"""Schema for the LinkedIn job-posting summary.

This Pydantic model defines the fields that Claude fills via structured output.
Identifiers and field descriptions are in English (to match the rest of this
codebase), but the VALUES Claude produces are written in TURKISH: the whole point
of the summary panel is to let the user read long English job posts quickly in
Turkish. Fields that are not present in the posting are left as None / empty list.

Note: Claude structured outputs do not support constraints like minLength/maxLength;
only types + Enum + descriptions are used here. The summary fields are kept discrete
so the future CV match-rate feature can reuse primary_language / tools / frameworks etc.
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
    """Structured summary extracted from a LinkedIn job posting.

    All free-text values MUST be written in Turkish; technology, language, tool,
    framework and library names are kept as-is (e.g. Python, Docker, React).
    """

    role_summary: str = Field(
        description=(
            "The role and what the candidate is expected to do. A short TURKISH "
            "summary of the 'What you'll be working on' / 'About the Role' / "
            "'Responsibilities' sections. 2-4 sentences."
        )
    )
    work_type: WorkType = Field(
        description="Work arrangement: remote, hybrid, on-site, or unspecified."
    )
    work_type_note: str | None = Field(
        default=None,
        description=(
            "Additional condition about the work arrangement, written in TURKISH. "
            "E.g. remote but requires residence in a specific country/city, timezone "
            "requirement, etc. None if not mentioned."
        ),
    )
    visa_sponsorship: str | None = Field(
        default=None,
        description=(
            "Whether the company provides visa / work-permit sponsorship, as stated "
            "in the posting, summarized in TURKISH (e.g. 'Sponsorluk sağlanmıyor', "
            "'Visa sponsorship mevcut'). None if the posting does not mention it."
        ),
    )
    primary_language: str | None = Field(
        default=None,
        description=(
            "The main/required primary programming language (e.g. 'Python', 'Java'). "
            "None if unspecified. Keep the language name as-is."
        ),
    )
    secondary_language: str | None = Field(
        default=None,
        description=(
            "A secondary / 'nice to have' / bonus programming language. None if absent."
        ),
    )
    tools: list[str] = Field(
        default_factory=list,
        description=(
            "Other requested tools/technologies (excluding languages, frameworks and "
            "libraries), e.g. Docker, Kubernetes, AWS, Git, PostgreSQL. Empty list if none."
        ),
    )
    frameworks: list[str] = Field(
        default_factory=list,
        description="Requested frameworks, e.g. Django, FastAPI, React, Spring. Empty list if none.",
    )
    libraries: list[str] = Field(
        default_factory=list,
        description="Requested libraries, e.g. pandas, NumPy, PyTorch. Empty list if none.",
    )
    min_experience: str | None = Field(
        default=None,
        description=(
            "Minimum experience required from the candidate, written in TURKISH "
            "(e.g. '3+ yıl', 'En az 5 yıl backend deneyimi'). None if unspecified."
        ),
    )


class SummarizeRequest(BaseModel):
    """Request body for the /summarize endpoint."""

    text: str = Field(description="The job description text (may be in English).")
    title: str | None = Field(default=None, description="Job title.")
    company: str | None = Field(default=None, description="Company name.")
    location: str | None = Field(default=None, description="Location.")
