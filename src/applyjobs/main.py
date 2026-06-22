"""Entry point: continuously poll the Google Sheet and generate CVs for new rows."""
from __future__ import annotations

import logging
import time

from .config import settings
from .pipeline import run_scan


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

    log.info(
        "ApplyJobsAgent started. Polling every %ds | model=%s | output=%s",
        settings.poll_interval,
        settings.claude_model,
        settings.output_dir,
    )

    while True:
        try:
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
