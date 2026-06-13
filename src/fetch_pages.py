"""HTTP fetch, caching, and robots.txt checks."""

from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from src.fetch_cache import get_cached_fetch, put_cached_fetch
from src.paths import HTML_CACHE, PDF_CACHE, USER_AGENT
from src.role_config import DOMAIN_PROBE_PATHS, PDF_LINK_KEYWORDS
from src.url_utils import normalize_url

_robots_cache: dict[str, RobotFileParser | None] = {}

RETRYABLE_HTTP_STATUS = frozenset({429, 502, 503, 504})
_log = logging.getLogger("contacts.fetch_pages")
_CACHE_KEY_RE = re.compile(r"^[0-9a-f]{16}$")


@dataclass
class FetchFailureRecord:
    url: str
    http_status: int = 0
    error_type: str = ""
    redirect_chain: str = ""
    content_type: str = ""
    rejection_reason: str = ""
    attempts: int = 0


@dataclass
class JurisdictionFetchStats:
    cache_hits: int = 0
    cache_misses: int = 0
    timeout_count: int = 0
    fetch_error_count: int = 0
    fetch_failures: list[FetchFailureRecord] = field(default_factory=list)


@dataclass(frozen=True)
class _FetchProfileSettings:
    connect_timeout: float
    read_timeout: float
    max_retries: int
    retry_backoff_seconds: float


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _safe_cache_stem(normalized_url: str) -> str:
    key = _cache_key(normalized_url)
    if _CACHE_KEY_RE.fullmatch(key):
        return key
    return hashlib.sha256(normalized_url.encode("utf-8", errors="replace")).hexdigest()[:16]


def _legacy_html_cache_path(normalized_url: str) -> Path:
    return HTML_CACHE / f"{_safe_cache_stem(normalized_url)}.html"


def _pdf_cache_path(normalized_url: str) -> Path:
    return PDF_CACHE / f"{_safe_cache_stem(normalized_url)}.pdf"


def _read_legacy_html_cache(cache_path: Path, url: str) -> str | None:
    try:
        if not cache_path.is_file():
            return None
        return cache_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _log.warning(
            "Skipping unreadable HTML cache for %s (%s): %s",
            url,
            cache_path,
            exc,
        )
        return None


def _write_legacy_html_cache(cache_path: Path, url: str, text: str) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        _log.warning(
            "HTML cache write failed for %s (%s): %s",
            url,
            cache_path,
            exc,
        )


def _read_pdf_cache(cache_path: Path, url: str) -> bytes | None:
    try:
        if not cache_path.is_file():
            return None
        return cache_path.read_bytes()
    except OSError as exc:
        _log.warning(
            "Skipping unreadable PDF cache for %s (%s): %s",
            url,
            cache_path,
            exc,
        )
        return None


def _write_pdf_cache(cache_path: Path, url: str, data: bytes) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)
    except OSError as exc:
        _log.warning(
            "PDF cache write failed for %s (%s): %s",
            url,
            cache_path,
            exc,
        )


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


def is_municipal_url(url: str) -> bool:
    """True for common official municipal TLDs (.gov, .org, .us)."""
    host = urlparse(url).netloc.lower()
    return host.endswith((".gov", ".org", ".us"))


def _redirect_chain(resp: httpx.Response) -> str:
    chain = [str(r.url) for r in resp.history]
    chain.append(str(resp.url))
    return " -> ".join(chain)


def _response_html(resp: httpx.Response) -> tuple[str | None, str]:
    """Return (html or None, rejection_reason)."""
    content_type = resp.headers.get("content-type", "")
    if resp.status_code == 200:
        pass
    elif resp.status_code == 403 and len(resp.text) > 2000:
        lower = resp.text.lower()
        if "just a moment" in lower or "403 - forbidden" in lower[:500]:
            return None, "blocked_403_challenge"
    elif resp.status_code in RETRYABLE_HTTP_STATUS:
        return None, f"retryable_http_{resp.status_code}"
    else:
        return None, f"http_{resp.status_code}"
    if "html" not in content_type and "text" not in content_type:
        return None, f"not_html:{content_type or 'unknown'}"
    if not resp.text.strip():
        return None, "empty_body"
    return resp.text, ""


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
        planning_connect_timeout: float = 8.0,
        planning_read_timeout: float = 20.0,
        planning_max_retries: int = 3,
    ):
        self.delay = delay
        self.force_refresh = force_refresh
        self.use_fetch_cache = use_fetch_cache
        self.fetch_cache_ttl_days = fetch_cache_ttl_days
        self._profiles = {
            "default": _FetchProfileSettings(
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                max_retries=max(0, max_retries),
                retry_backoff_seconds=1.0,
            ),
            "planning": _FetchProfileSettings(
                connect_timeout=planning_connect_timeout,
                read_timeout=planning_read_timeout,
                max_retries=max(0, planning_max_retries),
                retry_backoff_seconds=1.5,
            ),
        }
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=httpx.Timeout(connect=connect_timeout, read=read_timeout, write=read_timeout, pool=connect_timeout),
        )
        self._last_request = 0.0
        self._run_fetched: dict[str, str] = {}
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

    def fetch_failures(self) -> list[FetchFailureRecord]:
        return list(self._jstats.fetch_failures)

    def _profile_settings(self, profile: str) -> _FetchProfileSettings:
        return self._profiles.get(profile, self._profiles["default"])

    def _run_cache_key(self, normalized: str, profile: str) -> str:
        return f"{normalized}|{profile}"

    def _wait(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.time()

    def _record_failure(
        self,
        *,
        url: str,
        http_status: int,
        error_type: str,
        redirect_chain: str,
        content_type: str,
        rejection_reason: str,
        attempts: int,
    ) -> None:
        self._jstats.fetch_failures.append(
            FetchFailureRecord(
                url=url,
                http_status=http_status,
                error_type=error_type,
                redirect_chain=redirect_chain,
                content_type=content_type,
                rejection_reason=rejection_reason,
                attempts=attempts,
            )
        )

    def fetch_html(
        self,
        url: str,
        base: str | None = None,
        *,
        profile: str = "default",
    ) -> str | None:
        normalized = normalize_url(url, base)
        if not normalized:
            return None
        if not allowed_by_robots(normalized):
            self._record_failure(
                url=normalized,
                http_status=0,
                error_type="robots_denied",
                redirect_chain="",
                content_type="",
                rejection_reason="robots_txt_disallow",
                attempts=0,
            )
            return None

        cache_key = self._run_cache_key(normalized, profile)
        if cache_key in self._run_fetched:
            self._jstats.cache_hits += 1
            return self._run_fetched[cache_key]

        if self.use_fetch_cache and not self.force_refresh:
            cached = get_cached_fetch(normalized, self.fetch_cache_ttl_days)
            if cached and cached.html:
                self._jstats.cache_hits += 1
                self._run_fetched[cache_key] = cached.html
                return cached.html

        legacy_path = _legacy_html_cache_path(normalized)
        if not self.force_refresh:
            cached_text = _read_legacy_html_cache(legacy_path, normalized)
            if cached_text is not None:
                self._jstats.cache_hits += 1
                self._run_fetched[cache_key] = cached_text
                return cached_text

        settings = self._profile_settings(profile)
        timeout = httpx.Timeout(
            connect=settings.connect_timeout,
            read=settings.read_timeout,
            write=settings.read_timeout,
            pool=settings.connect_timeout,
        )

        self._jstats.cache_misses += 1
        text: str | None = None
        final_url = normalized
        status_code = 0
        content_type = ""
        redirect_chain = ""
        last_rejection = ""
        last_error_type = ""
        attempts = 0

        for attempt in range(settings.max_retries + 1):
            attempts = attempt + 1
            if attempt > 0:
                backoff = settings.retry_backoff_seconds * attempt
                time.sleep(min(backoff, 8.0))
            self._wait()
            try:
                resp = self.client.get(normalized, timeout=timeout)
                status_code = resp.status_code
                try:
                    final_url = normalize_url(str(resp.url)) or normalized
                except RuntimeError:
                    final_url = normalized
                content_type = resp.headers.get("content-type", "")
                try:
                    redirect_chain = _redirect_chain(resp)
                except RuntimeError:
                    redirect_chain = normalized
                text, last_rejection = _response_html(resp)
                if text:
                    break
                if status_code in RETRYABLE_HTTP_STATUS and attempt < settings.max_retries:
                    last_error_type = "rate_limit" if status_code == 429 else "transient_http"
                    retry_after = resp.headers.get("retry-after", "")
                    if retry_after.isdigit():
                        time.sleep(min(float(retry_after), 10.0))
                    continue
                last_error_type = "http_error"
                break
            except httpx.TimeoutException:
                self._jstats.timeout_count += 1
                last_error_type = "timeout"
                last_rejection = "timeout"
                if attempt >= settings.max_retries:
                    break
            except httpx.HTTPError as exc:
                self._jstats.fetch_error_count += 1
                last_error_type = "connection_error"
                last_rejection = exc.__class__.__name__
                if attempt >= settings.max_retries:
                    break

        if text:
            self._run_fetched[cache_key] = text
            _write_legacy_html_cache(legacy_path, normalized, text)
            if self.use_fetch_cache:
                put_cached_fetch(
                    normalized,
                    status_code=status_code,
                    final_url=final_url,
                    content_type=content_type,
                    html=text,
                )
            return text

        self._record_failure(
            url=normalized,
            http_status=status_code,
            error_type=last_error_type or "fetch_failed",
            redirect_chain=redirect_chain,
            content_type=content_type,
            rejection_reason=last_rejection or "unknown",
            attempts=attempts,
        )
        return None

    def fetch_pdf(self, url: str, max_bytes: int = 5_000_000) -> bytes | None:
        normalized = normalize_url(url)
        if not normalized or not allowed_by_robots(normalized):
            return None
        cache_path = _pdf_cache_path(normalized)
        if not self.force_refresh:
            cached_pdf = _read_pdf_cache(cache_path, normalized)
            if cached_pdf is not None:
                return cached_pdf
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
            _write_pdf_cache(cache_path, normalized, resp.content)
            return resp.content
        except httpx.HTTPError:
            self._jstats.fetch_error_count += 1
            return None

    def probe_domain(self, base_url: str) -> list[str]:
        """Try common planning-related paths on a domain."""
        found: list[str] = []
        for path in DOMAIN_PROBE_PATHS:
            url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
            html = self.fetch_html(url, profile="planning")
            if html and len(html) > 500:
                found.append(url)
        return found


def format_fetch_failures(failures: list[FetchFailureRecord], *, limit: int = 8) -> str:
    """Compact diagnostics string for CSV/JSON."""
    parts: list[str] = []
    for rec in failures[:limit]:
        parts.append(
            f"{rec.url}|status={rec.http_status}|err={rec.error_type}|reason={rec.rejection_reason}"
        )
    if len(failures) > limit:
        parts.append(f"...+{len(failures) - limit} more")
    return "; ".join(parts)


def fetch_profile_for_page_kind(page_kind: str) -> str:
    """Return fetch profile name for a crawl page kind."""
    if page_kind in ("manual", "planning", "directory"):
        return "planning"
    return "default"


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
        f"https://www.cityof{slug}.org",
        f"https://cityof{slug}.org",
        f"https://www.cityof{slug}.gov",
        f"https://cityof{slug}.gov",
        f"https://www.{slug}city.org",
        f"https://{slug}city.org",
        f"https://www.{slug}{state_lower}.gov",
        f"https://{slug}{state_lower}.gov",
        f"https://www.{slug}{state_lower}.org",
        f"https://{slug}{state_lower}.org",
        f"https://www.{hyphen}-{state_lower}.gov",
        f"https://www.{slug}.gov",
        f"https://{slug}.gov",
        f"https://www.{slug}.org",
        f"https://{slug}.org",
        f"https://www.{slug}{state_lower}.us",
        f"https://www.{slug}{state_lower}.com",
        f"https://cityof{slug}.com",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for p in patterns:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out
