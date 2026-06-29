"""Diagnose how each Huntr board job will be handled. Read-only (changes nothing).

IMPORTANT: stop the running agent first (Ctrl-C in its terminal), because it uses the
same Chrome profile — two browsers on one profile conflict.

For every board job it shows: its job id (column M), whether it is newly-seen, whether
it is already in the sheet, and the resulting decision (import / duplicate-alert /
already-handled). Useful when a job you added to Huntr did not turn into a CV.

Usage:
    ./.venv/bin/python scripts/huntr_diagnose.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.applyjobs.config import settings  # noqa: E402
from src.applyjobs.huntr import HuntrClient  # noqa: E402
from src.applyjobs.pipeline import _job_key, load_huntr_seen  # noqa: E402
from src.applyjobs.reporting import setup_logging  # noqa: E402
from src.applyjobs.sheets import SheetsClient  # noqa: E402


def main() -> None:
    setup_logging()
    settings.validate()

    seen = load_huntr_seen()
    print(f"\nSEEN baseline: {'<none — next run will baseline>' if seen is None else f'{len(seen)} job key(s)'}")

    # The board JSON sometimes fails to load in one shot (or the running agent is using
    # the same Chrome profile) -> 0 jobs. Retry a few times before giving up.
    jobs: list[dict] = []
    for attempt in range(1, 4):
        jobs = HuntrClient(headless=True).fetch_jobs()
        if jobs:
            break
        print(f"  (attempt {attempt}: board not loaded, retrying...)")
    print(f"Parsed {len(jobs)} job(s) from the board.")
    if not jobs:
        print(
            "\nBoard could not be read. Make sure the agent is fully STOPPED (Ctrl-C) so it\n"
            "is not using the same Chrome profile, then run this again."
        )
        return

    existing_by_key: dict[str, int] = {}
    for r in SheetsClient().get_rows():
        if r.link:
            existing_by_key.setdefault(_job_key(r.link), r.number)
    print(f"Sheet contains {len(existing_by_key)} job key(s).\n")

    seen_set = seen or set()
    print("--- per board job ---")
    for j in jobs:
        key = _job_key(j["url"])
        is_new = key not in seen_set
        in_sheet = key in existing_by_key
        if seen is None:
            decision = "BASELINE (first run: seen, no action)"
        elif not is_new:
            decision = "already handled (seen)"
        elif in_sheet:
            decision = f"DUPLICATE -> alert, no CV (sheet row {existing_by_key[key]})"
        else:
            decision = "IMPORT -> new row + CV"
        print(f"  {key:<18} new={is_new!s:<5} inSheet={in_sheet!s:<5} | {decision} | {(j.get('title') or '')[:32]}")


if __name__ == "__main__":
    main()
