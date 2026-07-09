"""FastAPI backend for the LinkedIn Job Summary browser extension.

Reads a job-posting text and returns a structured summary via Claude. Field
identifiers are English; the field VALUES are produced in Turkish (see
summary_schema). Uses the Haiku model (settings.summary_model) for fast, low-cost
summaries, independent of the CV-generation model (settings.claude_model).

Run:
    python scripts/run_summary_api.py
    # or: uvicorn src.applyjobs.summary_api:app --port 8000

Endpoints:
    GET  /health      -> {"status": "ok", "model": ...}
    POST /summarize   -> JobSummary
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import CV_BASE_FILE, settings
from .summary_schema import JobSummary, SummarizeRequest

logger = logging.getLogger("applyjobs.summary")

# The candidate's master profile, loaded once. Injected into the prompt so the model
# can score how well each posting fits the user (fit_score / fit_reason). Missing file
# is tolerated: scoring is then disabled (the model is told to emit fit_score = 0).
try:
    _CV_TEXT = CV_BASE_FILE.read_text(encoding="utf-8").strip()
except OSError:
    _CV_TEXT = ""
    logger.warning("CV file %s not found; fit scoring disabled.", CV_BASE_FILE)

# The system prompt is in English, but it instructs the model to write the field
# VALUES in Turkish so the panel reads as a quick Turkish summary.
SYSTEM_PROMPT = (
    "You are a technical recruiting assistant. The user wants an AT-A-GLANCE summary "
    "to decide in seconds whether a job posting fits them. Be TERSE. Rules:\n"
    "- Write free-text VALUES in TURKISH; keep technology names as-is (Python, Docker).\n"
    "- Only use information EXPLICITLY stated in the posting; if missing, leave the "
    "field empty (\"\" or []). Never invent or guess.\n"
    "- The text may include page clutter (navigation, other job titles). Focus on the "
    "posting itself; take 'job_title' and 'company' from the posting.\n"
    "- 'role_summary': one or two short sentences — what the candidate will build/do "
    "and the key context that matters. No company history, no boilerplate.\n"
    "- 'stack': the REQUIRED technologies only, max 6 items, most important first — "
    "primary programming language(s) first (join alternatives like '.NET / Node.js / "
    "Scala' into one item), then key frameworks/tools. Skip nice-to-haves.\n"
    "- 'work_type': distinguish remote/hybrid/on-site; put any city/country/timezone "
    "condition in 'work_type_note' (a few words, e.g. 'İstanbul tercihli').\n"
    "- 'min_experience': a few words (e.g. '3+ yıl'); 'visa_sponsorship': only if the "
    "posting mentions it.\n"
    "- 'fit_score' (0-100): how well the posting fits the CANDIDATE PROFILE given below "
    "— compare required languages/frameworks/tools AND seniority. Bands: 70-100 strong "
    "(stack overlaps well and level fits), 40-69 partial (some overlap or a level gap), "
    "1-39 weak. The candidate is junior / early mid-level, so senior/lead postings score "
    "lower even when the stack overlaps. If no candidate profile is given, use 0.\n"
    "- 'fit_reason': ONE very short Turkish clause explaining the score (e.g. "
    "'Node/TS güçlü ama .NET ağırlıklı'). Empty when fit_score is 0."
)


def _cv_block() -> str:
    """The candidate profile appended to the system prompt, or '' when unavailable."""
    if not _CV_TEXT:
        return ""
    return "\n\nCANDIDATE PROFILE (score fit_score against this):\n" + _CV_TEXT


class MissingCredentialsError(RuntimeError):
    """Raised when no Anthropic API key is configured."""


app = FastAPI(title="LinkedIn Job Summary", version="0.1.0")

# Extension requests go through the background service worker (works without CORS),
# but CORS is enabled for local development convenience. Restrict origins in prod.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    """Create the Anthropic client once (key from settings)."""
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _build_user_message(req: SummarizeRequest) -> str:
    parts: list[str] = []
    if req.title:
        parts.append(f"Job title: {req.title}")
    if req.company:
        parts.append(f"Company: {req.company}")
    if req.location:
        parts.append(f"Location: {req.location}")
    parts.append("\nJob posting:\n" + req.text.strip())
    parts.append(
        "\nAnalyze the posting above and fill the requested fields "
        "(free-text values in Turkish)."
    )
    return "\n".join(parts)


# NOTE: plain-JSON prompting instead of structured outputs (messages.parse).
# The 14-field JobSummary schema exceeds the structured-outputs grammar-compile
# budget on the summary model: every request burned the full ~180s compile
# timeout and then 400'd with "Schema is too complex" / "Grammar compilation
# timed out". Prompting for JSON and validating with the same Pydantic model
# keeps responses in the seconds range.
_SCHEMA_JSON = json.dumps(
    JobSummary.model_json_schema(), ensure_ascii=False, separators=(",", ":")
)

_JSON_INSTRUCTION = (
    "\nRespond with ONLY one JSON object that matches this JSON schema — no "
    "markdown, no code fences, no commentary:\n" + _SCHEMA_JSON
)


def _extract_json(text: str) -> str:
    """Best-effort: cut the first {...} span out of the model's reply."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("Model reply contains no JSON object.")
    return text[start : end + 1]


def summarize(req: SummarizeRequest) -> JobSummary:
    """Turn a job-posting text into a structured (Turkish-valued) summary."""
    if not settings.anthropic_api_key:
        raise MissingCredentialsError(
            "ANTHROPIC_API_KEY is not set. Add it to the project .env file."
        )

    # The CV + prompt + schema prefix is identical for every posting the user views,
    # so cache it — only the per-job user message varies. (Below Haiku's 4096-token
    # cacheable minimum this silently no-ops, which is harmless.)
    system = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT + _cv_block() + _JSON_INSTRUCTION,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    last_error: Exception | None = None
    for _ in range(2):  # one retry on malformed JSON
        response = _client().messages.create(
            model=settings.summary_model,
            max_tokens=600,  # the summary is deliberately terse; cap the latency too
            system=system,
            messages=[{"role": "user", "content": _build_user_message(req)}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        try:
            return JobSummary.model_validate_json(_extract_json(text))
        except Exception as exc:  # noqa: BLE001 - malformed JSON: retry once
            last_error = exc
    raise ValueError(f"Model did not return valid JSON: {last_error}")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": settings.summary_model}


@app.post("/summarize", response_model=JobSummary)
def summarize_endpoint(req: SummarizeRequest) -> JobSummary:
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=422, detail="Job text ('text') must not be empty.")

    try:
        return summarize(req)
    except MissingCredentialsError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except anthropic.RateLimitError:
        raise HTTPException(
            status_code=429,
            detail="Claude API rate limit hit. Please try again shortly.",
        )
    except anthropic.AuthenticationError:
        raise HTTPException(
            status_code=500,
            detail="Claude API authentication failed (check ANTHROPIC_API_KEY).",
        )
    except anthropic.APIConnectionError:
        raise HTTPException(
            status_code=502,
            detail="Could not reach the Claude API. Check your internet connection.",
        )
    except anthropic.APIStatusError as exc:
        logger.exception("Claude API error")
        raise HTTPException(status_code=502, detail=f"Claude API error ({exc.status_code}).")
    except Exception:  # noqa: BLE001 - wrap unexpected errors as 500
        logger.exception("Unexpected error during summarization")
        raise HTTPException(status_code=500, detail="Unexpected error during summarization.")
