"""Employer portal uses synthetic sessions and the real simulation state machine."""
import pytest
from fastapi.testclient import TestClient

from api.main import app
import api.mock104 as portal
from api.recruitment_demo import DemoSessions
from tests.test_recruitment import requirement


@pytest.fixture
def client(monkeypatch):
    registry = DemoSessions()
    monkeypatch.setattr(portal, "sessions", registry)
    import api.recruitment as production
    def forbidden():
        pytest.fail("Mock portal accessed production recruitment database")
    monkeypatch.setattr(production, "get_service", forbidden)
    with TestClient(app) as c:
        assert c.post("/api/mock104/start", json={}).status_code == 200
        yield c
    for session in registry.sessions.values():
        session["directory"].cleanup()


def job(**overrides):
    return {**requirement(), "company_name": "虛構示範企業", "description": "這是用來測試刊登流程的虛構職缺，不接受真實應徵。", "employment_type": "全職", **overrides}


def create(client, **overrides):
    response = client.post("/api/mock104/jobs", json=job(**overrides))
    assert response.status_code == 201, response.text
    return response.json()["selected_id"]


def test_portal_create_edit_submit_publish_and_close(client):
    assert "非 104 官方網站" in client.get("/mock104").text
    identifier = create(client)
    edited = client.put(f"/api/mock104/jobs/{identifier}", json=job(title="設備操作員"))
    assert edited.json()["jobs"][0]["data"]["title"] == "設備操作員"
    assert edited.json()["jobs"][0]["revision"] == 2
    for action, status in (("submit", "PENDING_APPROVAL"), ("approve", "PROCESSING"), ("complete", "SUCCEEDED"), ("close", "CLOSED")):
        response = client.post(f"/api/mock104/jobs/{identifier}/{action}", json={"scenario": "SUCCESS"})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["jobs"][0]["status"] == status
        assert result["sent_to_platform"] is False
        assert result["jobs"][0]["publication"]["sent_to_platform"] is False
    assert client.get("/api/mock104/state").json()["jobs"][0]["status"] == "CLOSED"


def test_drafts_survive_reloading_and_session_start(client):
    identifier = create(client, description="")
    state = client.post("/api/mock104/start", json={}).json()
    assert len(state["jobs"]) == 1
    assert state["jobs"][0]["id"] == identifier
    assert state["jobs"][0]["status"] == "DRAFT"
    assert client.post(f"/api/mock104/jobs/{identifier}/submit", json={}).status_code == 422


def test_failed_publication_can_retry_then_succeed(client):
    identifier = create(client)
    client.post(f"/api/mock104/jobs/{identifier}/submit", json={"scenario": "FAILURE"})
    client.post(f"/api/mock104/jobs/{identifier}/approve", json={})
    assert client.post(f"/api/mock104/jobs/{identifier}/complete", json={}).json()["jobs"][0]["status"] == "FAILED"
    client.post(f"/api/mock104/jobs/{identifier}/retry", json={"scenario": "SUCCESS"})
    client.post(f"/api/mock104/jobs/{identifier}/approve", json={})
    result = client.post(f"/api/mock104/jobs/{identifier}/complete", json={}).json()
    assert result["jobs"][0]["status"] == "SUCCEEDED"
    assert result["jobs"][0]["publication"]["attempts"] == 2


def test_only_draft_can_edit_and_submission_is_idempotent(client):
    identifier = create(client)
    for _ in range(2):
        assert client.post(f"/api/mock104/jobs/{identifier}/submit", json={}).status_code == 200
    assert client.put(f"/api/mock104/jobs/{identifier}", json=job(title="changed")).status_code == 409
    result = client.get("/api/mock104/state").json()
    assert result["jobs"][0]["data"]["title"] == "CNC操作員"


def test_job_ids_are_isolated_between_browsers(client):
    identifier = create(client)
    with TestClient(app) as other:
        assert other.get("/api/mock104/state").status_code == 204
        other.post("/api/mock104/start", json={})
        assert other.get("/api/mock104/state").json()["jobs"] == []
        assert other.put(f"/api/mock104/jobs/{identifier}", json=job()).status_code == 404
        assert other.post(f"/api/mock104/jobs/{identifier}/submit", json={}).status_code == 404


@pytest.mark.parametrize("path", ["start", "jobs"])
def test_cross_origin_writes_rejected(client, path):
    assert client.post("/api/mock104/" + path, json=job() if path == "jobs" else {}, headers={"Origin": "https://other.example"}).status_code == 403


@pytest.mark.parametrize("changes", [{"salary_max": 1}, {"headcount": 0}, {"mode": "LIVE"}, {"tenant_id": "company-a"}])
def test_invalid_and_live_fields_rejected(client, changes):
    assert client.post("/api/mock104/jobs", json=job(**changes)).status_code == 422

def test_manual_edit_then_submit_requires_current_reviewed_revision(client):
    identifier=create(client)
    changed=client.put('/api/mock104/jobs/'+identifier,json=job(title='人工調整的職缺',headcount=4)).json()
    row=next(r for r in changed['jobs'] if r['id']==identifier)
    stale=client.post('/api/mock104/jobs/'+identifier+'/submit',json={'expected_revision':row['revision']-1})
    assert stale.status_code==409
    assert client.get('/api/mock104/state').json()['jobs'][0]['status']=='DRAFT'
    submitted=client.post('/api/mock104/jobs/'+identifier+'/submit',json={'expected_revision':row['revision']})
    assert submitted.status_code==200,submitted.text
    result=submitted.json()['jobs'][0]
    assert result['status']=='PENDING_APPROVAL'
    assert result['data']['title']=='人工調整的職缺' and result['data']['headcount']==4
