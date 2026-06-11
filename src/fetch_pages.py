"""HTTP fetch, caching, and robots.txt checks."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from src.fetch_cache import get_cached_fetch, put_cached_fetch
from src.paths import HTML_CACHE, PDF_CACHE, USER_AGENT
from src.role_config import DOMAIN_PROBE_PATHS, PDF_LINK_KEYWORDS
from src.url_utils import normalize_url

_robots_cache: dict[str, RobotFileParser | None] = {}


@dataclass
class JurisdictionFetchStats:
    cache_hits: int = 0
    cache_misses: int = 0
    timeout_count: int = 0
    fetch_error_count: int = 0


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _get_robots(base_url: str) -> RobotFileParser | None:
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin in _robots_cache:
        return _robots_cache[origin]
    rp = RobotFileParser()
    robots_url = urljoin(origin, "/robots.txt")
    try:
        rp.set_url(robots_url)
        rp.read()
        _robots_cache[origin] = rp
        return rp
    except Exception:
        _robots_cache[origin] = None
        return None


def allowed_by_robots(url: str) -> bool:
    rp = _get_robots(url)
    if rp is None:
        return True
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def same_domain(url: str, base: str) -> bool:
    return urlparse(url).netloc.lower() == urlparse(base).netloc.lower()


def is_gov_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host.endswith(".gov") or ".gov." in host


def _response_html(resp: httpx.Response) -> str | None:
    if resp.status_code == 200:
        pass
    elif resp.status_code == 403 and len(resp.text) > 2000:
        lower = resp.text.lower()
        if "just a moment" in lower or "403 - forbidden" in lower[:500]:
            return None
    else:
        return None
    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        return None
    return resp.text


class PageFetcher:
    def __init__(
        self,
        delay: float = 3.0,
        force_refresh: bool = False,
        *,
        use_fetch_cache: bool = True,
        fetch_cache_ttl_days: int = 7,
        connect_timeout: float = 5.0,
        read_timeout: float = 10.0,
        max_retries: int = 1,
    ):
        self.delay = delay
        self.force_refresh = force_refresh
        self.use_fetch_cache = use_fetch_cache
        self.fetch_cache_ttl_days = fetch_cache_ttl_days
        self.max_retries = max(0, max_retries)
        timeout = httpx.Timeout(connect=connect_timeout, read=read_timeout, write=read_timeout, pool=connect_timeout)
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=timeout,
        )
        self._last_request = 0.0
        self._run_fetched: dict[str, str | None] = {}
        self._jstats = JurisdictionFetchStats()

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def begin_jurisdiction(self) -> None:
        self._jstats = JurisdictionFetchStats()

    def end_jurisdiction(self) -> JurisdictionFetchStats:
        stats = self._jstats
        self._jstats = JurisdictionFetchStats()
        return stats

    def _wait(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.time()

    def fetch_html(self, url: str, base: str | None = None) -> str | None:
        normalized = normalize_url(url, base)
        if not normalized:
            return None
        if not allowed_by_robots(normalized):
            return None

        if normalized in self._run_fetched:
            self._jstats.cache_hits += 1
            return self._run_fetched[normalized]

        if self.use_fetch_cache and not self.force_refresh:
            cached = get_cached_fetch(normalized, self.fetch_cache_ttl_days)
            if cached and cached.html:
                self._jstats.cache_hits += 1
                self._run_fetched[normalized] = cached.html
                return cached.html

        legacy_path = HTML_CACHE / f"{_cache_key(normalized)}.html"
        if legacy_path.exists() and not self.force_refresh:
            text = legacy_path.read_text(encoding="utf-8", errors="replace")
            self._jstats.cache_hits += 1
            self._run_fetched[normalized] = text
            return text

        self._jstats.cache_misses += 1
        self._wait()
        text: str | None = None
        final_url = normalized
        status_code = 0
        content_type = ""
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.client.get(normalized)
                status_code = resp.status_code
                final_url = normalize_url(str(resp.url)) or normalized
                content_type = resp.headers.get("content-type", "")
                text = _response_html(resp)
                break
            except httpx.TimeoutException:
                self._jstats.timeout_count += 1
                if attempt >= self.max_retries:
                    break
            except httpx.HTTPError:
                self._jstats.fetch_error_count += 1
                if attempt >= self.max_retries:
                    break

        self._run_fetched[normalized] = text
        if text:
            HTML_CACHE.mkdir(parents=True, exist_ok=True)
            legacy_path.write_text(text, encoding="utf-8")
            if self.use_fetch_cache:
                put_cached_fetch(
                    normalized,
                    status_code=status_code,
                    final_url=final_url,
                    content_type=content_type,
                    html=text,
                )
        return text

    def fetch_pdf(self, url: str, max_bytes: int = 5_000_000) -> bytes | None:
        normalized = normalize_url(url)
        if not normalized or not allowed_by_robots(normalized):
            return None
        cache_path = PDF_CACHE / f"{_cache_key(normalized)}.pdf"
        if cache_path.exists() and not self.force_refresh:
            return cache_path.read_bytes()
        self._wait()
        try:
            resp = self.client.get(normalized)
            if resp.status_code != 200:
                return None
            if len(resp.content) > max_bytes:
                return None
            ct = resp.headers.get("content-type", "")
            if "pdf" not in ct and not normalized.lower().endswith(".pdf"):
                return None
            PDF_CACHE.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(resp.content)
            return resp.content
        except httpx.HTTPError:
            self._jstats.fetch_error_count += 1
            return None

    def probe_domain(self, base_url: str) -> list[str]:
        """Try common planning-related paths on a domain."""
        found: list[str] = []
        for path in DOMAIN_PROBE_PATHS:
            url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
            html = self.fetch_html(url)
            if html and len(html) > 500:
                found.append(url)
        return found


def safe_soup(html: str) -> BeautifulSoup | None:
    """Parse HTML; return None when markup breaks the stdlib parser."""
    try:
        return BeautifulSoup(html or "", "html.parser")
    except (ValueError, TypeError):
        return None


def extract_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Return (url, link_text) pairs."""
    soup = safe_soup(html)
    if soup is None:
        return []
    links: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("#") or href.startswith("mailto:"):
            continue
        url = normalize_url(urljoin(base_url, href))
        if not url:
            continue
        text = a.get_text(" ", strip=True)
        links.append((url, text))
    return links


def find_pdf_links(html: str, base_url: str, official_domain: str) -> list[str]:
    pdfs: list[str] = []
    for url, text in extract_links(html, base_url):
        if not url.lower().endswith(".pdf"):
            continue
        if not same_domain(url, official_domain):
            continue
        combined = f"{url} {text}".lower()
        if any(kw in combined for kw in PDF_LINK_KEYWORDS) or "planning" in combined:
            pdfs.append(url)
    return pdfs[:3]


def guess_official_urls(jurisdiction_name: str, state: str) -> list[str]:
    """Generate candidate municipal/county homepage URLs."""
    from src.jurisdiction_utils import jurisdiction_slug, normalize_jurisdiction_name

    display = normalize_jurisdiction_name(jurisdiction_name)
    slug = jurisdiction_slug(jurisdiction_name)
    hyphen = re.sub(r"[^a-z0-9\-]", "", display.lower().replace(" ", "-"))
    state_lower = state.lower()
    is_county = "county" in display.lower()

    if is_county:
        county_slug = slug
        return [
            f"https://www.co.{county_slug}.{state_lower}.gov",
            f"https://www.{county_slug}county.gov",
            f"https://www.{county_slug}-county.{state_lower}.gov",
            f"https://{county_slug}county.gov",
            f"https://www.{county_slug}.{state_lower}.gov",
        ]

    patterns = [
        f"https://www.{slug}{state_lower}.gov",
        f"https://{slug}{state_lower}.gov",
        f"https://www.{hyphen}-{state_lower}.gov",
        f"https://www.{slug}.gov",
        f"https://{slug}.gov",
        f"https://www.{slug}{state_lower}.us",
        f"https://www.{slug}{state_lower}.org",
        f"https://{slug}{state_lower}.org",
        f"https://www.{slug}{state_lower}.com",
        f"https://www.cityof{slug}.gov",
        f"https://cityof{slug}.gov",
        f"https://www.cityof{slug}.org",
        f"https://cityof{slug}.org",
        f"https://www.cityof{slug}.com",
        f"https://cityof{slug}.com",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for p in patterns:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out
