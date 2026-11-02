"""Public demonstration using isolated, bounded, short-lived synthetic databases."""
import secrets
import time
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response

from recruitment.auth import Principal
from recruitment.models import Requirement, SimulationCreate, SimulationRetry, StrictModel
from recruitment.service import RecruitmentService


router = APIRouter(prefix="/api/recruitment-demo", tags=["Isolated recruitment demo"])
COOKIE = "recruitment_demo_session"
DEMO_HR = Principal("synthetic-demo", "示範HR", "hr")


class DemoStart(StrictModel):
    scenario: Literal["SUCCESS", "FAILURE"] = "SUCCESS"


class DemoSessions:
    def __init__(self):
        self.lock = RLock()
        self.sessions = {}

    def cleanup(self):
        expired = [key for key, value in self.sessions.items() if value["expires"] <= time.monotonic()]
        for key in expired:
            self.sessions.pop(key)["directory"].cleanup()

    def start(self, previous, scenario):
        with self.lock:
            self.cleanup()
            if previous in self.sessions:
                self.sessions.pop(previous)["directory"].cleanup()
            if len(self.sessions) >= 32:
                raise HTTPException(503, "展示人數已達上限，請稍後重試。")
            directory = TemporaryDirectory(prefix="radar-demo-")
            try:
                service = RecruitmentService(Path(directory.name) / "demo.sqlite")
                req = service.requirement(DEMO_HR, Requirement(
                    title="CNC操作員", district="大雅區", shift="日班", headcount=3,
                    required_skills=["cnc"], trainable_skills=["機械製圖"],
                    min_experience_months=12, salary_min=35000, salary_max=45000,
                ))
                service.approve(DEMO_HR, req["id"], req["revision"])
                row = service.create_simulation(DEMO_HR, req["id"], SimulationCreate(idempotency_key="browser-demo", scenario=scenario))
            except Exception:
                directory.cleanup()
                raise
            key = secrets.token_urlsafe(32)
            self.sessions[key] = {"directory": directory, "service": service, "id": row["id"],
                                  "expires": time.monotonic() + 1200}
            return key, self.snapshot(self.sessions[key])

    @contextmanager
    def session(self, key):
        with self.lock:
            self.cleanup()
            session = self.sessions.get(key)
            if session is None:
                raise HTTPException(404, "展示已到期，請重新建立模擬。")
            yield session

    @staticmethod
    def snapshot(session):
        service = session["service"]
        return {"publication": service.simulation(DEMO_HR, session["id"]),
                "events": service.listing(DEMO_HR, "events", 100, 0)["items"],
                "demo_only": True, "uses_production_database": False}


sessions = DemoSessions()


def same_origin(request):
    origin = request.headers.get("origin")
    if origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (request.url.scheme, request.url.netloc):
        raise HTTPException(403, "請從本站的展示頁操作。")


@router.post("/start")
def start(body: DemoStart, request: Request, response: Response):
    same_origin(request)
    key, result = sessions.start(request.cookies.get(COOKIE), body.scenario)
    response.set_cookie(COOKIE, key, httponly=True, samesite="strict", secure=request.url.scheme == "https",
                        max_age=1200, path="/api/recruitment-demo")
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/state")
def state(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        with sessions.session(request.cookies.get(COOKIE)) as session:
            return sessions.snapshot(session)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return Response(status_code=204, headers={"Cache-Control": "no-store"})


def act(request, response, action, scenario=None):
    same_origin(request)
    response.headers["Cache-Control"] = "no-store"
    with sessions.session(request.cookies.get(COOKIE)) as session:
        service, identifier = session["service"], session["id"]
        if action == "approve":
            service.approve_simulation(DEMO_HR, identifier)
        elif action == "complete":
            service.complete_simulation(DEMO_HR, identifier)
        else:
            service.retry_simulation(DEMO_HR, identifier, SimulationRetry(scenario=scenario))
        return sessions.snapshot(session)


@router.post("/approve")
def approve(request: Request, response: Response):
    return act(request, response, "approve")


@router.post("/complete")
def complete(request: Request, response: Response):
    return act(request, response, "complete")


@router.post("/retry")
def retry(body: SimulationRetry, request: Request, response: Response):
    return act(request, response, "retry", body.scenario)
