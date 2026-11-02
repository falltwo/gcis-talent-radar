"""HR-approved handoff for visible scripted filling of the isolated mock portal."""
import os
import time
from collections import deque
from threading import Lock
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field

import api.mock104 as portal
from api.mock104 import JobForm
from recruitment.drafting import prepare_requirement
from recruitment.models import ExtractedRequirement, StrictModel
from recruitment.workflow import uid


router = APIRouter(prefix="/api/mock104/agent", tags=["Recruitment Agent demo"])
budget_lock = Lock()
model_calls = deque()


class AgentPrepare(StrictModel):
    company_name: str = Field(min_length=1, max_length=120)
    company_intro: str = Field(default="", max_length=1000)
    district: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=120)
    needs: str = Field(min_length=5, max_length=2500)
    mode: Literal["MODEL", "SAMPLE"] = "MODEL"


class JobExtraction(ExtractedRequirement):
    description: str | None = Field(default=None, max_length=5000)
    work_hours: str | None = Field(default=None, max_length=120)
    schedule_system: Literal["固定班制", "排班制", "輪班制"] | None = None
    employment_type: Literal["全職", "兼職"] | None = None


class ApprovedHandoff(StrictModel):
    job: JobForm
    hr_confirmed: Literal[True]
    confirm_before_publish: bool = True
    scenario: Literal["SUCCESS", "FAILURE"] = "SUCCESS"
    typing_speed: Literal["NORMAL", "FAST"] = "NORMAL"


class RunId(StrictModel):
    run_id: str


class FilledHandoff(RunId):
    job_id: str


def run_for(session, identifier):
    run = session.get("agent_run")
    if not run or run["run_id"] != identifier:
        raise HTTPException(409, "這次操作已被取代，請回到 HR 工作台重新確認。")
    return run


@router.post("/prepare")
def prepare(body: AgentPrepare, request: Request, response: Response):
    portal.protect(request, response)
    with portal.get_session(request) as session:
        if body.mode == "SAMPLE":
            if body.role.strip() not in {"CNC 操作員", "CNC操作員"}:
                raise HTTPException(422, "固定示範僅適用 CNC 操作員；自訂需求請使用 AI 整理。")
            fields = {"title": "CNC 操作員", "district": body.district, "shift": "日班", "headcount": 3,
                      "required_skills": ["cnc"], "trainable_skills": ["機械製圖"], "min_experience_months": 12,
                      "salary_min": 35000, "salary_max": 45000, "work_hours": "08:00–17:00",
                      "schedule_system": "固定班制", "employment_type": "全職",
                      "description": "1. 操作 CNC 加工設備，依圖面完成工件加工。\n2. 檢查加工品質並填寫生產紀錄。\n3. 協助設備保養與現場整理。\n\n此為固定示範資料，非真實職缺。"}
            source = "FIXED_SAMPLE"
        else:
            if os.environ.get("RECRUITMENT_AGENT_DEMO_AI_ENABLED") != "1":
                raise HTTPException(503, "本機 AI 展示尚未啟用；可先使用固定範例展示完整填表流程。")
            if session.get("prepare_calls", 0) >= 3:
                raise HTTPException(429, "本次展示的 AI 整理已達3次上限。")
            with budget_lock:
                while model_calls and model_calls[0] < time.monotonic() - 60:
                    model_calls.popleft()
                if len(model_calls) >= 10:
                    raise HTTPException(429, "AI 整理暫時繁忙，請稍後再試。")
                model_calls.append(time.monotonic())
            session["prepare_calls"] = session.get("prepare_calls", 0) + 1
            context = (f"職位：{body.role}\n工作地點：{body.district}\nHR提供的招募需求：{body.needs}\n"
                       "請另整理工作內容description、上班起迄時間work_hours、班制schedule_system、工作性質employment_type。"
                       "沒有提及的欄位保留null，不得自行估薪、編造公司資訊或補充招募限制。")
            fields = prepare_requirement(context, JobExtraction)["fields"]
            source = "MODEL"
        fields.update(company_name=body.company_name, company_intro=body.company_intro)
        return {"job": fields, "source": source, "requires_hr_review": True,
                "missing_fields": [key for key, value in fields.items() if value is None],
                "notice": "公司資訊由HR提供。整理結果需HR確認；尚未填表或刊登。"}


@router.post("/approve")
def approve(body: ApprovedHandoff, request: Request, response: Response):
    portal.protect(request, response)
    if len(body.job.description.strip()) < 10 or not body.job.work_hours.strip():
        raise HTTPException(422, "請確認工作內容及上班起迄時間後再交給 Agent。")
    with portal.get_session(request) as session:
        previous = session.get("agent_run")
        if previous and previous["phase"] in {"RUNNING", "AWAITING_CONFIRMATION", "READY_TO_PUBLISH", "SUBMITTED"}:
            raise HTTPException(409, "已有待完成的填表流程，請先完成或停止該流程。")
        run = {"run_id": uid(), "job": body.job.model_dump(), "phase": "READY", "job_id": None,
               "confirm_before_publish": body.confirm_before_publish, "scenario": body.scenario,
               "typing_speed": body.typing_speed,
               "mode": "SIMULATION", "sent_to_platform": False}
        session["agent_run"] = run
        return run


@router.get("/run")
def current_run(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    with portal.get_session(request) as session:
        if not session.get("agent_run"):
            raise HTTPException(404, "尚無已核准的 Agent 填表工作。")
        return session["agent_run"]


@router.post("/claim")
def claim(body: RunId, request: Request, response: Response):
    portal.protect(request, response)
    with portal.get_session(request) as session:
        run = run_for(session, body.run_id)
        if run["phase"] != "READY":
            raise HTTPException(409, "這個填表工作已啟動，請勿重複執行。")
        run["phase"] = "RUNNING"
        return run


@router.post("/filled")
def filled(body: FilledHandoff, request: Request, response: Response):
    portal.protect(request, response)
    with portal.get_session(request) as session:
        run = run_for(session, body.run_id)
        if run["phase"] != "RUNNING":
            raise HTTPException(409, "填表工作目前不接受完成回報。")
        actual = next((job for job in portal.snapshot(session)["jobs"] if job["id"] == body.job_id), None)
        if not actual or actual["status"] != "DRAFT" or actual["data"] != run["job"]:
            raise HTTPException(409, "已填入的內容與HR核准版本不同，已停止自動刊登。")
        run.update(job_id=body.job_id, phase="AWAITING_CONFIRMATION" if run["confirm_before_publish"] else "READY_TO_PUBLISH")
        return run


@router.post("/cancel")
def cancel(body: RunId, request: Request, response: Response):
    portal.protect(request, response)
    with portal.get_session(request) as session:
        run = run_for(session, body.run_id)
        if run["phase"] in {"PUBLISHED", "CANCELLED"}:
            return run
        run["phase"] = "CANCELLED"
        return run
