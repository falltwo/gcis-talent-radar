"""The home page sends one sentence; the model may only pick from fixed options, and anything it gets wrong is dropped."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.site_intent import router
from engine import site_intent
from sourcing import llm

EMPTY = {"industry": None, "related_industries": [], "uncodable_question": None, "role": None, "senior_role": None,
         "hires": None, "emphasis": [], "unsupported": [], "unsupported_phrases": []}


def answer(**fields):
    return {**EMPTY, **fields}


def make_client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_without_a_key_the_model_is_not_called(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    result = site_intent.parse("精密機械加工廠，招 20 位 CNC 技術員", "")
    assert result["source"] == "unavailable" and result["reason"] == "no_key"


def test_valid_answer_is_kept(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: answer(
        industry="機械設備業", related_industries=["金屬製品業"], role="CNC 技術員", hires=20,
        emphasis=["cluster"], unsupported=["transport"], unsupported_phrases=["近交流道"]))
    result = site_intent.parse("精密機械加工廠與模具沖壓線，招 20 位 CNC 技術員，要供應鏈完整、近交流道", "")
    assert result["source"] == "llm"
    assert result["intent"] == answer(industry="機械設備業", related_industries=["金屬製品業"], role="CNC 技術員",
                                      hires=20, emphasis=["cluster"], unsupported=["transport"],
                                      unsupported_phrases=["近交流道"])


def test_values_outside_the_options_are_dropped(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: answer(
        industry="半導體業", related_industries=["半導體業", "塑膠製品業"], role="x" * 40, senior_role="廠長", hires=50,
        emphasis=["cluster", "cheap_land", "cluster"], unsupported=["transport", "moon"]))
    result = site_intent.parse("想在台中設廠，需要廠長", "")
    assert result["source"] == "llm"
    # 半導體業 is not an EE520 category, the role is too long, and 50 never appears in the text.
    assert result["intent"] == answer(related_industries=["塑膠製品業"], senior_role="廠長",
                                      emphasis=["cluster"], unsupported=["transport"])


def test_model_failure_reports_unavailable(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: None)
    assert site_intent.parse("機械工廠", "")["reason"] == "model_failed"
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: ["not", "an", "object"])
    assert site_intent.parse("機械工廠", "")["reason"] == "model_failed"


def test_request_asks_for_strict_schema_routing_and_a_short_timeout(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    seen = {}
    def fake(system, user, name, schema, **kwargs):
        seen.update(kwargs, schema=schema, user=user, system=system)
        return None
    monkeypatch.setattr(llm, "chat_json", fake)
    site_intent.parse("機械工廠", "上下游群聚優先")
    assert seen["provider"] == {"require_parameters": True}
    assert seen["timeout"][1] <= 8
    assert "機械設備業" in seen["schema"]["properties"]["industry"]["enum"]
    assert "上下游群聚優先" in seen["user"]
    # The model reads the official definition of each category, not just its name.
    assert "金屬熱處理業" in seen["system"] and "金屬表面處理業" in seen["system"]


def test_api_rejects_long_text_and_unknown_preference():
    api = make_client()
    assert api.post("/api/site-intent", json={"text": "字" * 201, "preference": ""}).status_code == 422
    assert api.post("/api/site-intent", json={"text": "機械", "preference": "隨便"}).status_code == 422


def test_api_returns_the_parse_result(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    response = make_client().post("/api/site-intent", json={"text": "機械工廠", "preference": "避開激烈競爭"})
    assert response.status_code == 200
    assert response.json()["source"] == "unavailable"


def test_sourcing_callers_keep_the_old_defaults(monkeypatch):
    # chat_json gained optional arguments; existing callers must still send the same request.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    sent = {}
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "{}"}}]}
    def post(url, headers, json, timeout):
        sent.update(json=json, timeout=timeout)
        return Response()
    monkeypatch.setattr(llm.requests, "post", post)
    llm.chat_json("s", "u", "n", {"type": "object"})
    assert sent["timeout"] == (10, 60) and "provider" not in sent["json"]


def test_preference_chip_is_applied_by_code_not_the_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: answer(emphasis=["vitality"]))
    assert site_intent.parse("食品工廠", "避開激烈競爭")["intent"]["emphasis"] == ["vitality", "competition"]
    assert site_intent.parse("食品工廠", "靠近交通樞紐")["intent"]["unsupported"] == ["transport"]


def test_a_role_the_user_never_wrote_is_dropped(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: answer(role="CNC技術員", senior_role="製程工程師"))
    intent = site_intent.parse("招 CNC 技術員", "")["intent"]
    assert intent["role"] == "CNC技術員" and intent["senior_role"] is None


def test_related_industries_are_capped_and_never_repeat_the_main_one(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: answer(
        industry="機械設備業", related_industries=["機械設備業", "金屬製品業", "基本金屬業", "塑膠製品業"]))
    assert site_intent.parse("機械工廠", "")["intent"]["related_industries"] == ["金屬製品業", "基本金屬業"]


def test_follow_up_question_only_when_the_industry_is_unknown(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: answer(uncodable_question="主要生產什麼產品？"))
    assert site_intent.parse("想在台中開工廠", "")["intent"]["uncodable_question"] == "主要生產什麼產品？"
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: answer(industry="食品及飼品業", uncodable_question="主要生產什麼？"))
    assert site_intent.parse("食品工廠", "")["intent"]["uncodable_question"] is None


def test_unsupported_phrases_must_be_the_users_words(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: answer(
        unsupported=["transport"], unsupported_phrases=["台74線", "大貨車進出方便", "靠近港口", "台74線"]))
    intent = site_intent.parse("大貨車進出方便，不要離國道交流道或台74線太遠", "")["intent"]
    assert intent["unsupported_phrases"] == ["台74線", "大貨車進出方便"]


def test_reference_file_covers_every_ee520_category():
    assert set(site_intent.DIVISIONS) == set(site_intent.INDUSTRIES) and len(site_intent.INDUSTRIES) == 26
    assert site_intent.DIVISIONS["金屬製品業"]["codes"] == ["25"]
