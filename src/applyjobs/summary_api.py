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

import logging
from functools import lru_cache

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .summary_schema import JobSummary, SummarizeRequest

logger = logging.getLogger("applyjobs.summary")

# The system prompt is in English, but it instructs the model to write the field
# VALUES in Turkish so the panel reads as a quick Turkish summary.
SYSTEM_PROMPT = (
    "You are a senior technical recruiting assistant. Analyze the given job posting "
    "(usually in English) and extract the requested fields. Rules:\n"
    "- Write all free-text field VALUES in TURKISH. Keep technology/language/tool "
    "names as-is (e.g. Python, Docker, React).\n"
    "- Only use information EXPLICITLY stated in the posting; if something is missing, "
    "leave the field empty (null or empty list). Never invent or guess.\n"
    "- 'primary_language' is the required/primary programming language; "
    "'secondary_language' is a 'nice to have' or bonus language.\n"
    "- Keep 'role_summary' short and clear (2-4 sentences), describing what the "
    "candidate is expected to do.\n"
    "- For work_type, carefully distinguish remote/hybrid/on-site; if it is remote but "
    "has a country/city/timezone requirement, put that in 'work_type_note'.\n"
    "- If the posting mentions visa/sponsorship, capture it in 'visa_sponsorship'."
)


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


def summarize(req: SummarizeRequest) -> JobSummary:
    """Turn a job-posting text into a structured (Turkish-valued) summary."""
    if not settings.anthropic_api_key:
        raise MissingCredentialsError(
            "ANTHROPIC_API_KEY is not set. Add it to the project .env file."
        )

    response = _client().messages.parse(
        model=settings.summary_model,
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_message(req)}],
        output_format=JobSummary,
    )
    return response.parsed_output


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
