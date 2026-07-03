"""Orchestration: detect new rows, generate CVs, save files, write back CV No."""
from __future__ import annotations

import json
import logging
import re

from . import docx_builder, drive_docs, generator, huntr
from .reporting import record_duplicate, record_failure
from .config import (
    HUNTR_SEEN_FILE,
    NO_CV_MARKER,
    SKIP_BASVURU_VALUES,
    STATE_DIR,
    settings,
)
from .scraper import Scraper
from .sheets import Row, SheetsClient

logger = logging.getLogger(__name__)

# Highest CV number ever assigned. Acts as a floor so a transient bad read of the
# sheet can never reset numbering to a low value and clobber existing CVs.
LAST_CV_FILE = STATE_DIR / "last_cv_no"


def load_last_cv_no() -> int:
    try:
        return int(LAST_CV_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def save_last_cv_no(value: int) -> None:
    LAST_CV_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_CV_FILE.write_text(str(value), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Huntr import
# --------------------------------------------------------------------------- #

# Consecutive scans where the board returned no jobs. After a couple in a row we alert
# once (likely an expired Huntr session), but a single transient empty read is ignored.
_huntr_empty_streak = 0


def _norm_url(url: str) -> str:
    return url.split("?", 1)[0].strip()


# LinkedIn job id inside the link, e.g. .../jobs/view/4427414076/... -> 4427414076.
# This is exactly what column M (İlan Numarası) extracts from K via its formula.
_LINKEDIN_ID_RE = re.compile(r"/jobs/view/(\d+)")


def _job_key(link: str) -> str:
    """Stable per-posting identity for de-duplication.

    For LinkedIn links it is the job id (the value column M computes from K) — the
    most reliable signal, since the same posting can have many tracking URLs. For
    non-LinkedIn links it falls back to the query-stripped URL. Empty link -> "".

    We derive the id from K rather than reading column M directly: M is a spreadsheet
    formula, so openpyxl returns the formula text (and Google's cached value can be
    missing for a freshly appended row) — computing it from K is equivalent and robust.
    """
    if not link:
        return ""
    m = _LINKEDIN_ID_RE.search(link)
    if m:
        return f"li:{m.group(1)}"
    return f"url:{_norm_url(link)}"


def load_huntr_seen() -> set[str] | None:
    """Board job keys already processed. None means 'first run' (no baseline yet)."""
    if not HUNTR_SEEN_FILE.exists():
        return None
    try:
        return set(json.loads(HUNTR_SEEN_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def save_huntr_seen(keys: set[str]) -> None:
    HUNTR_SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    HUNTR_SEEN_FILE.write_text(json.dumps(sorted(keys)), encoding="utf-8")


def sync_huntr_to_sheet() -> int:
    """Import newly-saved Huntr board jobs into the sheet. Returns rows appended.

    Identity is the job id (column M / _job_key), not createdAt. We keep a persisted set
    of board job keys we've already handled ('seen'). Each scan, a key that newly appears
    on the board is either:
      - imported (not in the sheet yet), or
      - flagged as a DUPLICATE (already in the sheet — no CV produced; the user is alerted
        via record_duplicate), then marked seen so it's only reported once.
    First run baselines the current board (imports nothing, no backlog dump).
    """
    if not settings.huntr_board_url:
        return 0

    global _huntr_empty_streak
    jobs = huntr.HuntrClient(headless=True).fetch_jobs()
    if not jobs:
        _huntr_empty_streak += 1
        logger.info("Huntr: no jobs found on the board.")
        if _huntr_empty_streak == 2:  # alert once; ignore a single transient empty read
            record_failure(
                "huntr_board",
                error="Board okunamadı — Huntr oturumu kapanmış olabilir. "
                "Çalıştır: ./.venv/bin/python scripts/huntr_login.py",
            )
        return 0
    _huntr_empty_streak = 0

    board_keys = {_job_key(j["url"]) for j in jobs if j.get("url")}
    seen = load_huntr_seen()
    first_run = seen is None

    # Fast path: established run with nothing new on the board -> no need to read the sheet.
    if not first_run and not (board_keys - seen):
        logger.info("Huntr: no new jobs to import.")
        return 0

    sheets = SheetsClient()
    existing_by_key: dict[str, int] = {}
    for r in sheets.get_rows():
        if r.link:
            existing_by_key.setdefault(_job_key(r.link), r.number)

    if first_run:
        # First run / migration: baseline ONLY the board jobs already tracked in the sheet,
        # so we don't spam duplicate alerts for the backlog. Board jobs NOT in the sheet stay
        # unseen and are imported below — genuinely pending jobs are never swallowed.
        seen = board_keys & existing_by_key.keys()
        logger.info("Huntr first run: baselined %d board job(s) already in the sheet.", len(seen))

    # In info-only mode we save the job info straight from Huntr (reliable, captured at
    # save time) and mark N so no CV is produced — instead of re-scraping the job page,
    # which is often an expired/stale LinkedIn view that yields wrong or missing fields.
    info_only = not settings.cv_generation

    new_keys = board_keys - seen  # jobs we haven't handled yet
    to_import: list[dict] = []
    for j in jobs:
        key = _job_key(j["url"])
        if key not in new_keys:
            continue
        if key in existing_by_key:
            # Newly added to Huntr but already tracked in the sheet -> alert, don't import.
            record_duplicate(j["url"], key, existing_by_key[key])
            continue
        entry = {"url": j["url"]}
        if info_only:
            # Fill only the reliable identity fields (company J, title L) from Huntr's
            # own record — NOT a re-scrape. City is intentionally left blank: Huntr's
            # geocoded location is often wrong (e.g. "Krizan Bay"), so F/H/C are left
            # for the user to fill rather than writing bad data.
            entry["company"] = j.get("company", "")
            entry["title"] = j.get("title", "")
        to_import.append(entry)

    # Mark everything currently on the board as handled so each job is processed once.
    save_huntr_seen(set(seen) | board_keys)

    if not to_import:
        logger.info("Huntr: no new jobs to import (newly-seen ones were duplicates).")
        return 0

    marker = NO_CV_MARKER if info_only else None
    written = sheets.append_job_rows(to_import, cv_no_marker=marker)
    logger.info(
        "Huntr: imported %d new job(s) into rows %s%s.",
        len(written), written, " (info-only, no CV)" if info_only else "",
    )
    return len(written)


def is_candidate(row: Row) -> bool:
    """A row needs a CV when it has a link, no CV No yet, and a non-skip Başvuru.

    The CV No (column N) is the single source of truth: filled = done, empty = to do.
    This makes 'delete row + re-add the same job' work — the fresh row has an empty N
    so it is processed again, regardless of any past run.
    """
    if not row.link:
        return False
    if row.cv_no:  # already has a CV number
        return False
    if row.basvuru in SKIP_BASVURU_VALUES:
        return False
    return True


def find_candidates(rows: list[Row]) -> list[Row]:
    """Candidate rows, with duplicate postings removed.

    A row is skipped (no CV) when another row already covers the same posting (same
    İlan Numarası / job id, column M derived from K):
      - another row already has a CV No (column N) for that posting, OR
      - an earlier candidate row in this same scan already claimed it.
    So each distinct posting yields exactly one CV, even if the link is added twice.
    """
    done_keys = {_job_key(r.link) for r in rows if r.cv_no and r.link}
    candidates: list[Row] = []
    seen: set[str] = set()
    for r in rows:
        if not is_candidate(r):
            continue
        key = _job_key(r.link)
        if key and (key in done_keys or key in seen):
            logger.info(
                "Row %d skipped: same job already in the sheet (job id %s).",
                r.number, key,
            )
            continue
        seen.add(key)
        candidates.append(r)
    return candidates


def _save_outputs(cv_no: int, cv_md: str, full_response: str, job_description: str) -> None:
    settings.ensure_dirs()
    cv_path = settings.markdown_dir / f"cv_{cv_no}.md"
    analysis_path = settings.analysis_dir / f"cv_{cv_no}_analysis.md"
    jd_path = settings.job_description_dir / f"job_description_{cv_no}.md"

    cv_path.write_text(cv_md, encoding="utf-8")
    analysis_path.write_text(full_response, encoding="utf-8")
    jd_path.write_text(job_description, encoding="utf-8")
    logger.info("Saved CV -> %s", cv_path)


def _export_google_doc(cv_no: int, cv_md: str) -> None:
    """Build the .docx from the template, upload it to Drive as a Google Doc, and
    download that Doc back as a PDF into the local PDFs folder.

    The .docx is only an in-memory intermediary (Drive converts it to a Doc); no local
    .docx is kept. Best-effort: a failure here must not undo the Markdown CV that already
    succeeded. A single Drive client is reused so credentials load only once.
    """
    try:
        docx_bytes = docx_builder.build_docx(cv_md)
        client = drive_docs.DriveDocsClient()
        file_id = client.upload_as_google_doc(docx_bytes, f"cv_{cv_no}")
        pdf_bytes = client.export_as_pdf(file_id)
        (settings.pdf_dir / f"cv_{cv_no}.pdf").write_bytes(pdf_bytes)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Google Doc/PDF export failed for cv_%d (Markdown CV still saved).", cv_no)
        # The Markdown CV + sheet row still succeed, so this would otherwise be silent —
        # record it so a missing Google Doc/PDF is noticed.
        record_failure("drive_export", cv_no=cv_no, error=repr(exc))


def _scrape_fields(row: Row, scraper: Scraper):
    """Scrape the job page once and return (JobPage, fields).

    `fields` are the only-empty column values to write to the sheet. Shared by the
    CV-generation path and the info-only (CV_GENERATION off) path.
    """
    jp = scraper.fetch_job(row.link)
    logger.info(
        "Fetched page: %r @ %r | %s | %s (%d chars desc)",
        jp.title, jp.company, jp.city, jp.work_type, len(jp.description),
    )
    fields = {
        "C": jp.easy_apply,
        "F": jp.city,
        "H": jp.work_type,
        "L": jp.title,
        "J": jp.company,
        "J_url": jp.company_url,
    }
    return jp, fields


def _generate_and_save(
    row: Row, cv_no: int, scraper: Scraper
) -> tuple[float | None, dict, str]:
    """Scrape the page (description + fields), generate the CV, save outputs.

    Returns (match_rate, fields, languages) where fields are the column values to write
    (only-empty) to the sheet and languages is the job's top two priority programming
    languages ("Python, Java") for column Q. G (work mode) is intentionally NOT inferred —
    it is filled manually — so the relocation sentence uses the row's existing G if set.
    """
    jp, fields = _scrape_fields(row, scraper)

    work_mode = row.work_mode  # manual (often empty -> default relocation sentence)
    city = row.city or jp.city
    full_response, cv_md, match_rate = generator.generate(
        jp.description, work_mode=work_mode, city=city
    )
    languages = generator.extract_languages(full_response)

    # Expert QA second pass (toggle via CV_REVIEW): re-check the draft against the job
    # (keyword coverage, accuracy, structure, match rate) and fix problems. Fall back
    # to the draft on error.
    review_full = ""
    if settings.cv_review:
        try:
            review_full, cv_reviewed, reviewed_rate = generator.review(
                jp.description, cv_md, work_mode=work_mode, city=city
            )
            cv_md = cv_reviewed
            if reviewed_rate is not None:
                match_rate = reviewed_rate
            logger.info("Review pass done for cv_%d (final match rate: %s).", cv_no, match_rate)
        except Exception:  # noqa: BLE001
            logger.exception("Review pass failed for cv_%d; using the first draft.", cv_no)

    _save_outputs(cv_no, cv_md, full_response, jp.description)
    if review_full:
        settings.ensure_dirs()
        (settings.analysis_dir / f"cv_{cv_no}_review.md").write_text(review_full, encoding="utf-8")
    _export_google_doc(cv_no, cv_md)

    return match_rate, fields, languages


def _regenerate_one(cv_no: int, row: Row) -> float | None:
    """Regenerate a single CV from its SAVED job description (no re-scrape).

    The original page text was stored as job_description_<no>.md when the CV was first
    made; re-using it is robust against expired/removed LinkedIn postings and avoids a
    long burst of scraping. Work mode (G) and city (F) come from the sheet row.
    Overwrites cv_<no>.md/_analysis/_review, updates the same-named Google Doc, and
    re-downloads its PDF.
    Returns the final match rate (or None).
    """
    jd_path = settings.job_description_dir / f"job_description_{cv_no}.md"
    if not jd_path.exists():
        raise FileNotFoundError(f"Saved job description not found: {jd_path}")
    job_description = jd_path.read_text(encoding="utf-8").strip()
    if not job_description:
        raise ValueError(f"Saved job description is empty: {jd_path}")

    work_mode = row.work_mode  # manual G (often empty -> default relocation sentence)
    city = row.city
    full_response, cv_md, match_rate = generator.generate(
        job_description, work_mode=work_mode, city=city
    )

    review_full = ""
    if settings.cv_review:
        try:
            review_full, cv_reviewed, reviewed_rate = generator.review(
                job_description, cv_md, work_mode=work_mode, city=city
            )
            cv_md = cv_reviewed
            if reviewed_rate is not None:
                match_rate = reviewed_rate
            logger.info("Review pass done for cv_%d (final match rate: %s).", cv_no, match_rate)
        except Exception:  # noqa: BLE001
            logger.exception("Review pass failed for cv_%d; using the first draft.", cv_no)

    _save_outputs(cv_no, cv_md, full_response, job_description)
    if review_full:
        settings.ensure_dirs()
        (settings.analysis_dir / f"cv_{cv_no}_review.md").write_text(review_full, encoding="utf-8")
    _export_google_doc(cv_no, cv_md)
    return match_rate


def regenerate_cv_range(start: int, end: int, dry_run: bool = False) -> int:
    """Re-generate CVs whose CV No (column N) is in [start, end], keeping the same
    numbers. Regenerates from each CV's SAVED job description (no re-scrape), overwrites
    cv_<no>.md/_analysis/_review, updates the same-named Google Doc, re-downloads its PDF,
    and refreshes Match Rate (P). Other sheet columns are left untouched.

    Uses whatever model/effort the current settings define, so run it with the env
    overridden to pick a stronger model, e.g.:
        CLAUDE_MODEL=claude-opus-4-8 CLAUDE_EFFORT=high python scripts/regenerate.py --from 200 --to 219
    """
    sheets = SheetsClient()
    rows = sheets.get_rows()

    targets: list[tuple[int, Row]] = []
    for r in rows:
        n = SheetsClient._as_int(r.cv_no)
        if n is not None and start <= n <= end:
            targets.append((n, r))
    targets.sort(key=lambda t: t[0])

    if not targets:
        logger.info("No rows with CV No in [%d, %d].", start, end)
        return 0

    logger.info(
        "Regenerating %d CV(s) [%s] from saved job descriptions with model=%s effort=%s (review=%s).",
        len(targets),
        ", ".join(str(n) for n, _ in targets),
        settings.claude_model,
        settings.claude_effort,
        settings.cv_review,
    )
    if dry_run:
        for n, r in targets:
            logger.info("  [DRY] CV %d -> sheet row %d", n, r.number)
        return 0

    count = 0
    for n, row in targets:
        logger.info("Regenerating CV %d (row %d) ...", n, row.number)
        try:
            match_rate = _regenerate_one(n, row)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Regeneration failed for CV %d (row %d); skipping.", n, row.number)
            record_failure("regenerate", row=row.number, cv_no=n, link=row.link, error=repr(exc))
            continue
        if match_rate is not None:
            try:
                sheets.write_match_rate(row.number, match_rate)
            except Exception:  # noqa: BLE001
                logger.exception("Match-rate write failed for CV %d (files were saved).", n)
        count += 1
        logger.info("Regenerated CV %d (final match rate: %s).", n, match_rate)
    return count


def _process_info_only(candidates: list[Row], sheets: SheetsClient) -> int:
    """CV-generation-OFF path: scrape each candidate's page for its info, write the
    only-empty fields (C/F/H/J/L) to the sheet, and mark N with NO_CV_MARKER so the row
    is handled once and never assigned a CV (even after the switch is turned back on).
    No Claude call, no Google Doc, no CV number consumed. Returns rows written.
    """
    count = 0
    with Scraper(headless=True) as scraper:
        for row in candidates:
            logger.info("Processing row %d (info-only, no CV) -> %s", row.number, row.link)
            try:
                _, fields = _scrape_fields(row, scraper)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Scrape failed for row %d; will retry next scan.", row.number
                )
                record_failure("scrape", row=row.number, link=row.link, error=repr(exc))
                continue
            try:
                sheets.write_info_only_row(row.number, fields, NO_CV_MARKER)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Sheet write failed for row %d (info-only); will retry next scan.",
                    row.number,
                )
                record_failure("sheet_write", row=row.number, link=row.link, error=repr(exc))
                continue
            count += 1
    return count


def run_scan(
    dry_run: bool = False,
    limit: int | None = None,
    only_row: int | None = None,
) -> int:
    """Scan the sheet once and process candidate rows. Returns count processed.

    limit:    process at most this many candidates (sheet order).
    only_row: process only this sheet row number (must still be a candidate).
    """
    sheets = SheetsClient()
    rows = sheets.get_rows()
    candidates = find_candidates(rows)

    if only_row is not None:
        candidates = [r for r in candidates if r.number == only_row]
        if not candidates:
            logger.warning(
                "Row %d is not a candidate (check: has link? CV No (N) empty? "
                "Başvuru not in %s?).",
                only_row,
                sorted(SKIP_BASVURU_VALUES),
            )
    if limit is not None:
        candidates = candidates[:limit]

    if not candidates:
        logger.info("No candidate rows to process.")
        return 0

    mode = "CV generation" if settings.cv_generation else "info-only (CV generation OFF)"
    logger.info("Processing %d candidate row(s) [%s].", len(candidates), mode)
    if dry_run:
        for r in candidates:
            logger.info(
                "  [DRY] row %d | Başvuru=%r | %s", r.number, r.basvuru, r.link
            )
        return 0

    if not settings.cv_generation:
        return _process_info_only(candidates, sheets)

    # Never go below the highest number we've ever assigned (floor guard).
    next_no = max(sheets.next_cv_number(rows), load_last_cv_no() + 1)
    count = 0
    with Scraper(headless=True) as scraper:
        for row in candidates:
            cv_no = next_no
            logger.info("Processing row %d -> CV No %d -> %s", row.number, cv_no, row.link)

            # 1) Generate first, WITHOUT touching the sheet yet. This gives any of your
            #    own edits to this row (B/C/F/G/H...) ~1.5 min to sync to Drive before
            #    the app writes, and means we touch the sheet only once (less clobbering).
            try:
                match_rate, fields, languages = _generate_and_save(row, cv_no, scraper)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Generation failed for row %d; number not consumed, will retry next scan.",
                    row.number,
                )
                record_failure("generate", row=row.number, link=row.link, error=repr(exc))
                continue

            # 2) Single sheet write at the end: page-derived fields (only-empty) +
            #    CV No (N) + Match Rate (P) + priority languages (Q) together.
            try:
                sheets.write_processed_row(
                    row.number, fields, cv_no, match_rate, languages
                )
                save_last_cv_no(cv_no)
                next_no += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Sheet write failed for row %d (CV files were saved; will retry next scan).",
                    row.number,
                )
                record_failure("sheet_write", row=row.number, cv_no=cv_no, link=row.link, error=repr(exc))
                continue

            count += 1
    return count
