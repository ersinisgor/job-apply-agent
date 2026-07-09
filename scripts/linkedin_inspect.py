"""Inspect a LinkedIn job page: dump JSON-LD + candidate DOM for field mapping.

Usage:
    python scripts/linkedin_inspect.py <linkedin-job-url>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright  # noqa: E402

from src.applyjobs.scraper import _USER_AGENT  # noqa: E402


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.linkedin.com/jobs/view/4421164942/"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        # Guest context on purpose — attaching the real LinkedIn session to an
        # automated browser gets the account flagged (see scraper.py docstring).
        ctx = browser.new_context(user_agent=_USER_AGENT)
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(3000)

        print("=== JSON-LD blocks ===")
        for s in page.query_selector_all('script[type="application/ld+json"]'):
            try:
                data = json.loads(s.inner_text())
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for it in items:
                if isinstance(it, dict) and it.get("@type") == "JobPosting":
                    print(json.dumps({k: it.get(k) for k in
                        ("title", "employmentType", "jobLocationType", "hiringOrganization", "jobLocation")},
                        ensure_ascii=False, indent=2)[:1500])

        print("\n=== DOM candidates ===")
        for label, sel in [
            ("company anchor", "a[href*='/company/']"),
            ("top-card company", ".job-details-jobs-unified-top-card__company-name a"),
            ("apply button", "button.jobs-apply-button"),
            ("apply (aria)", "button[aria-label*='Easy Apply'], button[aria-label*='Kolay']"),
            ("primary desc container", ".job-details-jobs-unified-top-card__primary-description-container"),
            ("preferences pills", ".job-details-fit-level-preferences button, .job-details-jobs-unified-top-card__job-insight"),
        ]:
            els = page.query_selector_all(sel)
            print(f"\n[{label}] ({sel}) -> {len(els)} match")
            for e in els[:4]:
                txt = (e.inner_text() or "").strip().replace("\n", " | ")[:120]
                href = e.get_attribute("href")
                print(f"   text={txt!r}" + (f" href={href}" if href else ""))
        ctx.close(); browser.close()


if __name__ == "__main__":
    main()
