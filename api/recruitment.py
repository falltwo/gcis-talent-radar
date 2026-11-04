"""Recruitment endpoints. Every route is authenticated and tenant-scoped."""
from functools import lru_cache

from fastapi import APIRouter, Depends, Query

from config import DB_PATH
from recruitment.auth import Principal, authenticate
from recruitment.models import (CandidateEvidence, CandidateImport, Delivery, DraftInput, InvitationApproval,
                                InvitationDraft, Publication, Reply, RequestApproval, Requirement,
                                SimulationCreate, SimulationRetry, StageChange)
from recruitment.service import RecruitmentService


router = APIRouter(prefix="/api/recruitment", tags=["Recruitment"])


@lru_cache(maxsize=1)
def get_service():
    # Additive migration is lazy: existing official-data routes need no new config.
    return RecruitmentService(DB_PATH)


def context(principal: Principal = Depends(authenticate)):
    # Authentication runs before opening/initializing the database.
    return principal, get_service()


@router.get("/platforms")
def platforms(ctx=Depends(context)):
    return {"mode": "MANUAL", "platforms": [
        {"name": name, "automated_publication": False, "automated_talent_search": False,
         "automated_invitation": False, "automated_reply_sync": False, "simulated_publication": name == "104"}
        for name in ("104", "1111")
    ], "supported_modes": ["MANUAL", "SIMULATION"],
       "notice": "Manual records and isolated 104 simulation only; no messages are sent and no platform APIs are called."}


@router.post("/requests/{request_id}/simulated-publications", status_code=201)
def create_simulation(request_id: str, body: SimulationCreate, ctx=Depends(context)):
    principal, service = ctx
    return service.create_simulation(principal, request_id, body)


@router.get("/simulated-publications")
def list_simulations(request_id: str | None = None, limit: int = Query(50, ge=1, le=200),
                     offset: int = Query(0, ge=0), ctx=Depends(context)):
    principal, service = ctx
    return service.list_simulations(principal, limit, offset, request_id)


@router.get("/simulated-publications/{simulation_id}")
def get_simulation(simulation_id: str, ctx=Depends(context)):
    principal, service = ctx
    return service.simulation(principal, simulation_id)


@router.post("/simulated-publications/{simulation_id}/approve")
def approve_simulation(simulation_id: str, ctx=Depends(context)):
    principal, service = ctx
    return service.approve_simulation(principal, simulation_id)


@router.post("/simulated-publications/{simulation_id}/complete")
def complete_simulation(simulation_id: str, ctx=Depends(context)):
    principal, service = ctx
    return service.complete_simulation(principal, simulation_id)


@router.post("/simulated-publications/{simulation_id}/retry")
def retry_simulation(simulation_id: str, body: SimulationRetry, ctx=Depends(context)):
    principal, service = ctx
    return service.retry_simulation(principal, simulation_id, body)


@router.post("/requests", status_code=201)
def create_request(body: Requirement, ctx=Depends(context)):
    principal, service = ctx
    return service.requirement(principal, body)


@router.post("/requirements/prepare")
def prepare_requirement(body: DraftInput, ctx=Depends(context)):
    principal, service = ctx
    return service.prepare(principal, body)


@router.put("/requests/{request_id}")
def update_request(request_id: str, body: Requirement, ctx=Depends(context)):
    principal, service = ctx
    return service.requirement(principal, body, request_id)


@router.post("/requests/{request_id}/approve")
def approve_request(request_id: str, body: RequestApproval, ctx=Depends(context)):
    principal, service = ctx
    return service.approve(principal, request_id, body.expected_revision)


@router.post("/requests/{request_id}/close")
def close_request(request_id: str, ctx=Depends(context)):
    principal, service = ctx
    return service.close(principal, request_id)


@router.post("/requests/{request_id}/publications")
def record_publication(request_id: str, body: Publication, ctx=Depends(context)):
    principal, service = ctx
    return service.publish(principal, request_id, body)


@router.post("/requests/{request_id}/candidates")
def import_candidate(request_id: str, body: CandidateImport, ctx=Depends(context)):
    principal, service = ctx
    return service.import_candidate(principal, request_id, body)


@router.get("/candidates/{candidate_id}")
def get_candidate(candidate_id: str, ctx=Depends(context)):
    principal, service = ctx
    return service.candidate(principal, candidate_id)


@router.put("/candidates/{candidate_id}/evidence")
def correct_candidate(candidate_id: str, body: CandidateEvidence, ctx=Depends(context)):
    principal, service = ctx
    return service.correct_candidate(principal, candidate_id, body)


@router.post("/candidates/{candidate_id}/opt-out")
def opt_out(candidate_id: str, ctx=Depends(context)):
    principal, service = ctx
    return service.opt_out(principal, candidate_id)


@router.delete("/candidates/{candidate_id}")
def delete_candidate(candidate_id: str, ctx=Depends(context)):
    principal, service = ctx
    return service.delete_candidate(principal, candidate_id)


@router.post("/retention/purge")
def purge_expired(ctx=Depends(context)):
    principal, service = ctx
    return service.purge(principal)


@router.post("/applications/{application_id}/match")
def match(application_id: str, ctx=Depends(context)):
    principal, service = ctx
    return service.match(principal, application_id)


@router.post("/applications/{application_id}/invitations", status_code=201)
def draft_invitation(application_id: str, body: InvitationDraft, ctx=Depends(context)):
    principal, service = ctx
    return service.draft_invitation(principal, application_id, body)


@router.post("/invitations/{invitation_id}/approve")
def approve_invitation(invitation_id: str, body: InvitationApproval = InvitationApproval(), ctx=Depends(context)):
    principal, service = ctx
    return service.approve_invitation(principal, invitation_id, body.reviewed_unknowns)


@router.post("/invitations/{invitation_id}/manual-delivery")
def record_delivery(invitation_id: str, body: Delivery, ctx=Depends(context)):
    principal, service = ctx
    return service.delivery(principal, invitation_id, body)


@router.post("/invitations/{invitation_id}/retry")
def retry(invitation_id: str, ctx=Depends(context)):
    principal, service = ctx
    return service.retry(principal, invitation_id)


@router.post("/invitations/{invitation_id}/manual-reply")
def record_reply(invitation_id: str, body: Reply, ctx=Depends(context)):
    principal, service = ctx
    return service.reply(principal, invitation_id, body)


@router.post("/applications/{application_id}/stage")
def change_stage(application_id: str, body: StageChange, ctx=Depends(context)):
    principal, service = ctx
    return service.stage(principal, application_id, body)


@router.get("/dashboard")
def dashboard(ctx=Depends(context)):
    principal, service = ctx
    return service.dashboard(principal)


# Explicit list endpoints keep table names out of caller control.
@router.get("/requests")
def list_requests(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), ctx=Depends(context)):
    principal, service = ctx
    return service.listing(principal, "requests", limit, offset)


@router.get("/applications")
def list_applications(request_id: str | None = None, limit: int = Query(50, ge=1, le=200),
                      offset: int = Query(0, ge=0), ctx=Depends(context)):
    principal, service = ctx
    return service.listing(principal, "applications", limit, offset, request_id)


@router.get("/invitations")
def list_invitations(request_id: str | None = None, limit: int = Query(50, ge=1, le=200),
                     offset: int = Query(0, ge=0), ctx=Depends(context)):
    principal, service = ctx
    return service.listing(principal, "invitations", limit, offset, request_id)


@router.get("/publications")
def list_publications(request_id: str | None = None, limit: int = Query(50, ge=1, le=200),
                      offset: int = Query(0, ge=0), ctx=Depends(context)):
    principal, service = ctx
    return service.listing(principal, "jobs", limit, offset, request_id)


@router.get("/events")
def list_events(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), ctx=Depends(context)):
    principal, service = ctx
    return service.listing(principal, "events", limit, offset)
