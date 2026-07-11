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
import re
from collections import OrderedDict
from functools import lru_cache

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import CV_BASE_FILE, PROJECTS_LIST_FILE, SUMMARY_CACHE_FILE, settings
from .summary_schema import JobSummary, SummarizeRequest

logger = logging.getLogger("applyjobs.summary")

# The candidate's master profile, loaded once. Injected into the prompt so the model
# can score how well each posting fits the user (fit_score / fit_reason). The profile
# is CV + past-project tech: the candidate knows more than the CV lists (e.g. Next.js
# used in a project but absent from the CV still counts as a matched skill). Both files
# are optional; if neither loads, scoring is disabled (model emits fit_score = 0).
def _read_profile_file(path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning("%s file %s not found.", label, path)
        return ""


_CV_TEXT = _read_profile_file(CV_BASE_FILE, "CV")
_PROJECTS_TEXT = _read_profile_file(PROJECTS_LIST_FILE, "Projects")
if not _CV_TEXT and not _PROJECTS_TEXT:
    logger.warning("No CV or projects profile loaded; fit scoring disabled.")

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
    "- 'stack': the REQUIRED technologies only, max 10 GROUPS, most important first "
    "(languages before frameworks/tools). Skip nice-to-haves. A group is an ARRAY, and "
    "it holds MORE THAN ONE option only when the posting itself offers a CHOICE between "
    "them ('or', 'veya', 'ya da', 'or similar', 'en az birinde'). MOST REQUIREMENTS ARE "
    "NOT A CHOICE — default to one-element groups:\n"
    "  * a technology required on its own is a one-element group: [\"Docker\"]\n"
    "  * 'Proficient in one or more back end languages — Python, Go, Java, Node.js, "
    "Rust, or similar' is ONE group: [\"Python\", \"Go\", \"Java\", \"Node.js\", \"Rust\"]\n"
    "  * when the posting couples a language with its framework, keep the pair inside a "
    "single option string, so 'Java/Spring Boot or C#/.NET Core' is ONE group: "
    "[\"Java / Spring Boot\", \"C# / .NET Core\"]\n"
    "  * 'HTML, CSS ve JavaScript konusunda güçlü deneyim' offers no choice — it is "
    "THREE one-element groups: [\"HTML\"], [\"CSS\"], [\"JavaScript\"]\n"
    "  Never merge unrelated required technologies into one group: Docker and "
    "PostgreSQL, both mandatory, are two separate one-element groups.\n"
    "- 'stack_known': always []. The server fills it.\n"
    "- 'work_type': distinguish remote/hybrid/on-site; put any city/country/timezone "
    "condition in 'work_type_note' (a few words, e.g. 'İstanbul tercihli').\n"
    "- 'min_experience': a few words (e.g. '3+ yıl'); 'visa_sponsorship': only if the "
    "posting mentions it.\n"
    "- 'fit_score' (0-100): how well the posting's REQUIRED TECHNOLOGIES fit the "
    "CANDIDATE PROFILE given below — compare required languages/frameworks/tools ONLY. "
    "The candidate KNOWS every technology named ANYWHERE in the profile — both the CV "
    "and the PAST PROJECTS — so a required technology counts as MET if it appears in "
    "either (e.g. Next.js used in a past project counts even if the CV omits it). "
    "Treat obvious spelling variants of a technology as the SAME thing: 'REST API' = "
    "'RESTful API', 'React' = 'React.js', 'Node' = 'Node.js', 'Vector Database' = "
    "pgvector / Vector Search, 'MSSQL' = 'SQL Server' — a variant in the profile means "
    "the requirement is met. "
    "A multi-option 'stack' group is a choice, so it counts as fully MET as soon as the "
    "candidate knows ANY ONE of its options. "
    "IGNORE experience and seniority ENTIRELY: do NOT lower the score for a senior/lead "
    "title or a years-of-experience requirement, and do NOT raise it for a junior one — "
    "the years asked for and the candidate's years must not affect the number at all. "
    "Bands: 70-100 strong (stack overlaps well), 40-69 partial (some overlap), 1-39 weak "
    "(little overlap). If no candidate profile is given, use 0.\n"
    "- 'fit_reason': ONE very short Turkish clause about STACK overlap only; never "
    "mention experience or seniority. Before writing it, walk the 'stack' items ONE BY "
    "ONE and search the whole CANDIDATE PROFILE (CV *and* past projects) for each: an "
    "item is MISSING only if it appears NOWHERE there. Never call an item missing when "
    "the profile names it — the profile's skill lists and project tech lists count.\n"
    "  * fit_score 70+: name the required technologies that match, then any missing one "
    "(e.g. 'Node.js, NestJS ve TypeScript uyumlu; AWS deneyimi yok.').\n"
    "  * fit_score below 70: write a SINGLE clause naming the MISSING technologies and "
    "nothing else — no ';', no second clause, no word about what the candidate does know "
    "or what their stack is built on. Examples of the ONLY acceptable shape: 'Java, "
    "Spring Boot, Kafka, Redis ve Kubernetes deneyimi yok.' / 'Python ve Django/FastAPI "
    "eksik.'\n"
    "  * fit_score 0: empty."
)


def _profile_block() -> str:
    """The candidate profile (CV + past-project tech) appended to the system prompt."""
    parts: list[str] = []
    if _CV_TEXT:
        parts.append("CV / RESUME:\n" + _CV_TEXT)
    if _PROJECTS_TEXT:
        parts.append(
            "PAST PROJECTS the candidate has built — treat EVERY technology named here "
            "as one the candidate KNOWS, even if the CV omits it:\n" + _PROJECTS_TEXT
        )
    if not parts:
        return ""
    return "\n\nCANDIDATE PROFILE (score fit_score against this):\n" + "\n\n".join(parts)


# The panel paints the score green at 70+, yellow at 40-69 and red below that
# (renderFit in extension/content.js). Outside the green band the reason must name the
# GAPS ONLY, and that clause is computed here rather than taken from the model: the
# model extracts 'stack' reliably but is not reliable at diffing it against the profile
# (it called PostgreSQL missing while both the CV and several projects list it).
_FIT_GREEN_MIN = 70

_PROFILE_HAYSTACK = "\n".join(p for p in (_CV_TEXT, _PROJECTS_TEXT) if p).lower()

# Interchangeable spellings of the same technology. A required tech counts as known if
# ANY spelling in its group is in the profile: postings and the model vary the wording
# (REST API vs RESTful API, React vs React.js, Vector Database vs pgvector / Vector
# Search), so a literal match alone kept flagging skills the candidate clearly has.
# Everything is lower-case; entries are compared after version/'.js' normalization.
_SYNONYM_GROUPS: list[set[str]] = [
    {
        "rest",
        "rest api",
        "rest apis",
        "restful",
        "restful api",
        "restful apis",
        "rest endpoints",
        "restful services",
    },
    {"react", "reactjs"},
    {"node", "nodejs"},
    {"next", "nextjs"},
    {"nest", "nestjs"},
    {
        "vector database",
        "vector databases",
        "vector db",
        "vector store",
        "vector search",
        "vector retrieval",
        "pgvector",
    },
    {"sql server", "mssql", "ms sql server", "microsoft sql server"},
    {"postgresql", "postgres", "postgre"},
    {"mongodb", "mongo"},
    # Postings often bolt the spec version onto the bare name; the CV writes the bare
    # form. A blanket trailing-digit strip would wreck 'S3', 'ES6', 'OAuth2', so pair
    # these explicitly instead.
    {"html", "html5"},
    {"css", "css3"},
]


def _normalize_tech(tech: str) -> str:
    """Lower-case, drop a trailing version ('React 18' -> 'react'), and strip a '.js'
    suffix ('React.js' -> 'react') so spelling variants collapse to one form."""
    t = tech.strip().lower()
    t = re.sub(r"\s+v?\d+(?:\.\d+)*$", "", t).strip()  # 'react 18', 'tailwind css v4'
    if t.endswith(".js"):
        t = t[:-3]
    return t


def _tech_variants(tech: str) -> set[str]:
    """Every spelling to look for when deciding whether the profile knows `tech`."""
    variants = {tech.strip().lower(), _normalize_tech(tech)}
    for base in list(variants):
        for group in _SYNONYM_GROUPS:
            if base in group:
                variants |= group
    return {v for v in variants if v}


def _profile_mentions(tech: str) -> bool:
    """True when `tech` (or a known synonym of it) is named anywhere in the profile."""
    if not tech or not tech.strip():
        return False
    for variant in _tech_variants(tech):
        # Bounded on both sides so 'Go' misses 'Django' and 'Java' misses 'JavaScript',
        # while '.NET', 'Node.js' and 'C#' still match themselves.
        pattern = rf"(?<![a-z0-9.#+]){re.escape(variant)}(?![a-z0-9#+])"
        if re.search(pattern, _PROFILE_HAYSTACK):
            return True
    return False


def _option_known(option: str) -> bool:
    """True when the candidate knows a stack option.

    An option may couple a language with its framework ('Java / Spring Boot'); the
    posting wants both, so every part has to be in the profile. (Alternatives are a
    separate level: they are the sibling options of the same stack group.)
    """
    parts = [part.strip() for part in option.split("/") if part.strip()]
    return bool(parts) and all(_profile_mentions(part) for part in parts)


def _stack_known(stack: list[list[str]]) -> list[list[bool]]:
    """Per-option 'is it in the profile?' flags — the panel paints these green/red."""
    return [[_option_known(option) for option in group] for group in stack]


def _missing_stack(stack: list[list[str]]) -> list[str]:
    """The required groups absent from the profile.

    A group lists interchangeable options ('Python' or 'Go' or 'Rust'), so it counts as
    met as soon as the candidate knows ANY one of them.
    """
    missing: list[str] = []
    for group in stack:
        if group and not any(_option_known(option) for option in group):
            missing.append(" veya ".join(option.strip() for option in group))
    return missing


def _gap_only_reason(stack: list[list[str]]) -> str:
    """'Java, Spring Boot ve Kafka deneyimi yok.' — a Turkish list of gaps alone."""
    missing = _missing_stack(stack)
    if not missing:
        return ""
    listed = (
        missing[0]
        if len(missing) == 1
        else ", ".join(missing[:-1]) + " ve " + missing[-1]
    )
    return f"{listed} deneyimi yok."


def _annotate_stack(summary: JobSummary) -> None:
    """Fill `stack_known`, and below the green band rewrite `fit_reason` as gaps only.

    The reason is left to the model when nothing is missing (it then explains the score
    some other way) or when no profile is loaded (fit_score is 0 anyway).
    """
    if not _PROFILE_HAYSTACK:
        return
    summary.stack_known = _stack_known(summary.stack)
    if not 0 < summary.fit_score < _FIT_GREEN_MIN:
        return
    reason = _gap_only_reason(summary.stack)
    if reason:
        summary.fit_reason = reason


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


# Summary cache, keyed by LinkedIn job id. The same posting gets opened repeatedly —
# in several tabs, and via BOTH the /jobs/search-results and the /jobs/view/<id>
# URLs — so keying by id (not by the slightly different extracted text each page
# yields) means every job costs exactly one model call. Bounded and LRU-evicted so a
# long browsing session can't grow it without limit, and mirrored to disk
# (SUMMARY_CACHE_FILE) so it survives an API restart.
_SUMMARY_CACHE: "OrderedDict[str, JobSummary]" = OrderedDict()
_CACHE_MAX = 1000
# Bump whenever the scoring rubric (SYSTEM_PROMPT) or JobSummary schema changes, so a
# stale on-disk cache from the old rules is discarded instead of returning old scores.
_CACHE_VERSION = 9


def _load_cache() -> None:
    """Populate the in-memory cache from disk at startup (best-effort)."""
    try:
        raw = json.loads(SUMMARY_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return  # missing or corrupt file: start empty
    if not isinstance(raw, dict) or raw.get("version") != _CACHE_VERSION:
        return  # old format or older rubric: ignore so stale scores don't linger
    entries = raw.get("entries")
    if not isinstance(entries, dict):
        return
    for job_id, data in entries.items():
        try:
            _SUMMARY_CACHE[str(job_id)] = JobSummary.model_validate(data)
        except Exception:  # noqa: BLE001 - skip entries that no longer fit the schema
            continue
    logger.info("loaded %d cached summaries from %s", len(_SUMMARY_CACHE), SUMMARY_CACHE_FILE)


def _save_cache() -> None:
    """Write the whole cache to disk atomically (temp file + replace)."""
    try:
        SUMMARY_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _CACHE_VERSION,
            "entries": {k: v.model_dump(mode="json") for k, v in _SUMMARY_CACHE.items()},
        }
        tmp = SUMMARY_CACHE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(SUMMARY_CACHE_FILE)
    except OSError:
        logger.warning("could not persist summary cache to %s", SUMMARY_CACHE_FILE)


def _cache_get(job_id: str | None) -> JobSummary | None:
    if not job_id:
        return None
    summary = _SUMMARY_CACHE.get(job_id)
    if summary is not None:
        _SUMMARY_CACHE.move_to_end(job_id)  # mark most-recently used
    return summary


def _cache_put(job_id: str | None, summary: JobSummary) -> None:
    if not job_id:
        return
    _SUMMARY_CACHE[job_id] = summary
    _SUMMARY_CACHE.move_to_end(job_id)
    while len(_SUMMARY_CACHE) > _CACHE_MAX:
        _SUMMARY_CACHE.popitem(last=False)  # evict least-recently used
    _save_cache()


_load_cache()


def _summary_is_blank(summary: JobSummary) -> bool:
    """True when the model returned nothing usable — every field empty, no stack, no
    fit. That means the text it was handed was not really a posting (the extension
    sometimes scrapes the wrong container); such a result must not be cached, or the
    job would keep returning the empty summary on every later open."""
    return not (
        summary.job_title.strip()
        or summary.company.strip()
        or summary.role_summary.strip()
        or summary.work_type_note.strip()
        or summary.min_experience.strip()
        or summary.fit_score
        or any(any(opt.strip() for opt in group) for group in summary.stack)
    )


def summarize(req: SummarizeRequest) -> JobSummary:
    """Turn a job-posting text into a structured (Turkish-valued) summary."""
    if not settings.anthropic_api_key:
        raise MissingCredentialsError(
            "ANTHROPIC_API_KEY is not set. Add it to the project .env file."
        )

    # A refresh (the panel's "Yenile" button) skips the cache READ but still
    # overwrites the stored entry below — recomputing from whatever text the page
    # currently yields.
    if not req.refresh:
        cached = _cache_get(req.job_id)
        if cached is not None:
            logger.info("summary cache hit for job %s", req.job_id)
            return cached

    # The CV + prompt + schema prefix is identical for every posting the user views,
    # so cache it — only the per-job user message varies. (Below Haiku's 4096-token
    # cacheable minimum this silently no-ops, which is harmless.)
    system = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT + _profile_block() + _JSON_INSTRUCTION,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    last_error: Exception | None = None
    for _ in range(2):  # one retry on malformed JSON
        response = _client().messages.create(
            model=settings.summary_model,
            max_tokens=600,  # the summary is deliberately terse; cap the latency too
            temperature=0,  # deterministic: the same posting scores the same every time
            system=system,
            messages=[{"role": "user", "content": _build_user_message(req)}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        try:
            summary = JobSummary.model_validate_json(_extract_json(text))
            _annotate_stack(summary)
            # Don't persist an empty result: the scraped text wasn't a posting, so let
            # a later re-open (once the real description loads) recompute it.
            if _summary_is_blank(summary):
                logger.info("blank summary for job %s; not caching", req.job_id)
            else:
                _cache_put(req.job_id, summary)
            return summary
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
