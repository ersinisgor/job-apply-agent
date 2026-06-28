"""Re-generate a range of existing CVs (by CV No) with the current settings.

Keeps the same CV numbers; overwrites cv_<no>.md / .docx / _analysis / _review,
updates the same-named Google Doc, and refreshes the Match Rate (P) column.
Other sheet columns are left untouched.

Usage:
    python scripts/regenerate.py --from 200 --to 219
    python scripts/regenerate.py --from 200 --to 219 --dry-run

To use a stronger model/effort just for this run, set the env vars on the command:
    CLAUDE_MODEL=claude-opus-4-8 CLAUDE_EFFORT=high \
        ./.venv/bin/python scripts/regenerate.py --from 200 --to 219
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.applyjobs.config import settings  # noqa: E402
from src.applyjobs.pipeline import regenerate_cv_range  # noqa: E402
from src.applyjobs.reporting import setup_logging  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-generate a range of existing CVs.")
    parser.add_argument("--from", dest="start", type=int, required=True, help="First CV No.")
    parser.add_argument("--to", dest="end", type=int, required=True, help="Last CV No (inclusive).")
    parser.add_argument("--dry-run", action="store_true", help="List target CVs only.")
    args = parser.parse_args()

    setup_logging()

    settings.validate()
    settings.ensure_dirs()
    log = logging.getLogger("applyjobs")
    count = regenerate_cv_range(args.start, args.end, dry_run=args.dry_run)
    log.info("Done. Regenerated %d CV(s).", count)


if __name__ == "__main__":
    main()
