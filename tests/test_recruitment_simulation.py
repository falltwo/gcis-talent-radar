"""Simulation cannot reach 104 or contaminate manual publication records."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from recruitment.auth import Principal
from recruitment.models import SimulationCreate
from recruitment.service import RecruitmentService
from tests.test_recruitment import HR, OTHER, RECRUITER, api, approved, requirement


def create(api, scenario="SUCCESS", req=None, key="demo-1"):
    req = req or approved(api)
    response = api("POST", f"/requests/{req}/simulated-publications", {"idempotency_key": key, "scenario": scenario})
    assert response.status_code == 201, response.text
    return req, response.json()


def assert_simulated(result, status):
    assert result["status"] == status
    assert result["mode"] == "SIMULATION"
    assert result["is_simulated"] is True
    assert result["sent_to_platform"] is False
    assert "模擬" in result["status_label"]
    assert "未送至104" in result["notice"]
    assert "url" not in result


@pytest.mark.parametrize("scenario,status", [("SUCCESS", "SUCCEEDED"), ("FAILURE", "FAILED")])
def test_simulation_states_without_any_network(api, monkeypatch, scenario, status):
    import ipaddress
    import socket
    import requests
    def forbid(*args, **kwargs):
        pytest.fail("Simulation attempted an outbound network call")
    original_connect = socket.socket.connect
    def outbound_guard(sock, address):
        # Windows asyncio creates a local socketpair even for in-process ASGI.
        if isinstance(address, tuple) and ipaddress.ip_address(address[0]).is_loopback:
            return original_connect(sock, address)
        forbid()
    monkeypatch.setattr(socket.socket, "connect", outbound_guard)
    monkeypatch.setattr(requests.sessions.Session, "request", forbid)
    req, row = create(api, scenario)
    identifier = row["id"]
    assert_simulated(row, "PENDING_APPROVAL")
    assert row["request_revision"] == 1
    assert row["snapshot"]["title"] == "CNC操作員"
    processing = api("POST", f"/simulated-publications/{identifier}/approve").json()
    assert_simulated(processing, "PROCESSING")
    assert processing["approved_by"] == "alice"
    assert processing["attempts"] == 1
    done = api("POST", f"/simulated-publications/{identifier}/complete").json()
    assert_simulated(done, status)
    if scenario == "SUCCESS":
        assert done["simulated_job_id"].startswith("sim104-")
        assert done["error_code"] is None
    else:
        assert done["simulated_job_id"] is None
        assert done["error_code"] == "SIMULATED_PLATFORM_FAILURE"
    assert api("GET", "/publications").json()["items"] == []
    dashboard = api("GET", "/dashboard").json()["simulated_publications"]
    assert dashboard["counts"] == {status: 1}
    assert dashboard["sent_to_platform"] is False
    assert api("GET", f"/simulated-publications/{identifier}").json() == done


def test_simulation_requires_approved_request(api):
    req = api("POST", "/requests", requirement()).json()["id"]
    response = api("POST", f"/requests/{req}/simulated-publications", {"idempotency_key": "draft"})
    assert response.status_code == 409


def test_recruiter_can_request_simulation_but_only_hr_drives_it(api):
    req = approved(api)
    response = api("POST", f"/requests/{req}/simulated-publications", {"idempotency_key": "recruiter"}, token=RECRUITER)
    identifier = response.json()["id"]
    for action, body in (("approve", None), ("complete", None), ("retry", {"scenario": "SUCCESS"})):
        assert api("POST", f"/simulated-publications/{identifier}/{action}", body, token=RECRUITER).status_code == 403


@pytest.mark.parametrize("token,status", [(None, 401), (OTHER, 404)])
def test_simulation_tenant_and_auth_boundary(api, token, status):
    req, row = create(api)
    identifier = row["id"]
    assert api("GET", f"/simulated-publications/{identifier}", token=token).status_code == status
    assert api("POST", f"/simulated-publications/{identifier}/approve", token=token).status_code == status
    assert api("POST", f"/simulated-publications/{identifier}/complete", token=token).status_code == status
    assert api("POST", f"/simulated-publications/{identifier}/retry", {"scenario": "SUCCESS"}, token=token).status_code == status
    if token == OTHER:
        assert api("GET", "/simulated-publications", token=token).json()["items"] == []
        assert api("GET", "/simulated-publications?request_id=" + req, token=token).status_code == 404
        assert api("POST", f"/requests/{req}/simulated-publications", {"idempotency_key": "other"}, token=token).status_code == 404


def test_creation_deduplicates_concurrent_requests(api):
    req = approved(api)
    principal = Principal("company-a", "alice", "hr")
    model = SimulationCreate(idempotency_key="parallel")
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: api.service.create_simulation(principal, req, model), range(4)))
    assert len({r["id"] for r in rows}) == 1
    assert len(api("GET", "/simulated-publications").json()["items"]) == 1
    assert api("POST", f"/requests/{req}/simulated-publications", {"idempotency_key": "parallel", "scenario": "FAILURE"}).status_code == 409
    assert api("POST", f"/requests/{req}/simulated-publications", {"idempotency_key": "different"}).status_code == 409


def test_approval_and_completion_are_idempotent(api):
    _, row = create(api)
    identifier = row["id"]
    assert api("POST", f"/simulated-publications/{identifier}/complete").status_code == 409
    for _ in range(2):
        assert api("POST", f"/simulated-publications/{identifier}/approve").json()["attempts"] == 1
    for _ in range(2):
        assert api("POST", f"/simulated-publications/{identifier}/complete").json()["status"] == "SUCCEEDED"
    actions = [r["action"] for r in api("GET", "/events").json()["items"]]
    assert actions.count("SIMULATION_104_PROCESSING") == 1
    assert actions.count("SIMULATION_104_SUCCEEDED") == 1
    assert api("POST", f"/simulated-publications/{identifier}/retry", {"scenario": "SUCCESS"}).status_code == 409


def test_failure_can_retry_with_success_but_requires_fresh_hr_approval(api):
    req, row = create(api, "FAILURE")
    identifier = row["id"]
    api("POST", f"/simulated-publications/{identifier}/approve")
    api("POST", f"/simulated-publications/{identifier}/complete")
    pending = api("POST", f"/simulated-publications/{identifier}/retry", {"scenario": "SUCCESS"}).json()
    assert_simulated(pending, "PENDING_APPROVAL")
    assert pending["approved_by"] is None
    assert pending["error_code"] is None
    assert api("POST", f"/simulated-publications/{identifier}/complete").status_code == 409
    api("POST", f"/simulated-publications/{identifier}/approve")
    done = api("POST", f"/simulated-publications/{identifier}/complete").json()
    assert_simulated(done, "SUCCEEDED")
    assert done["attempts"] == 2
    # Replay the original creation payload after retry; still returns this record.
    assert create(api, "FAILURE", req=req)[1]["id"] == identifier


def test_retry_cap_is_persisted(api):
    _, row = create(api, "FAILURE")
    identifier = row["id"]
    for i in range(3):
        assert api("POST", f"/simulated-publications/{identifier}/approve").json()["attempts"] == i + 1
        api("POST", f"/simulated-publications/{identifier}/complete")
        retry = api("POST", f"/simulated-publications/{identifier}/retry", {"scenario": "FAILURE"})
        assert retry.status_code == (200 if i < 2 else 409)


@pytest.mark.parametrize("state", ["PENDING_APPROVAL", "PROCESSING", "FAILED"])
def test_close_cancels_unfinished_simulation(api, state):
    req, row = create(api, "FAILURE")
    identifier = row["id"]
    if state != "PENDING_APPROVAL":
        api("POST", f"/simulated-publications/{identifier}/approve")
    if state == "FAILED":
        api("POST", f"/simulated-publications/{identifier}/complete")
    api("POST", f"/requests/{req}/close")
    assert_simulated(api("GET", f"/simulated-publications/{identifier}").json(), "CANCELLED")
    assert api("POST", f"/simulated-publications/{identifier}/complete").status_code == 409
    assert api("POST", f"/simulated-publications/{identifier}/retry", {"scenario": "SUCCESS"}).status_code == 409


def test_simulation_survives_restart_and_does_not_alter_manual_publications(api):
    req, row = create(api)
    api("POST", f"/requests/{req}/publications", {"platform": "104", "external_id": "manually-posted-123"})
    principal = Principal("company-a", "alice", "hr")
    restarted = RecruitmentService(api.service.db_path)
    assert_simulated(restarted.simulation(principal, row["id"]), "PENDING_APPROVAL")
    assert api("GET", "/publications").json()["items"][0]["external_id"] == "manually-posted-123"
    assert api("GET", "/platforms").json()["platforms"][0]["automated_publication"] is False
    assert api("GET", "/platforms").json()["platforms"][0]["simulated_publication"] is True


def test_simulation_write_rolls_back_on_audit_failure(api):
    req = approved(api)
    with api.service.connection() as conn:
        conn.execute("CREATE TRIGGER reject_simulation_event BEFORE INSERT ON recruitment_events BEGIN SELECT RAISE(ABORT, 'no audit'); END")
    assert api("POST", f"/requests/{req}/simulated-publications", {"idempotency_key": "rollback"}).status_code == 409
    assert api("GET", "/simulated-publications").json()["items"] == []


@pytest.mark.parametrize("body", [{"idempotency_key": "x", "mode": "LIVE"}, {"idempotency_key": "x", "platform": "104"}, {"idempotency_key": "x", "scenario": "LIVE"}])
def test_caller_cannot_switch_simulation_to_live_mode(api, body):
    assert api("POST", f"/requests/{approved(api)}/simulated-publications", body).status_code == 422
