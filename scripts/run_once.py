"""Run a single scan of the sheet (for cron jobs or manual testing).

Usage:
    python scripts/run_once.py             # process all candidate rows once
    python scripts/run_once.py --dry-run   # just list candidates, write nothing
    python scripts/run_once.py --limit 1   # process at most 1 candidate (good for a first test)
    python scripts/run_once.py --row 430   # process only sheet row 430
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.applyjobs.config import settings  # noqa: E402
from src.applyjobs.pipeline import run_scan, sync_huntr_to_sheet  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one scan of the job sheet.")
    parser.add_argument("--dry-run", action="store_true", help="List candidates only.")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N candidates.")
    parser.add_argument("--row", type=int, default=None, help="Process only this sheet row number.")
    parser.add_argument(
        "--huntr", action="store_true", help="Sync new Huntr jobs into the sheet first."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    settings.validate()
    settings.ensure_dirs()
    log = logging.getLogger("applyjobs")
    if args.huntr:
        imported = sync_huntr_to_sheet()
        log.info("Huntr: %d new job(s) imported.", imported)
    count = run_scan(dry_run=args.dry_run, limit=args.limit, only_row=args.row)
    log.info("Done. Processed %d row(s).", count)


if __name__ == "__main__":
    main()
