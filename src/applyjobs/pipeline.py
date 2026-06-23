"""Orchestration: detect new rows, generate CVs, save files, write back CV No."""
from __future__ import annotations

import logging

from . import docx_builder, drive_docs, generator, huntr
from .config import (
    HUNTR_CURSOR_FILE,
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

def _norm_url(url: str) -> str:
    return url.split("?", 1)[0].strip()


def load_huntr_cursor() -> str | None:
    """Highest Huntr job createdAt already accounted for (None on first ever run)."""
    if HUNTR_CURSOR_FILE.exists():
        return HUNTR_CURSOR_FILE.read_text(encoding="utf-8").strip()
    return None


def save_huntr_cursor(created_at: str) -> None:
    HUNTR_CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    HUNTR_CURSOR_FILE.write_text(created_at or "", encoding="utf-8")


def sync_huntr_to_sheet() -> int:
    """Import newly-saved Huntr board jobs into the sheet. Returns rows appended.

    A job counts as new when its createdAt is later than the stored cursor AND its URL
    is not already in the sheet. First ever run sets the cursor to the newest existing
    job and imports nothing (no backlog dump). Deleting then re-saving a job in Huntr
    gives it a fresh createdAt, so it can be re-imported (if no longer in the sheet).
    """
    if not settings.huntr_board_url:
        return 0

    jobs = huntr.HuntrClient(headless=True).fetch_jobs()
    if not jobs:
        logger.info("Huntr: no jobs found on the board.")
        return 0

    created_values = [j.get("created_at", "") for j in jobs if j.get("created_at")]
    max_created = max(created_values) if created_values else ""
    cursor = load_huntr_cursor()

    if cursor is None:  # first ever run
        save_huntr_cursor(max_created)
        logger.info("Huntr first run: cursor set to %s; imported 0 (existing backlog skipped).", max_created)
        return 0

    sheets = SheetsClient()
    existing_urls = {_norm_url(r.link) for r in sheets.get_rows() if r.link}

    # Only the URL is taken from Huntr; the rest of the columns are filled later from
    # the scraped job page (write_processed_row).
    new_jobs = [
        {"url": j["url"]}
        for j in jobs
        if j.get("created_at", "") > cursor and _norm_url(j["url"]) not in existing_urls
    ]

    # Advance the cursor past everything currently on the board so we don't re-check it.
    if max_created and max_created > cursor:
        save_huntr_cursor(max_created)

    if not new_jobs:
        logger.info("Huntr: no new jobs to import.")
        return 0

    written = sheets.append_job_rows(new_jobs)
    logger.info("Huntr: imported %d new job(s) into rows %s.", len(written), written)
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
    return [r for r in rows if is_candidate(r)]


def _save_outputs(cv_no: int, cv_md: str, full_response: str, job_description: str) -> None:
    settings.ensure_dirs()
    cv_path = settings.output_dir / f"cv_{cv_no}.md"
    analysis_path = settings.analysis_dir / f"cv_{cv_no}_analysis.md"
    jd_path = settings.job_description_dir / f"job_description_{cv_no}.md"

    cv_path.write_text(cv_md, encoding="utf-8")
    analysis_path.write_text(full_response, encoding="utf-8")
    jd_path.write_text(job_description, encoding="utf-8")
    logger.info("Saved CV -> %s", cv_path)


def _export_google_doc(cv_no: int, cv_md: str) -> None:
    """Build the .docx from the template and upload it to Drive as a Google Doc.

    Best-effort: a failure here must not undo the Markdown CV that already succeeded.
    """
    try:
        docx_bytes = docx_builder.build_docx(cv_md)
        # Local copy for inspection.
        (settings.output_dir / f"cv_{cv_no}.docx").write_bytes(docx_bytes)
        drive_docs.upload_as_google_doc(docx_bytes, f"cv_{cv_no}")
    except Exception:  # noqa: BLE001
        logger.exception("Google Doc export failed for cv_%d (Markdown CV still saved).", cv_no)


def _generate_and_save(row: Row, cv_no: int, scraper: Scraper) -> tuple[float | None, dict]:
    """Scrape the page (description + fields), generate the CV, save outputs.

    Returns (match_rate, fields) where fields are the column values to write
    (only-empty) to the sheet. G (work mode) is intentionally NOT inferred — it is
    filled manually — so the relocation sentence uses the row's existing G if set.
    """
    jp = scraper.fetch_job(row.link)
    logger.info(
        "Fetched page: %r @ %r | %s | %s (%d chars desc)",
        jp.title, jp.company, jp.city, jp.work_type, len(jp.description),
    )

    work_mode = row.work_mode  # manual (often empty -> default relocation sentence)
    city = row.city or jp.city
    full_response, cv_md, match_rate = generator.generate(
        jp.description, work_mode=work_mode, city=city
    )

    # Expert QA second pass: re-check the draft against the job (keyword coverage,
    # accuracy, structure, match rate) and fix problems. Fall back to the draft on error.
    review_full = ""
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

    fields = {
        "C": jp.easy_apply,
        "F": jp.city,
        "H": jp.work_type,
        "L": jp.title,
        "J": jp.company,
        "J_url": jp.company_url,
    }
    return match_rate, fields


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

    logger.info("Processing %d candidate row(s).", len(candidates))
    if dry_run:
        for r in candidates:
            logger.info(
                "  [DRY] row %d | Başvuru=%r | %s", r.number, r.basvuru, r.link
            )
        return 0

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
                match_rate, fields = _generate_and_save(row, cv_no, scraper)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Generation failed for row %d; number not consumed, will retry next scan.",
                    row.number,
                )
                continue

            # 2) Single sheet write at the end: page-derived fields (only-empty) +
            #    CV No (N) + Match Rate (P) together.
            try:
                sheets.write_processed_row(row.number, fields, cv_no, match_rate)
                save_last_cv_no(cv_no)
                next_no += 1
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Sheet write failed for row %d (CV files were saved; will retry next scan).",
                    row.number,
                )
                continue

            count += 1
    return count
