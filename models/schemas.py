"""Pydantic schemas for structured job-description analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RequirementCategory = Literal[
    "hard_skill",
    "soft_skill",
    "education",
    "experience",
    "certification",
    "seniority",
    "experience_level",
    "operational_competency",
    "technical_competency",
    "learning",
    "working_arrangement",
    "keyword",
]
RequirementPriority = Literal["required", "preferred", "unspecified"]
PriorityBasis = Literal["explicit", "inferred", "unspecified"]


class JobResponsibility(BaseModel):
    name: str = Field(min_length=1)
    priority: RequirementPriority = "unspecified"
    priority_basis: PriorityBasis = "unspecified"
    job_evidence: str = ""
    related_requirement_ids: list[str] = Field(default_factory=list)
    related_requirement_names: list[str] = Field(default_factory=list, exclude=True)


class JobRequirement(BaseModel):
    requirement_id: str = ""
    name: str = Field(min_length=1)
    category: RequirementCategory
    priority: RequirementPriority = "unspecified"
    priority_basis: PriorityBasis = "unspecified"
    literal_phrases: list[str] = Field(default_factory=list)
    related_concepts: list[str] = Field(default_factory=list)
    job_evidence: str = ""
    source_span: str = ""
    source_section: str = ""


class JobProfile(BaseModel):
    job_title: str = "Unspecified role"
    responsibilities: list[JobResponsibility] = Field(default_factory=list)
    requirements: list[JobRequirement] = Field(default_factory=list)
