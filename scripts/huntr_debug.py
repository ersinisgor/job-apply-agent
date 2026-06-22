"""Dump the Huntr board (rendered HTML + captured JSON) for finalizing field mapping.

Run this after huntr_login.py if job parsing misses fields. It saves files under
./huntr_debug/ which can be inspected to confirm Huntr's exact JSON shape.

Usage:
    python scripts/huntr_debug.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.applyjobs.config import settings  # noqa: E402
from src.applyjobs.huntr import HuntrClient  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not settings.huntr_board_url:
        raise SystemExit("Set HUNTR_BOARD_URL in .env first.")
    out = Path(__file__).resolve().parents[1] / "huntr_debug"
    # headless=False so you can see what loads; close it after it finishes.
    HuntrClient(headless=False).dump_debug(out)
    print(f"\nDump written to: {out}")
    print("Share board.html + payload_*.json so the field mapping can be finalized.")


if __name__ == "__main__":
    main()
