"""Make problems observable after the fact, instead of scrolling past in a terminal
you are not watching.

Three layers:
  1. setup_logging() — console + a rotating file log (state/agent.log) with full detail
     (tracebacks included), so nothing is lost.
  2. record_failure() — appends ONE human-readable line per failure to
     state/failures.log. This is the short "report" to glance at after a batch.
  3. A best-effort macOS desktop notification on each failure, so you get alerted
     without watching the terminal.
"""
from __future__ import annotations

import datetime
import logging
import subprocess
import sys
from logging.handlers import RotatingFileHandler

from .config import STATE_DIR

LOG_FILE = STATE_DIR / "agent.log"
FAILURES_FILE = STATE_DIR / "failures.log"

logger = logging.getLogger(__name__)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure console + rotating-file logging. Safe to call once per program start."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return  # already configured (don't add duplicate handlers)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def _notify(title: str, message: str) -> None:
    """Best-effort macOS desktop notification; a no-op elsewhere or on any error."""
    if sys.platform != "darwin":
        return
    try:
        safe = message.replace('"', "'")[:200]
        subprocess.run(
            ["osascript", "-e", f'display notification "{safe}" with title "{title}"'],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except Exception:  # noqa: BLE001
        pass


def record_failure(
    stage: str,
    *,
    row: int | None = None,
    cv_no: int | None = None,
    link: str = "",
    error: str = "",
) -> None:
    """Record a failure: append to state/failures.log, log it, and raise a notification.

    stage examples: "generate", "drive_export", "sheet_write", "regenerate".
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    one_line_error = " ".join(str(error).split())[:300]
    line = f"{ts} | {stage:<12} | row={row} cv_no={cv_no} | {link} | {one_line_error}\n"
    try:
        with FAILURES_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        logger.exception("Could not write to %s", FAILURES_FILE)
    logger.error("FAILURE [%s] row=%s cv_no=%s: %s", stage, row, cv_no, one_line_error)
    _notify("ApplyJobsAgent — hata", f"{stage}: row={row} cv_no={cv_no}")


def record_duplicate(link: str, job_key: str, sheet_row: int | None = None) -> None:
    """A job newly added to Huntr is already in the sheet, so no CV is produced for it.

    Surfaced like a failure (desktop notification + a line in failures.log) so the user
    notices it instead of assuming a CV was made.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    job_id = job_key.split(":", 1)[-1]  # "li:4364788282" -> "4364788282"
    where = f"satır {sheet_row}" if sheet_row else "mevcut bir satır"
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} | DUPLICATE    | İlan no {job_id} zaten sheet'te ({where}) | {link} | CV ÜRETİLMEDİ\n"
    try:
        with FAILURES_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        logger.exception("Could not write to %s", FAILURES_FILE)
    logger.warning(
        "DUPLICATE: job %s already in the sheet (%s) — no CV generated.", job_id, where
    )
    _notify(
        "ApplyJobsAgent — tekrar ilan",
        f"İlan no {job_id} zaten sheet'te ({where}); CV üretilmedi.",
    )
