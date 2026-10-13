"""Schemas reserved for candidate-to-job matching after profile confirmation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MatchStatus = Literal["matched", "partial", "missing", "needs_review"]


class CVMatchRecord(BaseModel):
    """A separate match result; this is not part of job-description extraction."""

    requirement_id: str = Field(min_length=1)
    candidate_evidence: str = ""
    match_status: MatchStatus = "needs_review"
    matched_phrases: list[str] = Field(default_factory=list)
    missing_phrases: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

