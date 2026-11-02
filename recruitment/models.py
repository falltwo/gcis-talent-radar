"""Explicit job-related criteria; extra fields (e.g. age/gender) are rejected."""
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def terms(values):
    cleaned = []
    for value in values:
        normalized = value.strip().casefold()
        if not normalized or len(normalized) > 80:
            raise ValueError("Each term must contain 1–80 characters")
        if normalized not in cleaned:
            cleaned.append(normalized)
    return cleaned


class Requirement(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    district: str = Field(min_length=1, max_length=80)
    shift: str = Field(min_length=1, max_length=80)
    headcount: int = Field(ge=1, le=10000)
    required_skills: list[str] = Field(default_factory=list, max_length=30)
    trainable_skills: list[str] = Field(default_factory=list, max_length=30)
    min_experience_months: int = Field(default=0, ge=0, le=600)
    salary_mode: Literal["RANGE", "NEGOTIABLE"] = "RANGE"
    salary_min: int | None = Field(default=None, ge=1, le=10000000)
    salary_max: int | None = Field(default=None, ge=1, le=10000000)

    _skills = field_validator("required_skills", "trainable_skills")(terms)

    @model_validator(mode="after")
    def salary_range(self):
        if self.salary_mode == "NEGOTIABLE":
            if self.salary_min is not None or self.salary_max is not None:
                raise ValueError("Negotiable salary must not include an invented range")
            return self
        if self.salary_min is None or self.salary_max is None:
            raise ValueError("A salary range requires both minimum and maximum")
        if self.salary_max < self.salary_min:
            raise ValueError("salary_max must be >= salary_min")
        return self


class CandidateEvidence(StrictModel):
    display_name: str = Field(min_length=1, max_length=100)
    # None means unknown; an empty list means the candidate explicitly has none.
    skills: list[str] | None = Field(default=None, max_length=100)
    available_shifts: list[str] | None = Field(default=None, max_length=20)
    districts: list[str] | None = Field(default=None, max_length=40)
    experience_months: int | None = Field(default=None, ge=0, le=600)

    @field_validator("skills", "available_shifts", "districts")
    @classmethod
    def normalized_terms(cls, value):
        return None if value is None else terms(value)


class CandidateImport(CandidateEvidence):
    source: Literal["104", "1111", "direct", "internal"]
    external_ref: str = Field(min_length=1, max_length=160)
    origin: Literal["APPLIED", "SOURCED"]
    rights_confirmed: Literal[True]
    rights_basis: str = Field(min_length=5, max_length=500)
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def retention(cls, value):
        now = datetime.now(timezone.utc)
        if value.tzinfo is None or not now < value <= now + timedelta(days=366):
            raise ValueError("expires_at must include timezone and be within the next 366 days")
        return value.astimezone(timezone.utc)


class Publication(StrictModel):
    platform: Literal["104", "1111", "direct"]
    external_id: str = Field(min_length=1, max_length=160)


class SimulationCreate(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=100)
    scenario: Literal["SUCCESS", "FAILURE"] = "SUCCESS"


class SimulationRetry(StrictModel):
    scenario: Literal["SUCCESS", "FAILURE"] = "SUCCESS"


class InvitationDraft(StrictModel):
    message: str = Field(min_length=1, max_length=2000)


class InvitationApproval(StrictModel):
    reviewed_unknowns: bool = False


class RequestApproval(StrictModel):
    expected_revision: int = Field(ge=1)


class DraftInput(StrictModel):
    needs: str = Field(min_length=5, max_length=4000)


class ExtractedRequirement(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    district: str | None = Field(default=None, min_length=1, max_length=80)
    shift: str | None = Field(default=None, min_length=1, max_length=80)
    headcount: int | None = Field(default=None, ge=1, le=10000)
    required_skills: list[str] = Field(default_factory=list, max_length=30)
    trainable_skills: list[str] = Field(default_factory=list, max_length=30)
    min_experience_months: int | None = Field(default=None, ge=0, le=600)
    salary_min: int | None = Field(default=None, ge=1, le=10000000)
    salary_max: int | None = Field(default=None, ge=1, le=10000000)

    _skills = field_validator("required_skills", "trainable_skills")(terms)


class Delivery(StrictModel):
    outcome: Literal["SENT", "FAILED"]
    # Stable external message ID (or a manual dispatch receipt), not a new ID per retry.
    reference: str = Field(min_length=1, max_length=160)


class Reply(StrictModel):
    outcome: Literal["INTERESTED", "DECLINED", "NO_RESPONSE"]


class StageChange(StrictModel):
    stage: Literal["INTERVIEW", "OFFERED", "HIRED", "REJECTED", "WITHDRAWN"]
