"""Job-description scraper using Playwright.

Goes to whatever URL is in the sheet's "İlan Linki" (K) column — company career
sites or LinkedIn. LinkedIn is handled as a special case using a saved login state.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from .config import LINKEDIN_STATE_FILE

logger = logging.getLogger(__name__)


@dataclass
class JobPage:
    """Structured data read from a job posting page."""

    url: str
    description: str
    title: str = ""
    company: str = ""
    company_url: str = ""
    city: str = ""
    work_type: str = ""   # Full-Time / Part-Time / Contract
    easy_apply: str = ""  # "Yok" for non-LinkedIn; "" for LinkedIn (not detectable)


# Canonical spelling for common cities (keys are Turkish-folded + lowercased, so both
# "Eskisehir" and "Eskişehir" resolve here).
_CITY_MAP = {
    "istanbul": "İstanbul",
    "izmir": "İzmir",
    "ankara": "Ankara",
    "eskisehir": "Eskişehir",
    "bursa": "Bursa",
    "icel": "Mersin",
    "mersin": "Mersin",
}

# Fold Turkish-specific letters so spelling variants map to the same key (length-preserving).
_TR_FOLD = str.maketrans(
    {
        "İ": "i", "I": "i", "ı": "i",
        "Ş": "s", "ş": "s", "Ç": "c", "ç": "c", "Ğ": "g", "ğ": "g",
        "Ö": "o", "ö": "o", "Ü": "u", "ü": "u",
    }
)


def _city_key(s: str) -> str:
    return s.translate(_TR_FOLD).lower().strip()


# LinkedIn metro-area labels: 'Greater İzmir', 'İzmir Metropolitan Area', 'İzmir ve
# Çevresi' all mean the city itself — strip the modifier down to the bare city.
_AREA_PREFIXES = ("greater ",)
_AREA_SUFFIXES = (
    " metropolitan area",
    " metropolitan bolgesi",
    " ve cevresi",
    " bolgesi",
    " cevresi",
    " area",
)


def _strip_area(s: str) -> str:
    """'Greater İzmir' -> 'İzmir'; 'İzmir Metropolitan Area' -> 'İzmir'."""
    out = (s or "").strip()
    low = _city_key(out)  # length-preserving, so slicing by len() stays aligned
    for p in _AREA_PREFIXES:
        if low.startswith(p):
            out = out[len(p):].strip()
            low = _city_key(out)
            break
    for suf in _AREA_SUFFIXES:
        if low.endswith(suf):
            out = out[: len(out) - len(suf)].strip()
            break
    return out


def _clean_city(text: str) -> str:
    """LinkedIn location like 'Istanbul, Istanbul, Türkiye' -> 'İstanbul', and metro
    labels like 'Greater İzmir' -> 'İzmir'.

    Strips metro-area modifiers, drops duplicated segments, keeps the first (city), and
    canonicalizes spelling.
    """
    text = (text or "").strip()
    if not text:
        return ""
    seen: set[str] = set()
    uniq: list[str] = []
    for part in text.split(","):
        p = _strip_area(part.strip())
        k = _city_key(p)
        if k and k not in seen:
            seen.add(k)
            uniq.append(p)
    if not uniq:
        return ""
    return _CITY_MAP.get(_city_key(uniq[0]), uniq[0])


def _map_employment(raw: str) -> str:
    r = (raw or "").strip().lower()
    if not r:
        return ""
    if "part" in r:
        return "Part-Time"
    if "contract" in r or "temporary" in r or "temp" in r:
        return "Contract"
    if "full" in r:
        return "Full-Time"
    return ""

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
        """Backward-compatible: just the description text."""
        return self.fetch_job(url).description

    def fetch_job(self, url: str) -> JobPage:
        """Read the job page once: description + structured fields.

        LinkedIn only serves its public (guest) view to automation, so fields come
        from the public-view DOM (top card + job-criteria list), with a JSON-LD
        fallback for non-LinkedIn career sites.
        """
        if not url:
            raise ValueError("Empty job URL")
        is_linkedin = "linkedin.com" in url.lower()
        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2_500)
            description = self._extract_description(page, is_linkedin)
            fields = self._extract_fields(page)
            return JobPage(
                url=url,
                description=description,
                title=fields.get("title", ""),
                company=fields.get("company", ""),
                company_url=fields.get("company_url", ""),
                city=fields.get("city", ""),
                work_type=fields.get("work_type", ""),
                easy_apply="" if is_linkedin else "Yok",
            )
        finally:
            page.close()

    def _extract_description(self, page, is_linkedin: bool) -> str:
        if is_linkedin:
            text = self._extract_linkedin(page)
            if text:
                return _truncate_linkedin_noise(text)
            logger.warning("LinkedIn selectors empty; falling back to full-page text.")
        text = _clean_html_to_text(page.content())
        if is_linkedin:
            text = _truncate_linkedin_noise(text)
        if len(text) < 80:
            raise RuntimeError(f"Extracted description too short ({len(text)} chars).")
        return text

    def _extract_fields(self, page) -> dict:
        """Title/company(+url)/city/employment-type from the LinkedIn public view,
        falling back to JSON-LD JobPosting (covers many non-LinkedIn career sites)."""
        def text_of(sel: str) -> str:
            el = page.query_selector(sel)
            return (el.inner_text() or "").strip() if el else ""

        title = text_of("h1.top-card-layout__title")
        company = company_url = ""
        a = page.query_selector("a.topcard__org-name-link")
        if a:
            company = (a.inner_text() or "").strip()
            company_url = (a.get_attribute("href") or "").split("?", 1)[0]
        city = _clean_city(text_of(".topcard__flavor--bullet"))
        work_type = ""
        for li in page.query_selector_all("li.description__job-criteria-item"):
            t = " ".join((li.inner_text() or "").split())
            if "employment type" in t.lower():
                work_type = _map_employment(t.lower().split("employment type", 1)[-1])
                break

        if not (title and company and city and work_type):
            jl = self._parse_jsonld(page)
            title = title or jl.get("title", "")
            company = company or jl.get("company", "")
            company_url = company_url or jl.get("company_url", "")
            city = city or _clean_city(jl.get("city", ""))
            work_type = work_type or _map_employment(jl.get("employment_type", ""))

        return {"title": title, "company": company, "company_url": company_url,
                "city": city, "work_type": work_type}

    @staticmethod
    def _parse_jsonld(page) -> dict:
        for s in page.query_selector_all('script[type="application/ld+json"]'):
            try:
                data = json.loads(s.inner_text())
            except Exception:  # noqa: BLE001
                continue
            for it in (data if isinstance(data, list) else [data]):
                if not (isinstance(it, dict) and it.get("@type") == "JobPosting"):
                    continue
                org = it.get("hiringOrganization") or {}
                loc = it.get("jobLocation") or {}
                addr = (loc.get("address") if isinstance(loc, dict) else {}) or {}
                emp = it.get("employmentType")
                if isinstance(emp, list):
                    emp = emp[0] if emp else ""
                return {
                    "title": it.get("title", "") or "",
                    "company": org.get("name", "") if isinstance(org, dict) else "",
                    "company_url": (org.get("sameAs") or org.get("url") or "") if isinstance(org, dict) else "",
                    "city": addr.get("addressLocality", "") if isinstance(addr, dict) else "",
                    "employment_type": emp or "",
                }
        return {}

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
