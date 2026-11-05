"""選址需求文字解析：模型只能從前端給的清單選，失敗就讓前端改用關鍵字規則。不連網，模型回應用假的。"""
import pytest
from fastapi.testclient import TestClient

from engine import site_intent
from sourcing import llm

INDUSTRIES = ["機械設備業", "金屬製品業", "電子零組件業"]
CRITERIA = [{"id": "vitality", "label": "市場活力"}, {"id": "cluster", "label": "同業群聚"},
            {"id": "transport", "label": "交通便利"}]
DEPARTMENTS = ["機械", "電機", "化工"]


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    answer = {}
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: answer.get("out"))
    return answer


def parse(text="做螺絲的工廠，不需要靠近交流道，想找車床師傅"):
    return site_intent.parse_intent(text, "", INDUSTRIES, CRITERIA, DEPARTMENTS)


def test_model_answer_is_kept_only_within_the_lists(model):
    model["out"] = {"industry": "金屬製品業", "boost": ["cluster", "cluster", "transport", "rocket"],
                    "avoid": ["transport"], "role": "車床技術員", "senior": None, "department": "機械"}
    out = parse()
    assert out["available"] and out["source"] == "llm"
    assert out["industry"] == "金屬製品業" and out["role"] == "車床技術員" and out["department"] == "機械"
    assert out["boost"] == ["cluster"] and out["avoid"] == ["transport"]  # 不考慮的不會同時加重；清單外的丟掉
    model["out"] = {"industry": "太空產業", "boost": [], "avoid": [], "role": "30歲以下男性作業員",
                    "senior": "x" * 30, "department": "天文"}
    out = parse()
    assert out["industry"] is None and out["role"] is None and out["senior"] is None and out["department"] is None


def test_no_key_or_model_failure_lets_the_frontend_use_keywords(model, monkeypatch):
    model["out"] = None
    assert parse()["available"] is False
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert parse()["available"] is False
    assert site_intent.parse_intent("", "", INDUSTRIES, CRITERIA, DEPARTMENTS)["available"] is False


def test_endpoint(model):
    from api.main import app
    model["out"] = {"industry": "機械設備業", "boost": ["cluster"], "avoid": [], "role": None,
                    "senior": "廠長", "department": "機械"}
    client = TestClient(app)
    res = client.post("/api/site-scan/intent", json={"text": "機械工廠找廠長", "industries": INDUSTRIES,
                                                     "criteria": CRITERIA, "departments": DEPARTMENTS})
    assert res.status_code == 200 and res.json()["senior"] == "廠長"
    assert client.post("/api/site-scan/intent", json={"text": "x" * 301, "industries": INDUSTRIES,
                                                      "criteria": CRITERIA}).status_code == 422
