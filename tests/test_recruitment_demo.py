"""Browser demo is isolated from enterprise credentials and production data."""
import pytest
from fastapi.testclient import TestClient

from api.main import app
import api.recruitment_demo as demo


@pytest.fixture
def client(monkeypatch):
    registry = demo.DemoSessions()
    monkeypatch.setattr(demo, "sessions", registry)
    import api.recruitment as production
    def forbidden():
        pytest.fail("Demo accessed production recruitment database")
    monkeypatch.setattr(production, "get_service", forbidden)
    monkeypatch.delenv("RECRUITMENT_API_TOKENS_JSON", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(app) as c:
        yield c
    for session in registry.sessions.values():
        session["directory"].cleanup()


def test_demo_page_and_real_backend_success_path(client):
    page = client.get("/recruitment-demo")
    assert page.status_code == 200
    assert "模擬展示環境" in page.text
    assert "以示範 HR 核准" in page.text
    start = client.post("/api/recruitment-demo/start", json={"scenario": "SUCCESS"})
    assert start.status_code == 200
    assert "HttpOnly" in start.headers["set-cookie"]
    assert "SameSite=strict" in start.headers["set-cookie"]
    assert start.json()["uses_production_database"] is False
    assert start.json()["publication"]["status"] == "PENDING_APPROVAL"
    assert client.post("/api/recruitment-demo/approve").json()["publication"]["status"] == "PROCESSING"
    result = client.post("/api/recruitment-demo/complete").json()
    assert result["publication"]["status"] == "SUCCEEDED"
    assert result["publication"]["sent_to_platform"] is False
    state = client.get("/api/recruitment-demo/state")
    assert state.json() == result
    assert state.headers["cache-control"] == "no-store"


def test_failure_retry_and_reset(client):
    client.post("/api/recruitment-demo/start", json={"scenario": "FAILURE"})
    client.post("/api/recruitment-demo/approve")
    assert client.post("/api/recruitment-demo/complete").json()["publication"]["status"] == "FAILED"
    assert client.post("/api/recruitment-demo/retry", json={"scenario": "SUCCESS"}).json()["publication"]["status"] == "PENDING_APPROVAL"
    client.post("/api/recruitment-demo/approve")
    assert client.post("/api/recruitment-demo/complete").json()["publication"]["status"] == "SUCCEEDED"
    reset = client.post("/api/recruitment-demo/start", json={"scenario": "SUCCESS"}).json()
    assert reset["publication"]["attempts"] == 0
    assert len(demo.sessions.sessions) == 1


def test_browser_sessions_do_not_share_data(client):
    first = client.post("/api/recruitment-demo/start", json={"scenario": "SUCCESS"}).json()
    with TestClient(app) as other:
        assert other.get("/api/recruitment-demo/state").status_code == 204
        second = other.post("/api/recruitment-demo/start", json={"scenario": "FAILURE"}).json()
        assert first["publication"]["id"] != second["publication"]["id"]
        assert other.post("/api/recruitment-demo/approve").status_code == 200
    assert client.get("/api/recruitment-demo/state").json()["publication"]["status"] == "PENDING_APPROVAL"


@pytest.mark.parametrize("path,body", [("start", {"scenario": "SUCCESS"}), ("approve", None), ("complete", None), ("retry", {"scenario": "SUCCESS"})])
def test_cross_origin_mutations_rejected(client, path, body):
    client.post("/api/recruitment-demo/start", json={"scenario": "SUCCESS"})
    assert client.post("/api/recruitment-demo/" + path, json=body, headers={"Origin": "https://unrelated.example"}).status_code == 403


def test_expired_or_invalid_cookie_cannot_access_state(client):
    client.post("/api/recruitment-demo/start", json={"scenario": "SUCCESS"})
    for session in demo.sessions.sessions.values():
        session["expires"] = 0
    assert client.get("/api/recruitment-demo/state").status_code == 204
    assert demo.sessions.sessions == {}
    assert client.post("/api/recruitment-demo/approve").status_code == 404


def test_demo_cannot_accept_real_ids_credentials_or_live_mode(client):
    for field in ("tenant_id", "request_id", "token", "mode"):
        assert client.post("/api/recruitment-demo/start", json={"scenario": "SUCCESS", field: "anything"}).status_code == 422
    assert client.post("/api/recruitment-demo/start", json={"scenario": "LIVE"}).status_code == 422
