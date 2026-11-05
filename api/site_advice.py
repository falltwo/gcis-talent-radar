"""POST /api/site-advice: plain-language hiring advice for three districts (see engine/site_advice.py)."""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from engine import site_advice

router = APIRouter(tags=["Site advice"])


class Fact(BaseModel):
    id: str = Field(pattern=r"^f\d{1,3}$")
    label: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=40)


class SiteAdviceRequest(BaseModel):
    districts: list[str] = Field(min_length=1, max_length=3)
    industry: str | None = Field(None, max_length=20)
    role: str | None = Field(None, max_length=20)
    facts: list[Fact] = Field(min_length=1, max_length=60)


@router.post("/api/site-advice")
def site_advice_endpoint(body: SiteAdviceRequest):
    return site_advice.advise(body.model_dump())
