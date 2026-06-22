"""Orchestration: detect new rows, generate CVs, save files, write back CV No."""
from __future__ import annotations

import json
import logging

from . import docx_builder, drive_docs, generator
from .config import (
    PROCESSED_STATE_FILE,
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


def load_processed() -> set[str]:
    if PROCESSED_STATE_FILE.exists():
        try:
            return set(json.loads(PROCESSED_STATE_FILE.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            logger.warning("Could not read processed state; starting fresh.")
    return set()


def save_processed(processed: set[str]) -> None:
    PROCESSED_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_STATE_FILE.write_text(
        json.dumps(sorted(processed), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def is_candidate(row: Row, processed: set[str]) -> bool:
    if not row.link:
        return False
    if row.cv_no:  # already has a CV number
        return False
    if row.basvuru in SKIP_BASVURU_VALUES:
        return False
    if row.key() in processed:
        return False
    return True


def find_candidates(rows: list[Row], processed: set[str]) -> list[Row]:
    return [r for r in rows if is_candidate(r, processed)]


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


def _generate_and_save(row: Row, cv_no: int, scraper: Scraper) -> float | None:
    """Scrape the link, generate the CV, save outputs. Returns the match rate."""
    job_description = scraper.fetch_description(row.link)
    logger.info("Fetched description (%d chars)", len(job_description))

    full_response, cv_md, match_rate = generator.generate(
        job_description, work_mode=row.work_mode, city=row.city
    )
    _save_outputs(cv_no, cv_md, full_response, job_description)
    _export_google_doc(cv_no, cv_md)
    return match_rate


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
    processed = load_processed()
    candidates = find_candidates(rows, processed)

    if only_row is not None:
        candidates = [r for r in candidates if r.number == only_row]
        if not candidates:
            logger.warning(
                "Row %d is not a candidate (check: has link? CV No empty? "
                "Başvuru not in %s? not already processed?).",
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
                match_rate = _generate_and_save(row, cv_no, scraper)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Generation failed for row %d; number not consumed, will retry next scan.",
                    row.number,
                )
                continue

            # 2) Single sheet write at the end: CV No (N) + Match Rate (P) together.
            try:
                sheets.write_cv_and_match(row.number, cv_no, match_rate)
                save_last_cv_no(cv_no)
                next_no += 1
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Sheet write failed for row %d (CV files were saved; will retry next scan).",
                    row.number,
                )
                continue

            processed.add(row.key())
            save_processed(processed)
            count += 1
    return count
