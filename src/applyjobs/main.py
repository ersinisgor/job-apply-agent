"""Entry point: continuously poll the Google Sheet and generate CVs for new rows."""
from __future__ import annotations

import logging
import time

from .config import settings
from .pipeline import run_scan, sync_huntr_to_sheet


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    _setup_logging()
    log = logging.getLogger("applyjobs")

    settings.validate()
    settings.ensure_dirs()

    huntr_enabled = bool(settings.huntr_board_url)
    log.info(
        "ApplyJobsAgent started. Polling every %ds | model=%s | Huntr=%s | output=%s",
        settings.poll_interval,
        settings.claude_model,
        f"on (every {settings.huntr_poll_interval}s)" if huntr_enabled else "off",
        settings.output_dir,
    )

    last_huntr = 0.0  # 0 forces a Huntr sync on the first iteration
    while True:
        try:
            if huntr_enabled and time.monotonic() - last_huntr >= settings.huntr_poll_interval:
                try:
                    imported = sync_huntr_to_sheet()
                    if imported:
                        log.info("Huntr: %d new job(s) imported into the sheet.", imported)
                except Exception:  # noqa: BLE001
                    log.exception("Huntr sync failed; continuing with sheet scan.")
                last_huntr = time.monotonic()

            processed = run_scan(dry_run=False)
            if processed:
                log.info("Scan complete: %d CV(s) generated.", processed)
        except KeyboardInterrupt:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Scan failed; will retry next interval.")
        try:
            time.sleep(settings.poll_interval)
        except KeyboardInterrupt:
            break

    log.info("Stopped.")


if __name__ == "__main__":
    main()
