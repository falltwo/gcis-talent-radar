"""The model writes the advice sentences, but every number comes from the facts the page sent."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.site_advice import router
from engine import site_advice
from sourcing import llm

FACTS = [
    {"id": "f1", "label": "太平區相關科系畢業生", "value": "2,744 人"},
    {"id": "f2", "label": "太平區每位畢業生對應的職缺需求", "value": "0.14"},
    {"id": "f3", "label": "南區製造類職缺筆數", "value": "8 筆（樣本太少）"},
]
REQUEST = {"districts": ["太平區", "大里區", "南區"], "industry": "機械設備業", "role": "CNC 技術員", "facts": FACTS}


def make_client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_without_a_key_the_model_is_not_called(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    assert site_advice.advise(REQUEST)["reason"] == "no_key"


def test_placeholders_are_filled_from_the_facts(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"sentences": [
        "太平區附近相關科系畢業生約 {f1}，每位畢業生對應 {f2} 個職缺需求，找學校合作最划算。"]})
    result = site_advice.advise(REQUEST)
    assert result["source"] == "llm"
    assert result["sentences"] == ["太平區附近相關科系畢業生約 2,744 人，每位畢業生對應 0.14 個職缺需求，找學校合作最划算。"]


def test_a_sentence_with_its_own_digits_or_unknown_ids_is_dropped(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"sentences": [
        "太平區有 3000 位畢業生。",            # a number the model wrote itself
        "大里區職缺需求是 {f9}。",              # an id that does not exist
        "南區的職缺只有 {f3}，看不出招募壓力。",  # fine
        "西屯區薪資高了 ２０％。"]})              # full-width digits and percent
    assert site_advice.advise(REQUEST)["sentences"] == ["南區的職缺只有 8 筆（樣本太少），看不出招募壓力。"]


def test_nothing_usable_means_unavailable(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"sentences": ["共有 12 所學校。"]})
    assert site_advice.advise(REQUEST)["reason"] == "nothing_valid"
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: None)
    assert site_advice.advise(REQUEST)["reason"] == "model_failed"


def test_at_most_four_sentences_and_a_length_cap(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"sentences": ["句子{f1}。"] * 6 + ["長" * 200]})
    assert len(site_advice.advise(REQUEST)["sentences"]) == 4


def test_request_uses_strict_routing_and_tells_the_model_not_to_pick_a_district(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    seen = {}
    def fake(system, user, name, schema, **kwargs):
        seen.update(kwargs, system=system, user=user)
        return None
    monkeypatch.setattr(llm, "chat_json", fake)
    site_advice.advise(REQUEST)
    assert seen["provider"] == {"require_parameters": True} and seen["timeout"][1] <= 8
    assert "不要替使用者決定" in seen["system"] and '"f1"' in seen["user"]


def test_api_validates_the_payload():
    api = make_client()
    bad_id = {**REQUEST, "facts": [{"id": "x; drop", "label": "a", "value": "b"}]}
    too_many = {**REQUEST, "districts": ["太平區", "大里區", "南區", "西屯區"]}
    not_a_district = {**REQUEST, "districts": ["區" * 5000]}
    long_value = {**REQUEST, "facts": [{"id": "f1", "label": "a", "value": "字" * 41}]}
    for body in (bad_id, too_many, long_value, not_a_district):
        assert api.post("/api/site-advice", json=body).status_code == 422


def test_api_returns_the_result(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    response = make_client().post("/api/site-advice", json=REQUEST)
    assert response.status_code == 200 and response.json()["source"] == "unavailable"


def test_citation_dumps_and_number_heavy_sentences_are_dropped(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"sentences": [
        "大里區需求最高（{f1}、{f2}、{f3}）。",
        "數字很多 {f1}、{f2}、{f3}、{f1}。",
        "太平區附近畢業生約 {f1}。"]})
    assert site_advice.advise(REQUEST)["sentences"] == ["太平區附近畢業生約 2,744 人。"]


def test_calls_are_capped_per_client(monkeypatch):
    from engine import model_budget
    model_budget.reset()
    monkeypatch.setenv("SITE_MODEL_CALLS_PER_CLIENT_PER_MINUTE", "2")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    api = make_client()
    codes = [api.post("/api/site-advice", json=REQUEST).status_code for _ in range(3)]
    model_budget.reset()
    assert codes == [200, 200, 429]


REQUIRED = {**REQUEST, "facts": [{**FACTS[0]}, {**FACTS[1], "required": True}, {**FACTS[2], "required": True}]}


def test_every_required_fact_must_be_mentioned(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    site_advice.clear_cache()
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"sentences": ["太平區每位畢業生對應 {f2} 個職缺需求。"]})
    assert site_advice.advise(REQUIRED)["reason"] == "missing_required"
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"sentences": [
        "太平區每位畢業生對應 {f2} 個職缺需求。", "南區職缺只有 {f3}，看不出招募壓力。"]})
    assert site_advice.advise(REQUIRED)["source"] == "llm"


def test_required_ids_are_named_in_the_prompt(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    site_advice.clear_cache()
    seen = {}
    monkeypatch.setattr(llm, "chat_json", lambda system, user, *a, **k: seen.update(user=user))
    site_advice.advise(REQUIRED)
    assert '"必須提到": ["f2", "f3"]' in seen["user"]


def test_same_request_is_served_from_cache_and_failures_are_not_cached(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    site_advice.clear_cache()
    calls = []
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: calls.append(1))
    assert site_advice.lookup(REQUEST) is None
    site_advice.advise(REQUEST)
    assert site_advice.lookup(REQUEST) is None  # a failed call is not stored
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: calls.append(1) or {"sentences": ["太平區畢業生約 {f1}。"]})
    first = site_advice.advise(REQUEST)
    hit = site_advice.lookup(REQUEST)
    assert hit["sentences"] == first["sentences"] and hit["cached"] is True and hit["usage"]["cost_usd"] == 0
    changed = {**REQUEST, "role": "廠長"}
    assert site_advice.lookup(changed) is None
    assert len(calls) == 2


def test_api_serves_cache_hits_without_spending_the_budget(monkeypatch):
    from engine import model_budget
    model_budget.reset()
    site_advice.clear_cache()
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setenv("SITE_MODEL_CALLS_PER_CLIENT_PER_MINUTE", "1")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"sentences": ["太平區畢業生約 {f1}。"]})
    api = make_client()
    codes = [api.post("/api/site-advice", json=REQUEST).status_code for _ in range(3)]
    model_budget.reset()
    site_advice.clear_cache()
    assert codes == [200, 200, 200]


def test_chinese_quantities_count_as_the_models_own_numbers(monkeypatch):
    # Review on #49: 十萬元 and 兩成 are not in the facts, so the answer must fall back, not be shown or cached.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    site_advice.clear_cache()
    only = {**REQUEST, "facts": [{**FACTS[0], "required": True}]}
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"sentences": [
        "太平區附近畢業生為 {f1}，每月起薪應開到十萬元，比其他區多兩成。"]})
    assert site_advice.advise(only)["reason"] == "nothing_valid"
    assert site_advice.lookup(only) is None
    for claim in ["約一半的職缺在南區。", "大里區薪資高出三成。", "職缺是太平區的兩倍。", "五分之一的工廠在招人。", "缺工約一萬人。"]:
        assert site_advice._sentence(claim, {}) is None, claim


def test_ordinary_words_with_numeral_characters_are_kept():
    for plain in ["三區之中，太平區比較適合一起找學校合作。", "南區資料不足，一般建議先進一步確認。", "每百家工廠的職缺偏少，十分適合從學校招人。"]:
        assert site_advice._sentence(plain, {}) == plain
