"""One-time helper: log in to Huntr so the agent can read your board.

Uses a persistent real-Chrome profile and removes automation flags, so Google
sign-in ("Bu tarayıcı güvenli olmayabilir") is not blocked. The session is stored
in credentials/huntr_profile/ and reused automatically afterwards.

Usage:
    python scripts/huntr_login.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright  # noqa: E402

from src.applyjobs.config import settings  # noqa: E402
from src.applyjobs.huntr import launch_huntr_context  # noqa: E402


def main() -> None:
    start_url = settings.huntr_board_url or "https://huntr.co/login"
    with sync_playwright() as pw:
        context = launch_huntr_context(pw, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(start_url)
        print("\n>>> Log in to Huntr in the opened Chrome window (Google sign-in works here).")
        input(">>> When your board is visible, press ENTER here to finish... ")
        context.close()
    print("Done. Session saved in credentials/huntr_profile/ (reused automatically).")


if __name__ == "__main__":
    main()
