"""Entry point: continuously poll the Google Sheet and generate CVs for new rows."""
from __future__ import annotations

import logging
import time

from .config import settings
from .pipeline import run_scan, sync_huntr_to_sheet
from .reporting import LOG_FILE, FAILURES_FILE, setup_logging


def main() -> None:
    setup_logging()
    log = logging.getLogger("applyjobs")
    log.info("Logs: %s | failures: %s", LOG_FILE, FAILURES_FILE)

    settings.validate()
    settings.ensure_dirs()

    huntr_enabled = bool(settings.huntr_board_url)
    log.info(
        "ApplyJobsAgent started. Polling every %ds | model=%s | CV generation=%s | Huntr=%s | output=%s",
        settings.poll_interval,
        settings.claude_model,
        "on" if settings.cv_generation else "OFF (info-only: import + save fields, no CV)",
        f"on (every {settings.huntr_poll_interval}s)" if huntr_enabled else "off",
        settings.output_dir,
    )

    interval = settings.huntr_poll_interval if huntr_enabled else settings.poll_interval
    while True:
        try:
            if huntr_enabled:
                try:
                    imported = sync_huntr_to_sheet()
                    if imported:
                        log.info("Huntr: %d new job(s) imported into the sheet.", imported)
                except Exception:  # noqa: BLE001
                    log.exception("Huntr sync failed; continuing with sheet scan.")

            processed = run_scan(dry_run=False)
            if processed:
                if settings.cv_generation:
                    log.info("Scan complete: %d CV(s) generated.", processed)
                else:
                    log.info("Scan complete: %d row(s) saved (info-only, no CV).", processed)
        except KeyboardInterrupt:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Scan failed; will retry next interval.")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            break

    log.info("Stopped.")


if __name__ == "__main__":
    main()
