"""HR-approved handoff for visible scripted filling of the isolated mock portal."""
import os
import time
from collections import deque
from threading import Lock
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import Field, model_validator

import api.mock104 as portal
from api.mock104 import JobForm
from recruitment.drafting import prepare_requirement
from recruitment.models import ExtractedRequirement, StrictModel
from recruitment.workflow import uid
from recruitment.computer_use import launch, local_origin
from recruitment.job_research import draft_job, strategy_for
from recruitment.job_history import JobHistory


router = APIRouter(prefix="/api/mock104/agent", tags=["Recruitment Agent demo"])
budget_lock = Lock()
model_calls = deque()


class AgentPrepare(StrictModel):
    company_name: str = Field(default="", max_length=120)
    company_intro: str = Field(default="", max_length=1000)
    district: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=120)
    needs: str = Field(min_length=5, max_length=2500)
    mode: Literal["AUTO", "MODEL", "SAMPLE"] = "AUTO"


class JobExtraction(ExtractedRequirement):
    description: str | None = Field(default=None, max_length=5000)
    work_hours: str | None = Field(default=None, max_length=120)
    schedule_system: Literal["固定班制", "排班制", "輪班制"] | None = None
    employment_type: Literal["全職", "兼職"] | None = None


class ApprovedHandoff(StrictModel):
    job: JobForm
    hr_confirmed: bool
    auto_fill: bool = False
    confirm_before_publish: bool = True
    fill_only: bool = False
    scenario: Literal["SUCCESS", "FAILURE"] = "SUCCESS"
    typing_speed: Literal["NORMAL", "FAST"] = "NORMAL"

    @model_validator(mode='after')
    def proposal_cannot_publish(self):
        if not self.hr_confirmed and not (self.auto_fill and self.fill_only and self.confirm_before_publish):
            raise ValueError('未確認的建議只允許填表，必須保留填完後的人工確認。')
        return self


class RunId(StrictModel):
    run_id: str


class FilledHandoff(RunId):
    job_id: str


def run_for(session, identifier):
    run = session.get("agent_run")
    if not run or run["run_id"] != identifier:
        raise HTTPException(409, "這次操作已被取代，請回到 HR 工作台重新確認。")
    return run


def reserve_model_call(session):
    if os.environ.get("RECRUITMENT_AGENT_DEMO_AI_ENABLED") != "1":
        raise HTTPException(503, "本機模型／網路搜尋尚未啟用；常見職位仍可使用職業範本。")
    if session.get("prepare_calls", 0) >= 3:
        raise HTTPException(429, "本次展示的模型整理已達3次上限。")
    with budget_lock:
        while model_calls and model_calls[0] < time.monotonic() - 60:
            model_calls.popleft()
        if len(model_calls) >= 10:
            raise HTTPException(429, "整理服務暫時繁忙，請稍後再試。")
        model_calls.append(time.monotonic())
    session["prepare_calls"] = session.get("prepare_calls", 0) + 1


@router.get('/strategy')
def preparation_strategy(response: Response, role: str = Query(min_length=1, max_length=120)):
    response.headers['Cache-Control']='no-store'
    return strategy_for(role)


@router.get('/history')
def history_templates(response: Response):
    response.headers['Cache-Control']='no-store'
    try:
        items=JobHistory().items()
    except RuntimeError as exc:
        raise HTTPException(503,str(exc)) from None
    return {'items':[{key:item[key] for key in ('role','saved_at','expires_at','sources')} for item in items],
            'retention_days':30,'max_items':200}


@router.post("/prepare")
def prepare(body: AgentPrepare, request: Request, response: Response):
    portal.protect(request, response)
    with portal.get_session(request) as session:
        if body.mode == "MODEL" or (body.mode == "AUTO" and strategy_for(body.role)['source']=='LIVE_WEB_RESEARCH'):
            reserve_model_call(session)
    # Long network/model work must not hold the browser/session registry lock.
    if body.mode == "AUTO":
        return draft_job(body)
    if body.mode == "SAMPLE":
        if body.role.strip() not in {"CNC 操作員", "CNC操作員"}:
            raise HTTPException(422, "固定示範僅適用CNC操作員；其他職位請使用範本或網路整理。")
        fields = {"title":"CNC 操作員","district":body.district,"shift":"日班","headcount":3,
                  "required_skills":["cnc"],"trainable_skills":["機械製圖"],"min_experience_months":12,
                  "salary_min":35000,"salary_max":45000,"work_hours":"08:00–17:00",
                  "schedule_system":"固定班制","employment_type":"全職",
                  "description":"操作CNC設備、檢查加工品質及協助保養。此為固定示範資料，非真實職缺。"}
        source = "FIXED_SAMPLE"
    else:
        context = (f"職位：{body.role}\n工作地點：{body.district}\nHR招募需求：{body.needs}\n"
                   "整理description、work_hours、schedule_system及employment_type；未提及欄位留null。")
        fields = prepare_requirement(context, JobExtraction)["fields"]
        source = "MODEL"
    fields.update(company_name=body.company_name,company_intro=body.company_intro)
    return {"job":fields,"source":source,"requires_hr_review":True,
            "missing_fields":[key for key,value in fields.items() if value is None],
            "notice":"整理結果需HR確認，尚未刊登。"}


@router.post("/approve")
def approve(body: ApprovedHandoff, request: Request, response: Response):
    from recruitment.action_router import model_name
    portal.protect(request, response)
    if len(body.job.description.strip()) < 10 or not body.job.work_hours.strip():
        raise HTTPException(422, "請確認工作內容及上班起迄時間後再交給 Agent。")
    with portal.get_session(request) as session:
        previous = session.get("agent_run")
        if previous and previous["phase"] in {"RUNNING", "COMPUTER_RUNNING", "COMPUTER_PUBLISHING", "AWAITING_CONFIRMATION", "READY_TO_PUBLISH", "SUBMITTED"}:
            raise HTTPException(409, "已有待完成的填表流程，請先完成或停止該流程。")
        run = {"run_id": uid(), "job": body.job.model_dump(), "phase": "READY", "job_id": None,
               "model_roles":{"thinking":os.getenv('RECRUITMENT_THINKING_MODEL',os.getenv('OPENROUTER_MODEL','openai/gpt-6-luna')),
                              "operation":model_name()},
               "confirm_before_publish": body.confirm_before_publish, "fill_only":body.fill_only,"auto_fill":body.auto_fill,"conditions_confirmed":body.hr_confirmed, "scenario": body.scenario,
               "typing_speed": body.typing_speed,
               "mode": "SIMULATION", "sent_to_platform": False,"driver":"COMPUTER_USE","steps":[],"screenshot":None}
        session["agent_run"] = run
        return run


@router.get("/run")
def current_run(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    with portal.get_session(request) as session:
        if not session.get("agent_run"):
            raise HTTPException(404, "尚無已核准的 Agent 填表工作。")
        from recruitment.computer_use import active,active_lock
        with active_lock:browser_active=request.cookies.get(portal.COOKIE) in active
        return {**session["agent_run"],"browser_active":browser_active}


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


@router.post('/browser/start')
def start_browser(body: RunId, request: Request, response: Response):
    portal.protect(request,response)
    if os.environ.get('RECRUITMENT_AGENT_DEMO_AI_ENABLED')!='1' or not os.environ.get('OPENROUTER_API_KEY','').strip():
        raise HTTPException(503,'請先啟用本機模型與Computer Use，或手動使用一般求才網頁。')
    if request.client.host not in {'127.0.0.1','::1','testclient'}:
        raise HTTPException(403,'獨立瀏覽器只供本機展示。')
    origin=local_origin(str(request.base_url).rstrip('/'))
    with portal.get_session(request) as session:
        run=run_for(session,body.run_id)
        if run['phase']!='READY': raise HTTPException(409,'工作已開始或已結束。')
        launch(portal.sessions,request.cookies.get(portal.COOKIE),origin,run['run_id'])
        return {'started':True,'driver':'COMPUTER_USE','notice':'同頁顯示Chrome實際截圖與滑鼠鍵盤操作，不另開視窗。'}


@router.post('/browser/resume')
def resume_browser(body: RunId, request: Request, response: Response):
    portal.protect(request,response)
    with portal.get_session(request) as session:
        run=run_for(session,body.run_id)
        if run['phase']!='AWAITING_CONFIRMATION': raise HTTPException(409,'目前沒有等待HR確認的瀏覽器工作。')
        run['phase']='COMPUTER_PUBLISHING'
        run['message']='HR已確認，繼續透過一般網站模擬刊登。'
        return run
