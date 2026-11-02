"""Mock job-board employer portal; all data stays in isolated demo SQLite."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field

from api.recruitment_demo import DEMO_HR, DemoSessions, same_origin
from recruitment.models import Requirement, SimulationCreate, SimulationRetry, StrictModel


router = APIRouter(prefix="/api/mock104", tags=["Mock job board"])
sessions = DemoSessions()
COOKIE = "mock104_demo"
DETAIL_SCHEMA = """CREATE TABLE IF NOT EXISTS mock_job_details (
    request_id TEXT PRIMARY KEY REFERENCES recruitment_requests(id),
    company_name TEXT NOT NULL, description TEXT NOT NULL,
    employment_type TEXT NOT NULL
)"""


class JobForm(Requirement):
    company_name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=5000)
    employment_type: Literal["全職", "兼職"] = "全職"


class ReviewScenario(StrictModel):
    scenario: Literal["SUCCESS", "FAILURE"] = "SUCCESS"


def snapshot(session):
    service = session["service"]
    requests = service.listing(DEMO_HR, "requests", 100, 0)["items"]
    publications = {row["request_id"]: row for row in service.list_simulations(DEMO_HR, 100, 0)["items"]}
    with service.connection() as conn:
        details = {row["request_id"]: dict(row) for row in conn.execute("SELECT * FROM mock_job_details").fetchall()}
    jobs = []
    for req in requests:
        if req["id"] not in details:
            continue
        publication = publications.get(req["id"])
        status = "CLOSED" if req["status"] == "CLOSED" else publication["status"] if publication else "DRAFT"
        jobs.append({"id": req["id"], "revision": req["revision"], "status": status,
                     "created_at": req["created_at"], "updated_at": req["updated_at"],
                     "data": {**req["data"], **{k: v for k, v in details[req["id"]].items() if k != "request_id"}},
                     "publication": publication})
    return {"jobs": jobs, "mode": "SIMULATION", "sent_to_platform": False,
            "notice": "獨立模擬求才平台，非104官方網站，不會刊登至104。"}


def get_session(request):
    return sessions.session(request.cookies.get(COOKIE))


def protect(request, response):
    same_origin(request)
    response.headers["Cache-Control"] = "no-store"


@router.post("/start")
def start(request: Request, response: Response):
    protect(request, response)
    key = request.cookies.get(COOKIE)
    try:
        with get_session(request) as session:
            return snapshot(session)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    key = sessions.start_empty()
    with sessions.session(key) as session:
        with session["service"].connection() as conn:
            conn.execute(DETAIL_SCHEMA)
        data = snapshot(session)
    response.set_cookie(COOKIE, key, httponly=True, samesite="strict", secure=request.url.scheme == "https",
                        max_age=1200, path="/api/mock104")
    return data


@router.get("/state")
def state(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        with get_session(request) as session:
            return snapshot(session)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return Response(status_code=204, headers={"Cache-Control": "no-store"})


def save_job(request, response, body, identifier=None):
    protect(request, response)
    with get_session(request) as session:
        service = session["service"]
        if identifier:
            # Check ownership and draft state before mutating either table.
            with service.connection() as conn:
                req = service.get(conn, "requests", identifier, DEMO_HR)
                if req["status"] != "DRAFT":
                    raise HTTPException(409, "只有草稿可以編輯。")
        elif len(snapshot(session)["jobs"]) >= 50:
            raise HTTPException(409, "每次展示最多建立50個職缺。")
        requirement = Requirement.model_validate(body.model_dump(include=set(Requirement.model_fields)))
        req = service.requirement(DEMO_HR, requirement, identifier)
        with service.connection() as conn:
            conn.execute("INSERT INTO mock_job_details VALUES(?,?,?,?) ON CONFLICT(request_id) DO UPDATE SET company_name=excluded.company_name,description=excluded.description,employment_type=excluded.employment_type",
                         (req["id"], body.company_name, body.description, body.employment_type))
        return {**snapshot(session), "selected_id": req["id"]}


@router.post("/jobs", status_code=201)
def create_job(body: JobForm, request: Request, response: Response):
    return save_job(request, response, body)


@router.put("/jobs/{identifier}")
def update_job(identifier: str, body: JobForm, request: Request, response: Response):
    return save_job(request, response, body, identifier)


@router.post("/jobs/{identifier}/submit")
def submit_job(identifier: str, body: ReviewScenario, request: Request, response: Response):
    protect(request, response)
    with get_session(request) as session:
        service = session["service"]
        with service.connection() as conn:
            req = service.get(conn, "requests", identifier, DEMO_HR)
            details = conn.execute("SELECT * FROM mock_job_details WHERE request_id=?", (identifier,)).fetchone()
            if details is None or len(details["description"].strip()) < 10:
                raise HTTPException(422, "請填寫至少10個字的工作內容後再送審。")
        if req["status"] == "DRAFT":
            service.approve(DEMO_HR, identifier, req["revision"])
        service.create_simulation(DEMO_HR, identifier, SimulationCreate(idempotency_key="mock-portal-submit", scenario=body.scenario))
        return {**snapshot(session), "selected_id": identifier}


@router.post("/jobs/{identifier}/{action}")
def action(identifier: str, action: Literal["approve", "complete", "close", "retry"],
           request: Request, response: Response, body: ReviewScenario = ReviewScenario()):
    protect(request, response)
    with get_session(request) as session:
        service = session["service"]
        if action == "close":
            service.close(DEMO_HR, identifier)
        else:
            with service.connection() as conn:
                service.get(conn, "requests", identifier, DEMO_HR)
                row = conn.execute("SELECT id FROM recruitment_simulated_publications WHERE request_id=?", (identifier,)).fetchone()
                if row is None:
                    raise HTTPException(409, "請先送出刊登申請。")
            if action == "approve":
                service.approve_simulation(DEMO_HR, row["id"])
            elif action == "complete":
                service.complete_simulation(DEMO_HR, row["id"])
            else:
                service.retry_simulation(DEMO_HR, row["id"], SimulationRetry(scenario=body.scenario))
        return {**snapshot(session), "selected_id": identifier}
