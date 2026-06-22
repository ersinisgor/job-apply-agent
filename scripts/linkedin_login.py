"""One-time helper: open a real browser, let the user log in to LinkedIn,
then save the session (cookies + local storage) so the scraper can read
authenticated job pages.

Usage:
    python scripts/linkedin_login.py

A Chromium window opens at LinkedIn. Log in, then press ENTER in the terminal.
The session is saved to credentials/linkedin_state.json (gitignored).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright  # noqa: E402

from src.applyjobs.config import CREDENTIALS_DIR, LINKEDIN_STATE_FILE  # noqa: E402


def main() -> None:
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")
        print("\n>>> Log in to LinkedIn in the opened window.")
        input(">>> When you are fully logged in, press ENTER here to save the session... ")
        context.storage_state(path=str(LINKEDIN_STATE_FILE))
        print(f"Saved session to {LINKEDIN_STATE_FILE}")
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
