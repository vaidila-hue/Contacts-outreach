"""Unified web search: Brave API (optional) with ddgs fallback."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from src.fetch_pages import is_gov_url

BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"

DDGS_INSTALL_MSG = (
    "DDGS search provider unavailable: install dependencies with "
    "pip install -r requirements.txt"
)


class SearchProviderError(RuntimeError):
    """DDGS or Brave search failed for a specific query."""


@dataclass
class SearchHit:
    url: str
    title: str
    snippet: str
    provider: str


@dataclass
class FilteredSearchResult:
    hit: SearchHit
    accepted: bool
    reason: str


@dataclass
class SearchDiagnostics:
    query: str
    provider: str
    raw_count: int = 0
    hits: list[SearchHit] = field(default_factory=list)
    filtered: list[FilteredSearchResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


_search_errors: list[str] = []


def consume_search_errors() -> list[str]:
    """Return and clear accumulated search provider errors."""
    errors = list(_search_errors)
    _search_errors.clear()
    return errors


def peek_search_errors() -> list[str]:
    return list(_search_errors)


def _record_search_error(message: str) -> None:
    _search_errors.append(message)


def brave_api_configured() -> bool:
    return bool(os.environ.get("BRAVE_SEARCH_API_KEY", "").strip())


def active_search_provider() -> str:
    if brave_api_configured():
        return "brave"
    return "ddgs"


def _is_municipal_site(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host.endswith(".gov") or host.endswith(".org") or host.endswith(".us")


def _brave_search(query: str, max_results: int = 5) -> list[SearchHit]:
    key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not key:
        return []
    try:
        resp = httpx.get(
            BRAVE_API_URL,
            params={"q": query, "count": max_results},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        msg = f"Brave search failed for query={query!r}: {type(exc).__name__}: {exc}"
        _record_search_error(msg)
        return []
    hits: list[SearchHit] = []
    for item in data.get("web", {}).get("results", []):
        url = item.get("url") or ""
        if not url:
            continue
        hits.append(
            SearchHit(
                url=url,
                title=item.get("title") or "",
                snippet=item.get("description") or "",
                provider="brave",
            )
        )
    return hits[:max_results]


def _ddgs_search(query: str, max_results: int = 5) -> list[SearchHit]:
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise ImportError(DDGS_INSTALL_MSG) from exc

    try:
        results = DDGS().text(query, max_results=max_results)
    except Exception as exc:
        msg = f"DDGS search failed for query={query!r}: {type(exc).__name__}: {exc}"
        _record_search_error(msg)
        raise SearchProviderError(msg) from exc

    hits: list[SearchHit] = []
    for r in results:
        url = r.get("href") or r.get("link") or ""
        if not url:
            continue
        hits.append(
            SearchHit(
                url=url,
                title=r.get("title") or "",
                snippet=r.get("body") or r.get("snippet") or "",
                provider="ddgs",
            )
        )
    return hits[:max_results]


def search_text(
    query: str,
    max_results: int = 5,
    delay: float = 0,
    gov_only: bool = False,
) -> tuple[list[SearchHit], str]:
    """Return hits and provider name used."""
    hits: list[SearchHit] = []
    provider = active_search_provider()
    if provider == "brave":
        hits = _brave_search(query, max_results)
    if not hits:
        provider = "ddgs"
        try:
            hits = _ddgs_search(query, max_results)
        except ImportError:
            raise
        except SearchProviderError:
            hits = []
    if delay:
        time.sleep(delay)
    if gov_only:
        hits = [
            h
            for h in hits
            if is_gov_url(h.url) or _is_municipal_site(h.url)
        ]
    return hits, provider


def filter_hit_for_jurisdiction(
    hit: SearchHit,
    jurisdiction_name: str,
    state: str,
    gov_only: bool = False,
    geography_type: str = "city",
) -> FilteredSearchResult:
    from src.site_discovery import classify_search_rejection

    if not hit.url:
        return FilteredSearchResult(hit, False, "empty_url")
    if gov_only:
        from src.fetch_pages import is_municipal_url

        if not is_municipal_url(hit.url):
            return FilteredSearchResult(hit, False, "unsupported_domain_pattern")
    accepted, reason = classify_search_rejection(
        hit, jurisdiction_name, state, geography_type, planning_context=False
    )
    return FilteredSearchResult(hit, accepted, reason)


def diagnose_search(
    query: str,
    jurisdiction_name: str,
    state: str,
    max_results: int = 5,
    gov_only: bool = False,
) -> SearchDiagnostics:
    consume_search_errors()
    hits, provider = search_text(query, max_results=max_results, gov_only=False)
    diag = SearchDiagnostics(
        query=query,
        provider=provider,
        raw_count=len(hits),
        hits=hits,
        errors=consume_search_errors(),
    )
    for hit in hits:
        diag.filtered.append(
            filter_hit_for_jurisdiction(hit, jurisdiction_name, state, gov_only=gov_only)
        )
    return diag


def search_urls(
    query: str,
    jurisdiction_name: str,
    state: str,
    max_results: int = 5,
    delay: float = 0,
    gov_only: bool = True,
) -> list[str]:
    """Search and return jurisdiction-valid URLs."""
    hits, _ = search_text(query, max_results=max_results, delay=delay, gov_only=False)
    urls: list[str] = []
    for hit in hits:
        fr = filter_hit_for_jurisdiction(hit, jurisdiction_name, state, gov_only=gov_only)
        if fr.accepted:
            urls.append(hit.url)
    return urls
