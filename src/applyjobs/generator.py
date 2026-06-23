"""CV generation via the Anthropic API.

Builds the ATS-optimization prompt from config assets and returns both the full
model response (Turkish analysis + tables) and the clean optimized CV markdown.
"""
from __future__ import annotations

import logging
import re

import anthropic

from .config import (
    ATS_PROMPT_FILE,
    ATS_REVIEW_PROMPT_FILE,
    CV_BASE_FILE,
    PROJECTS_LIST_FILE,
    settings,
)

logger = logging.getLogger(__name__)

_CV_MARKER_RE = re.compile(r"<CV_START>\s*(.*?)\s*<CV_END>", re.DOTALL)
_MATCH_RATE_RE = re.compile(r"<MATCH_RATE>\s*(\d+(?:\.\d+)?)\s*</MATCH_RATE>")

MAX_TOKENS = 8000

# Reasoning effort -> extended-thinking token budget. "none" disables thinking.
_EFFORT_BUDGET = {"low": 4096, "medium": 8192, "high": 16384}


BASE_RELOCATION_SENTENCE = "Open to relocation and on-site or hybrid opportunities."


def _relocation_instruction(work_mode: str, city: str) -> str:
    """Build the SUMMARY closing-sentence rule from the row's work mode and city."""
    wm = work_mode.strip().lower()
    city = city.strip()
    if wm == "remote":
        return (
            "The job is REMOTE. In the SUMMARY, REMOVE the final sentence "
            f'"{BASE_RELOCATION_SENTENCE}" completely and do not replace it with anything.'
        )
    if wm in ("on-site", "onsite", "on site", "hybrit", "hybrid"):
        new_sentence = f"Open to relocation({city}) and on-site or hybrid opportunities."
        return (
            f"The job is {work_mode.strip()} (on-site/hybrid). The SUMMARY's final sentence "
            f'MUST read EXACTLY: "{new_sentence}"'
        )
    return (
        "Keep the SUMMARY's final sentence exactly as in the original CV: "
        f'"{BASE_RELOCATION_SENTENCE}"'
    )


def _build_prompt(job_description: str, work_mode: str, city: str) -> str:
    template = ATS_PROMPT_FILE.read_text(encoding="utf-8")
    cv_base = CV_BASE_FILE.read_text(encoding="utf-8")
    projects = PROJECTS_LIST_FILE.read_text(encoding="utf-8")
    return (
        template.replace("{{PROJECTS_LIST}}", projects)
        .replace("{{CV_BASE}}", cv_base)
        .replace("{{SUMMARY_RELOCATION_RULE}}", _relocation_instruction(work_mode, city))
        .replace("{{JOB_DESCRIPTION}}", job_description.strip())
    )


def _extract_cv(full_response: str) -> str:
    match = _CV_MARKER_RE.search(full_response)
    if match:
        cv = match.group(1).strip()
        # Strip an accidental wrapping code fence if the model added one.
        if cv.startswith("```"):
            cv = re.sub(r"^```[a-zA-Z]*\n", "", cv)
            cv = re.sub(r"\n```$", "", cv).strip()
        return cv
    raise ValueError(
        "Could not find <CV_START>...<CV_END> markers in the model response."
    )


def _extract_match_rate(full_response: str) -> float | None:
    match = _MATCH_RATE_RE.search(full_response)
    if not match:
        logger.warning("No <MATCH_RATE> marker found in the model response.")
        return None
    return float(match.group(1))


def _call_model(prompt: str) -> str:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    kwargs = {
        "model": settings.claude_model,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    budget = _EFFORT_BUDGET.get(settings.claude_effort)
    if budget:
        # Extended thinking: max_tokens must leave room for output beyond the budget.
        kwargs["max_tokens"] = budget + MAX_TOKENS
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
    # Stream so large (high-effort) requests aren't blocked by the 10-min non-stream limit.
    with client.messages.stream(**kwargs) as stream:
        message = stream.get_final_message()
    # Only collect answer text; skip "thinking" blocks.
    return "".join(
        block.text for block in message.content if getattr(block, "type", "") == "text"
    )


def generate(
    job_description: str, work_mode: str = "", city: str = ""
) -> tuple[str, str, float | None]:
    """Return (full_response, optimized_cv_markdown, match_rate)."""
    prompt = _build_prompt(job_description, work_mode, city)
    logger.info("Requesting CV from %s ...", settings.claude_model)
    full = _call_model(prompt)
    return full, _extract_cv(full), _extract_match_rate(full)


def review(
    job_description: str, cv_draft: str, work_mode: str = "", city: str = ""
) -> tuple[str, str, float | None]:
    """Second expert pass: verify the draft CV against the job and FIX problems.

    Returns (full_review_response, corrected_cv_markdown, final_match_rate).
    """
    template = ATS_REVIEW_PROMPT_FILE.read_text(encoding="utf-8")
    prompt = (
        template.replace("{{PROJECTS_LIST}}", PROJECTS_LIST_FILE.read_text(encoding="utf-8"))
        .replace("{{CV_BASE}}", CV_BASE_FILE.read_text(encoding="utf-8"))
        .replace("{{SUMMARY_RELOCATION_RULE}}", _relocation_instruction(work_mode, city))
        .replace("{{JOB_DESCRIPTION}}", job_description.strip())
        .replace("{{CV_DRAFT}}", cv_draft.strip())
    )
    logger.info("Reviewing CV (expert QA pass) with %s ...", settings.claude_model)
    full = _call_model(prompt)
    return full, _extract_cv(full), _extract_match_rate(full)
