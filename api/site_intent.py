"""POST /api/site-intent: structure the home page's siting sentence (see engine/site_intent.py)."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from engine import model_budget, site_intent

router = APIRouter(tags=["Site intent"])


class SiteIntentRequest(BaseModel):
    text: str = Field("", max_length=site_intent.MAX_TEXT)
    preference: str = ""

    @field_validator("preference")
    @classmethod
    def known_preference(cls, value: str) -> str:
        if value not in site_intent.PREFERENCES:
            raise ValueError("unknown preference")
        return value


@router.post("/api/site-intent")
def parse_site_intent(body: SiteIntentRequest, request: Request):
    if not model_budget.reserve(request.client.host if request.client else "unknown"):
        raise HTTPException(429, "AI 解析暫時太頻繁，改用關鍵字擷取。")
    return site_intent.parse(body.text, body.preference)
