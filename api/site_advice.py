"""POST /api/site-advice: plain-language hiring advice for three districts (see engine/site_advice.py)."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from config import TAICHUNG_DISTRICTS
from engine import model_budget, site_advice

District = Literal[tuple(TAICHUNG_DISTRICTS)]

router = APIRouter(tags=["Site advice"])


class Fact(BaseModel):
    id: str = Field(pattern=r"^f\d{1,3}$")
    label: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=40)


class SiteAdviceRequest(BaseModel):
    districts: list[District] = Field(min_length=1, max_length=3)
    industry: str | None = Field(None, max_length=20)
    role: str | None = Field(None, max_length=20)
    facts: list[Fact] = Field(min_length=1, max_length=60)


@router.post("/api/site-advice")
def site_advice_endpoint(body: SiteAdviceRequest, request: Request):
    if not model_budget.reserve(request.client.host if request.client else "unknown"):
        raise HTTPException(429, "AI 建議暫時太頻繁，畫面保留系統版建議。")
    return site_advice.advise(body.model_dump())
