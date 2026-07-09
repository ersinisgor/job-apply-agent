"""Schema for the LinkedIn job-posting summary.

This Pydantic model defines the fields that Claude fills via structured output.
Identifiers and field descriptions are in English (to match the rest of this
codebase), but the VALUES Claude produces are written in TURKISH: the whole point
of the summary panel is to let the user read long English job posts quickly in
Turkish. Fields that are not present in the posting are left as "" / empty list.
(Plain `str` with "" instead of `str | None`: nullable fields generate `anyOf`
unions in the JSON schema, which count heavily toward the structured-outputs
complexity limit and caused 400 "Schema is too complex".)

IMPORTANT: keep field descriptions SHORT. The structured-outputs API has a schema
complexity limit and descriptions count toward it — long descriptions cause a
400 "Schema is too complex" error. Detailed extraction rules belong in the
SYSTEM_PROMPT in summary_api.py, not here.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class WorkType(str, Enum):
    """Work arrangement stated in the posting."""

    REMOTE = "remote"
    HYBRID = "hybrid"
    ON_SITE = "on-site"
    UNSPECIFIED = "unspecified"


class JobSummary(BaseModel):
    """At-a-glance job summary. Free-text values in Turkish; deliberately terse."""

    job_title: str = Field(
        default="", description="Position title as stated in the posting."
    )
    company: str = Field(
        default="", description="Hiring company name as stated in the posting."
    )
    role_summary: str = Field(
        description="1-2 short Turkish sentences: what the candidate will build/do."
    )
    work_type: WorkType = Field(
        description="Work arrangement: remote, hybrid, on-site, or unspecified."
    )
    work_type_note: str = Field(
        default="",
        description="Very short Turkish location/timezone condition, e.g. 'İstanbul tercihli'.",
    )
    visa_sponsorship: str = Field(
        default="", description="Very short Turkish visa/sponsorship note; usually empty."
    )
    stack: list[str] = Field(
        default_factory=list,
        description="Required technologies, max 6, most important first.",
    )
    fit_score: int = Field(
        default=0, description="0-100 fit vs the candidate profile; 0 if unknown."
    )
    fit_reason: str = Field(
        default="", description="One very short Turkish clause: why it fits or not."
    )
    min_experience: str = Field(
        default="", description="Minimum experience, very short Turkish, e.g. '3+ yıl'."
    )


class SummarizeRequest(BaseModel):
    """Request body for the /summarize endpoint."""

    text: str = Field(description="The job description text (may be in English).")
    title: str | None = Field(default=None, description="Job title.")
    company: str | None = Field(default=None, description="Company name.")
    location: str | None = Field(default=None, description="Location.")
    job_id: str | None = Field(
        default=None,
        description="LinkedIn job id; used as the server-side summary cache key.",
    )
    refresh: bool = Field(
        default=False,
        description="If true, ignore the cached summary and recompute, overwriting it.",
    )
