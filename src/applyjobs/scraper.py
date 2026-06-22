"""Job-description scraper using Playwright.

Goes to whatever URL is in the sheet's "İlan Linki" (K) column — company career
sites or LinkedIn. LinkedIn is handled as a special case using a saved login state.
"""
from __future__ import annotations

import logging

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from .config import LINKEDIN_STATE_FILE

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Selectors LinkedIn uses for the job description body (logged-in and public views).
_LINKEDIN_SELECTORS = [
    ".jobs-description__content",
    ".jobs-box__html-content",
    ".show-more-less-html__markup",
    ".description__text",
]

# On LinkedIn the job content is followed by recommendation sections we don't want.
# Cut everything from the first of these markers onward.
_LINKEDIN_END_MARKERS = [
    "More jobs",
    "People also viewed",
    "Similar jobs",
    "Jobs you may be interested in",
]


def _truncate_linkedin_noise(text: str) -> str:
    """Drop LinkedIn's trailing 'More jobs' / recommendations sections."""
    low = text.lower()
    cut = len(text)
    for marker in _LINKEDIN_END_MARKERS:
        idx = low.find(marker.lower())
        if idx != -1:
            cut = min(cut, idx)
    return text[:cut].strip()


def _clean_html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "svg"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines()]
    # Collapse blank lines and drop very short navigational fragments left over.
    cleaned: list[str] = []
    for ln in lines:
        if not ln:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        cleaned.append(ln)
    return "\n".join(cleaned).strip()


class Scraper:
    """Keeps one browser/context open across multiple fetches."""

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless
        self._pw = None
        self._browser = None
        self._context = None

    def __enter__(self) -> "Scraper":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        ctx_kwargs = {"user_agent": _USER_AGENT}
        if LINKEDIN_STATE_FILE.exists():
            ctx_kwargs["storage_state"] = str(LINKEDIN_STATE_FILE)
        self._context = self._browser.new_context(**ctx_kwargs)
        return self

    def __exit__(self, *exc) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer:
                    closer.close()
            except Exception:  # noqa: BLE001
                pass
        if self._pw:
            self._pw.stop()

    def fetch_description(self, url: str) -> str:
        if not url:
            raise ValueError("Empty job URL")
        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2_500)  # let client-side content render

            is_linkedin = "linkedin.com" in url.lower()
            if is_linkedin:
                text = self._extract_linkedin(page)
                if text:
                    return _truncate_linkedin_noise(text)
                logger.warning("LinkedIn selectors empty; falling back to full-page text.")

            html = page.content()
            text = _clean_html_to_text(html)
            if is_linkedin:
                text = _truncate_linkedin_noise(text)
            if len(text) < 80:
                raise RuntimeError(
                    f"Extracted description too short ({len(text)} chars) from {url}"
                )
            return text
        finally:
            page.close()

    def _extract_linkedin(self, page) -> str:
        # Click "show more" if present so the full description is in the DOM.
        for sel in (
            "button.show-more-less-html__button",
            "button[aria-label*='more']",
        ):
            try:
                btn = page.query_selector(sel)
                if btn:
                    btn.click(timeout=2_000)
                    page.wait_for_timeout(500)
                    break
            except Exception:  # noqa: BLE001
                pass

        for sel in _LINKEDIN_SELECTORS:
            el = page.query_selector(sel)
            if el:
                html = el.inner_html()
                text = _clean_html_to_text(html)
                if len(text) >= 80:
                    return text
        return ""


def fetch_description(url: str, headless: bool = True) -> str:
    """Convenience one-shot fetch (opens and closes its own browser)."""
    with Scraper(headless=headless) as s:
        return s.fetch_description(url)
