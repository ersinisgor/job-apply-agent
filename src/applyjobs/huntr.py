"""Read the user's Huntr board via Playwright.

Huntr exposes no public API for individual accounts, so we drive the logged-in web
app (huntr.co) and capture the JSON the board loads in the background, then pull job
records out of it heuristically. This avoids depending on fragile DOM selectors.

Setup: run `scripts/huntr_login.py` once to save the session. If parsing ever misses
jobs, run `scripts/huntr_debug.py` to dump the page + captured JSON so the field
mapping can be refined against the live board.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from playwright.sync_api import sync_playwright

from .config import HUNTR_PROFILE_DIR, settings
from .scraper import _USER_AGENT, _clean_html_to_text

logger = logging.getLogger(__name__)


def launch_huntr_context(pw, headless: bool):
    """Open a persistent real-Chrome context for Huntr.

    Uses the system Chrome (channel="chrome") and removes the automation flags that
    make Google show "this browser may not be secure" and block sign-in. The session
    persists in HUNTR_PROFILE_DIR so login is only needed once.
    """
    HUNTR_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(HUNTR_PROFILE_DIR),
        headless=headless,
        channel="chrome",
        user_agent=_USER_AGENT,
        # Drop the automation/no-sandbox flags so Chrome behaves like a normal browser
        # (no infobars, and Google's "browser not secure" sign-in block is avoided).
        ignore_default_args=["--enable-automation", "--no-sandbox"],
        args=["--disable-blink-features=AutomationControlled"],
    )

# Candidate JSON keys for each field (Huntr's exact names are confirmed via debug dump).
_TITLE_KEYS = ("title", "jobTitle", "position", "role", "name")
_COMPANY_KEYS = ("company", "companyName", "employer", "organization", "employerName")
_URL_KEYS = ("url", "jobUrl", "postUrl", "link", "applyUrl", "jobPostingUrl", "jobPostUrl")
_LOCATION_KEYS = ("location", "jobLocation", "city", "locationName")
_DESC_KEYS = ("description", "jobDescription", "desc", "details")


def _first(d: dict, keys) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):  # e.g. {"name": "..."} nested
            for kk in ("name", "title", "label", "value"):
                if isinstance(v.get(kk), str) and v[kk].strip():
                    return v[kk].strip()
    return ""


def _looks_like_job(d: dict) -> bool:
    has_title = bool(_first(d, _TITLE_KEYS))
    has_anchor = bool(_first(d, _URL_KEYS) or _first(d, _COMPANY_KEYS))
    return has_title and has_anchor


def _walk_for_jobs(node, out: list[dict]) -> None:
    """Recursively collect dict nodes that look like job records."""
    if isinstance(node, dict):
        if _looks_like_job(node):
            out.append(node)
        for v in node.values():
            _walk_for_jobs(v, out)
    elif isinstance(node, list):
        for item in node:
            _walk_for_jobs(item, out)


def _to_job(d: dict) -> dict:
    return {
        "company": _first(d, _COMPANY_KEYS),
        "title": _first(d, _TITLE_KEYS),
        "location": _first(d, _LOCATION_KEYS),
        "url": _first(d, _URL_KEYS),
        "description": _clean_html_to_text(_first(d, _DESC_KEYS)) if _first(d, _DESC_KEYS) else "",
    }


class HuntrClient:
    def __init__(self, headless: bool = True) -> None:
        self._headless = headless

    def _capture_payloads(self, context) -> list:
        """Load the board and return all JSON response bodies captured during load."""
        payloads: list = []

        def on_response(resp):
            ct = (resp.headers or {}).get("content-type", "")
            if "application/json" not in ct:
                return
            try:
                payloads.append(resp.json())
            except Exception:  # noqa: BLE001
                pass

        page = context.new_page()
        page.on("response", on_response)
        page.goto(settings.huntr_board_url, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(3_000)
        page.close()
        return payloads

    def fetch_jobs(self) -> list[dict]:
        """Return jobs from the board: list of {company,title,location,url,description}."""
        if not settings.huntr_board_url:
            return []
        with sync_playwright() as pw:
            context = launch_huntr_context(pw, headless=self._headless)
            try:
                payloads = self._capture_payloads(context)
            finally:
                context.close()

        raw: list[dict] = []
        for p in payloads:
            _walk_for_jobs(p, raw)

        # De-dupe by url (fallback title+company) and require a URL to be usable.
        jobs: dict[str, dict] = {}
        for d in raw:
            job = _to_job(d)
            if not job["url"]:
                continue
            key = job["url"].split("?", 1)[0]
            jobs.setdefault(key, job)
        result = list(jobs.values())
        logger.info("Huntr: captured %d JSON payloads, %d job(s) with URL.", len(payloads), len(result))
        return result

    def dump_debug(self, out_dir: Path) -> None:
        """Save captured JSON payloads + rendered HTML for finalizing field mapping."""
        out_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            context = launch_huntr_context(pw, headless=self._headless)
            try:
                payloads = self._capture_payloads(context)
                page = context.new_page()
                page.goto(settings.huntr_board_url, wait_until="networkidle", timeout=60_000)
                page.wait_for_timeout(3_000)
                (out_dir / "board.html").write_text(page.content(), encoding="utf-8")
                page.close()
            finally:
                context.close()
        for i, p in enumerate(payloads):
            try:
                (out_dir / f"payload_{i:02d}.json").write_text(
                    json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception:  # noqa: BLE001
                pass
        logger.info("Huntr debug dump written to %s (%d payloads).", out_dir, len(payloads))
