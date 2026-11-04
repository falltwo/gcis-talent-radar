"""API contract, real SQLite transitions, authorization and failure-path tests."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from api.main import app
from api.recruitment import get_service
from recruitment.auth import Principal
from recruitment.models import Delivery
from recruitment.service import RecruitmentService


HR = "h" * 40
RECRUITER = "r" * 40
OTHER = "o" * 40


@pytest.fixture
def api(tmp_path, monkeypatch):
    service = RecruitmentService(tmp_path / "recruitment.sqlite")
    monkeypatch.setenv("RECRUITMENT_API_TOKENS_JSON", json.dumps({
        HR: {"tenant_id": "company-a", "actor_id": "alice", "role": "hr"},
        RECRUITER: {"tenant_id": "company-a", "actor_id": "bob", "role": "recruiter"},
        OTHER: {"tenant_id": "company-b", "actor_id": "eve", "role": "hr"},
    }))
    import api.recruitment as routes
    monkeypatch.setattr(routes, "get_service", lambda: service)

    def request(method, path, body=None, token=HR):
        async def call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                return await client.request(method, "/api/recruitment" + path, json=body,
                                            headers={} if token is None else {"Authorization": "Bearer " + token})
        return asyncio.run(call())
    request.service = service
    return request


def requirement(**overrides):
    return {"title": "CNC操作員", "district": "大雅區", "shift": "日班", "headcount": 3,
            "required_skills": ["CNC"], "trainable_skills": ["製圖"], "min_experience_months": 12,
            "salary_min": 35000, "salary_max": 45000, **overrides}


def candidate(**overrides):
    return {"source": "104", "external_ref": "authorized-001", "origin": "APPLIED",
            "display_name": "測試候選人", "skills": ["cnc"], "available_shifts": ["日班"],
            "districts": ["大雅區"], "experience_months": 24, "rights_confirmed": True,
            "rights_basis": "企業獲授權匯入的測試資料", "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(), **overrides}


def approved(api):
    response = api("POST", "/requests", requirement())
    assert response.status_code == 201, response.text
    req = response.json()["id"]
    assert api("POST", f"/requests/{req}/approve", {"expected_revision": 1}).status_code == 200
    return req


def imported(api, req=None, **overrides):
    req = req or approved(api)
    response = api("POST", f"/requests/{req}/candidates", candidate(**overrides))
    assert response.status_code == 200, response.text
    return req, response.json()


def invitation(api, approve=True):
    req, application = imported(api)
    application_id = application["id"]
    assert api("POST", f"/applications/{application_id}/match").json()["decision"] == "MATCHED"
    response = api("POST", f"/applications/{application_id}/invitations", {"message": "邀請您討論CNC職務"})
    assert response.status_code == 201, response.text
    inv = response.json()["id"]
    if approve:
        assert api("POST", f"/invitations/{inv}/approve").status_code == 200
    return req, application, inv


def test_complete_manual_workflow_and_audit(api):
    req, application, inv = invitation(api)
    publication = api("POST", f"/requests/{req}/publications", {"platform": "104", "external_id": "job-1"})
    assert publication.status_code == 200
    assert api("POST", f"/requests/{req}/publications", {"platform": "104", "external_id": "job-1"}).json()["id"] == publication.json()["id"]
    sent = api("POST", f"/invitations/{inv}/manual-delivery", {"outcome": "SENT", "reference": "manual-receipt-1"})
    assert sent.json()["attempts"] == 1
    assert api("POST", f"/invitations/{inv}/manual-reply", {"outcome": "INTERESTED"}).status_code == 200
    for stage in ("INTERVIEW", "OFFERED", "HIRED"):
        assert api("POST", f"/applications/{application['id']}/stage", {"stage": stage}).json()["stage"] == stage
    assert api("GET", "/dashboard").json()["applications"] == {"HIRED": 1}
    events = api("GET", "/events").json()["items"]
    assert events[-1]["action"] == "APPLICATION_HIRED"
    assert "測試候選人" not in json.dumps(events, ensure_ascii=False)
    assert "邀請您" not in json.dumps(events, ensure_ascii=False)
    assert all(e["actor_id"] == "alice" for e in events)


@pytest.mark.parametrize("token", [None, "bad-token"])
def test_no_anonymous_access(api, token):
    assert api("GET", "/requests", token=token).status_code == 401


@pytest.mark.parametrize("config", ["", "[]", "{}", '{"short":{}}', '{"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx":{"tenant_id":"a","actor_id":"a","role":"admin"}}'])
def test_fail_closed_credentials(api, monkeypatch, config):
    monkeypatch.setenv("RECRUITMENT_API_TOKENS_JSON", config)
    assert api("GET", "/dashboard").status_code == 503


def test_recruiter_cannot_approve_or_send(api):
    req = api("POST", "/requests", requirement(), token=RECRUITER).json()["id"]
    assert api("POST", f"/requests/{req}/approve", {"expected_revision": 1}, token=RECRUITER).status_code == 403
    _, _, inv = invitation(api)
    assert api("POST", f"/invitations/{inv}/manual-delivery", {"outcome": "SENT", "reference": "x"}, token=RECRUITER).status_code == 403


def test_tenant_cannot_access_other_company(api):
    req, application, inv = invitation(api)
    assert api("GET", "/requests", token=OTHER).json()["items"] == []
    assert api("GET", "/applications", token=OTHER).json()["items"] == []
    assert api("GET", "/invitations", token=OTHER).json()["items"] == []
    assert api("GET", "/events", token=OTHER).json()["items"] == []
    assert api("GET", "/dashboard", token=OTHER).json()["applications"] == {}
    for path in (f"/requests/{req}/close", f"/applications/{application['id']}/match", f"/invitations/{inv}/approve"):
        assert api("POST", path, token=OTHER).status_code == 404
    assert api("DELETE", f"/candidates/{application['candidate_id']}", token=OTHER).status_code == 404
    assert api("GET", "/applications?request_id=" + req, token=OTHER).status_code == 404


@pytest.mark.parametrize("body", [requirement(salary_max=100), requirement(headcount=0), requirement(age=30), requirement(required_skills=[" "]), requirement(title="限男性CNC操作員")])
def test_invalid_or_protected_criteria_rejected(api, body):
    assert api("POST", "/requests", body).status_code == 422


def test_approved_requirement_is_immutable_and_draft_is_versioned(api):
    req = api("POST", "/requests", requirement()).json()["id"]
    assert api("PUT", f"/requests/{req}", requirement(headcount=5)).json()["revision"] == 2
    assert api("POST", f"/requests/{req}/approve", {"expected_revision": 1}).status_code == 409
    assert api("POST", f"/requests/{req}/approve", {"expected_revision": 2}).json()["approved_by"] == "alice"
    assert api("PUT", f"/requests/{req}", requirement()).status_code == 409


def test_requires_approval_before_import_or_publication(api):
    req = api("POST", "/requests", requirement()).json()["id"]
    assert api("POST", f"/requests/{req}/candidates", candidate()).status_code == 409
    assert api("POST", f"/requests/{req}/publications", {"platform": "104", "external_id": "1"}).status_code == 409


@pytest.mark.parametrize("overrides", [{"rights_confirmed": False}, {"expires_at": "2000-01-01T00:00:00Z"},
                                       {"expires_at": "2099-01-01T00:00:00Z"}, {"expires_at": "2099-01-01"},
                                       {"gender": "male"}, {"source": "unknown"}])
def test_import_requires_authorized_bounded_retention(api, overrides):
    assert api("POST", f"/requests/{approved(api)}/candidates", candidate(**overrides)).status_code == 422


@pytest.mark.parametrize("overrides,decision", [({"skills": None}, "NEEDS_REVIEW"), ({"available_shifts": None}, "NEEDS_REVIEW"),
                                               ({"skills": []}, "NOT_MATCHED"), ({"experience_months": 2}, "NOT_MATCHED"),
                                               ({"experience_months": None}, "NEEDS_REVIEW"), ({}, "MATCHED")])
def test_matching_distinguishes_missing_and_mismatch(api, overrides, decision):
    _, application = imported(api, **overrides)
    result = api("POST", f"/applications/{application['id']}/match").json()
    assert result["decision"] == decision
    assert result["request_revision"] == 1
    assert all({"criterion", "expected", "observed", "result"} <= set(x) for x in result["checks"])
    if decision == "NOT_MATCHED":
        assert api("POST", f"/applications/{application['id']}/invitations", {"message": "test"}).status_code == 409


def test_import_and_invitation_deduplication(api):
    req, application = imported(api)
    assert api("POST", f"/requests/{req}/candidates", candidate()).json()["id"] == application["id"]
    assert api("POST", f"/requests/{req}/candidates", candidate(skills=["different"])).status_code == 409
    assert api("POST", f"/applications/{application['id']}/invitations", {"message": "test"}).status_code == 409
    api("POST", f"/applications/{application['id']}/match")
    assert api("POST", f"/applications/{application['id']}/invitations", {"message": "test"}).status_code == 201
    assert api("POST", f"/applications/{application['id']}/invitations", {"message": "test again"}).status_code == 409
    assert api("POST", f"/applications/{application['id']}/match").status_code == 409


def test_send_requires_hr_approval_and_cannot_skip_stages(api):
    _, application, inv = invitation(api, approve=False)
    assert api("POST", f"/invitations/{inv}/manual-delivery", {"outcome": "SENT", "reference": "x"}).status_code == 409
    assert api("POST", f"/invitations/{inv}/manual-reply", {"outcome": "INTERESTED"}).status_code == 409
    assert api("POST", f"/applications/{application['id']}/stage", {"stage": "HIRED"}).status_code == 409


def test_delivery_idempotency_under_concurrent_retries(api):
    _, _, inv = invitation(api)
    principal = Principal("company-a", "alice", "hr")
    def send(_):
        return api.service.delivery(principal, inv, Delivery(outcome="SENT", reference="same-receipt"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(send, range(4)))
    assert all(row["attempts"] == 1 for row in rows)
    events = api("GET", "/events").json()["items"]
    assert sum(e["action"] == "MANUAL_DELIVERY_SENT" for e in events) == 1
    assert api("POST", f"/invitations/{inv}/manual-delivery", {"outcome": "SENT", "reference": "different"}).status_code == 409


def test_failed_delivery_retry_limit(api):
    _, _, inv = invitation(api)
    for i in range(3):
        failure = api("POST", f"/invitations/{inv}/manual-delivery", {"outcome": "FAILED", "reference": f"failed-{i}"})
        assert failure.json()["attempts"] == i + 1
        retry = api("POST", f"/invitations/{inv}/retry")
        assert retry.status_code == (200 if i < 2 else 409)


@pytest.mark.parametrize("action", ["close", "opt-out", "withdraw"])
def test_stop_conditions_cancel_queued_invitation(api, action):
    req, application, inv = invitation(api)
    if action == "close":
        assert api("POST", f"/requests/{req}/close").status_code == 200
    elif action == "opt-out":
        assert api("POST", f"/candidates/{application['candidate_id']}/opt-out").status_code == 200
    else:
        assert api("POST", f"/applications/{application['id']}/stage", {"stage": "WITHDRAWN"}).status_code == 200
    assert api("POST", f"/invitations/{inv}/manual-delivery", {"outcome": "SENT", "reference": "x"}).status_code == 409
    assert api("GET", "/invitations").json()["items"][0]["status"] == "CANCELLED"


@pytest.mark.parametrize("reply", ["DECLINED", "NO_RESPONSE"])
def test_terminal_response_stops_contact(api, reply):
    _, application, inv = invitation(api)
    api("POST", f"/invitations/{inv}/manual-delivery", {"outcome": "SENT", "reference": "x"})
    assert api("POST", f"/invitations/{inv}/manual-reply", {"outcome": reply}).status_code == 200
    assert api("POST", f"/applications/{application['id']}/invitations", {"message": "again"}).status_code == 409
    assert api("POST", f"/invitations/{inv}/retry").status_code == 409


def test_expiry_blocks_reads_sends_and_purge_cascades(api):
    _, application, inv = invitation(api)
    with api.service.connection() as conn:
        conn.execute("UPDATE recruitment_candidates SET expires_at='2000-01-01T00:00:00+00:00'")
    assert api("GET", f"/candidates/{application['candidate_id']}").status_code == 410
    assert api("GET", "/applications").json()["items"] == []
    assert api("GET", "/invitations").json()["items"] == []
    assert api("POST", f"/invitations/{inv}/manual-delivery", {"outcome": "SENT", "reference": "x"}).status_code == 409
    assert api("POST", "/retention/purge", token=OTHER).json()["deleted"] == 0
    assert api("POST", "/retention/purge").json()["deleted"] == 1
    with api.service.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM recruitment_applications").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM recruitment_invitations").fetchone()[0] == 0


def test_deletion_removes_candidate_evidence_and_messages(api):
    _, application, _ = invitation(api)
    assert api("DELETE", f"/candidates/{application['candidate_id']}").json() == {"deleted": True}
    assert api("GET", "/applications").json()["items"] == []
    assert api("GET", "/invitations").json()["items"] == []


def test_additive_migration_and_manual_platform_contract(api):
    RecruitmentService(api.service.db_path)
    assert api("GET", "/requests").status_code == 200
    capabilities = api("GET", "/platforms").json()
    assert capabilities["mode"] == "MANUAL"
    assert all(not p["automated_invitation"] for p in capabilities["platforms"])
    assert api("GET", "/requests?limit=10000").status_code == 422
    assert api("GET", "/events?offset=-1").status_code == 422


def test_audit_failure_rolls_back_business_change(api):
    with api.service.connection() as conn:
        conn.execute("CREATE TRIGGER reject_event BEFORE INSERT ON recruitment_events BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END")
    assert api("POST", "/requests", requirement()).status_code == 409
    assert api("GET", "/requests").json()["items"] == []


def test_hr_can_correct_evidence_and_old_match_is_invalidated(api):
    _, application = imported(api, skills=None)
    application_id = application["id"]
    assert api("POST", f"/applications/{application_id}/match").json()["decision"] == "NEEDS_REVIEW"
    evidence = {k: v for k, v in candidate().items() if k in {"display_name", "skills", "available_shifts", "districts", "experience_months"}}
    path = f"/candidates/{application['candidate_id']}/evidence"
    assert api("PUT", path, evidence, token=RECRUITER).status_code == 403
    assert api("PUT", path, evidence).status_code == 200
    assert api("GET", "/applications").json()["items"][0]["match_result"] is None
    assert api("POST", f"/applications/{application_id}/match").json()["decision"] == "MATCHED"
    api("POST", f"/applications/{application_id}/invitations", {"message": "test"})
    assert api("PUT", path, evidence).status_code == 409


def test_unknown_matching_requires_explicit_hr_acknowledgement(api):
    _, application = imported(api, skills=None)
    api("POST", f"/applications/{application['id']}/match")
    inv = api("POST", f"/applications/{application['id']}/invitations", {"message": "請確認技能"}).json()["id"]
    assert api("POST", f"/invitations/{inv}/approve").status_code == 409
    assert api("POST", f"/invitations/{inv}/approve", {"reviewed_unknowns": True}).status_code == 200


def test_agent_draft_does_not_persist_or_approve_requirements(api, monkeypatch):
    from types import SimpleNamespace
    import recruitment.drafting as drafting
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    seen = []
    def post(*args, **kwargs):
        seen.append(kwargs["json"])
        return SimpleNamespace(ok=True, json=lambda: {"choices": [{"message": {"content": json.dumps(requirement())}}]})
    monkeypatch.setattr(drafting.requests, "post", post)
    response = api("POST", "/requirements/prepare", {"needs": "大雅區招募三名CNC操作員，日班"})
    assert response.status_code == 200, response.text
    assert response.json()["requires_hr_review"] is True
    assert response.json()["persisted"] is False
    assert api("GET", "/requests").json()["items"] == []
    assert "test-secret" not in response.text
    assert seen[0]["response_format"]["type"] == "json_schema"
    assert api("GET", "/events").json()["items"][-1]["action"] == "REQUIREMENT_PREPARED_UNVERIFIED"


def test_agent_missing_fields_are_not_invented(api, monkeypatch):
    from types import SimpleNamespace
    import recruitment.drafting as drafting
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    fields = requirement(salary_min=None, salary_max=None, headcount=None)
    monkeypatch.setattr(drafting.requests, "post", lambda *a, **k: SimpleNamespace(ok=True, json=lambda: {"choices": [{"message": {"content": json.dumps(fields)}}]}))
    result = api("POST", "/requirements/prepare", {"needs": "大雅區招募CNC操作員"}).json()
    assert result["ready_for_structured_submission"] is False
    assert {"salary_min", "salary_max", "headcount"} <= set(result["missing_fields"])


@pytest.mark.parametrize("mode", ["missing_key", "timeout", "provider_reject", "malformed", "protected_traits"])
def test_agent_draft_fails_safely(api, monkeypatch, mode):
    from types import SimpleNamespace
    import recruitment.drafting as drafting
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    def post(*args, **kwargs):
        if mode == "timeout":
            raise drafting.requests.Timeout("do not leak provider headers")
        return SimpleNamespace(ok=mode != "provider_reject", json=lambda: {"choices": []})
    monkeypatch.setattr(drafting.requests, "post", post)
    if mode == "missing_key":
        monkeypatch.delenv("OPENROUTER_API_KEY")
    needs = "招募只限男性操作員" if mode == "protected_traits" else "大雅區招募CNC操作員"
    response = api("POST", "/requirements/prepare", {"needs": needs})
    assert response.status_code == (503 if mode == "missing_key" else 422 if mode == "protected_traits" else 502)
    assert "test-secret" not in response.text
    assert "headers" not in response.text
    assert api("GET", "/requests").json()["items"] == []
