"""One-time helper: log in to Huntr so the agent can read your board.

Usage:
    python scripts/huntr_login.py

A Chromium window opens at huntr.co. Log in, then press ENTER in the terminal.
The session is saved to credentials/huntr_state.json (gitignored).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright  # noqa: E402

from src.applyjobs.config import CREDENTIALS_DIR, HUNTR_STATE_FILE  # noqa: E402


def main() -> None:
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://huntr.co/login")
        print("\n>>> Log in to Huntr in the opened window.")
        input(">>> When you are fully logged in (board visible), press ENTER here to save... ")
        context.storage_state(path=str(HUNTR_STATE_FILE))
        print(f"Saved Huntr session to {HUNTR_STATE_FILE}")
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
