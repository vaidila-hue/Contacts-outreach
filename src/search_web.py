"""Role-family web search via Brave/ddgs."""

from __future__ import annotations

import time

from src.jurisdiction_utils import (
    filter_urls_for_jurisdiction,
    is_blocked_official_url,
    is_parking_or_error_page,
    normalize_jurisdiction_name,
    official_homepage_from_url,
    url_matches_jurisdiction,
)
from src.role_config import (
    MAX_FAST_SEARCH_QUERIES,
    MAX_SEARCH_QUERIES,
    URL_RANK_KEYWORDS,
    county_queries,
    fast_county_queries,
    fast_municipality_queries,
    municipality_queries,
)
from src.search_providers import SearchHit, search_text


def _rank_url(url: str) -> int:
    lower = url.lower()
    score = 0
    if "planning-directory" in lower or "staff-directory" in lower:
        score += 150
    elif "directory" in lower:
        score += 80
    for i, kw in enumerate(URL_RANK_KEYWORDS):
        if kw in lower:
            score += (len(URL_RANK_KEYWORDS) - i) * 10
    from src.fetch_pages import is_gov_url

    if is_gov_url(url):
        score += 5
    for bad in ("news", "press", "faq", "calendar", "event", "camera", "traffic"):
        if bad in lower:
            score -= 20
    return score


def rank_search_results(urls: list[str]) -> list[str]:
    unique = list(dict.fromkeys(urls))
    return sorted(unique, key=_rank_url, reverse=True)


def _search_query_urls(query: str, max_results: int = 5, gov_only: bool = True) -> list[str]:
    hits, _ = search_text(query, max_results=max_results, gov_only=False)
    urls = [h.url for h in hits if h.url]
    if gov_only:
        from src.fetch_pages import is_gov_url
        from urllib.parse import urlparse

        filtered = []
        for u in urls:
            host = urlparse(u).netloc.lower()
            if is_gov_url(u) or host.endswith(".org") or host.endswith(".us"):
                filtered.append(u)
        return filtered
    return urls


def search_planning_pages(
    jurisdiction_name: str,
    state: str,
    geography_type: str,
    county_name: str = "",
    delay: float = 3.0,
) -> tuple[list[str], int]:
    """Run tiered role-family queries; return ranked .gov URLs and query count."""
    display = normalize_jurisdiction_name(jurisdiction_name)
    if geography_type == "county":
        all_queries = county_queries(display)
    else:
        all_queries = municipality_queries(display, state)

    collected: list[str] = []
    queries_run = 0
    tier1_count = 2

    for i, query in enumerate(all_queries):
        if queries_run >= MAX_SEARCH_QUERIES:
            break
        if i >= tier1_count and collected:
            ranked = rank_search_results(collected)
            if ranked and _rank_url(ranked[0]) > 0:
                break
        collected.extend(_search_query_urls(query))
        queries_run += 1
        time.sleep(delay)

    filtered = filter_urls_for_jurisdiction(collected, display, state)
    return rank_search_results(filtered), queries_run


def fast_planning_search(
    jurisdiction_name: str,
    state: str,
    geography_type: str,
    county_name: str = "",
    delay: float = 0.75,
) -> tuple[list[str], list[SearchHit], int]:
    """
    Run 2–3 high-yield email-focused queries; return ranked URLs, raw hits, query count.
    """
    display = normalize_jurisdiction_name(jurisdiction_name)
    if geography_type == "county":
        all_queries = fast_county_queries(display, state)
    else:
        all_queries = fast_municipality_queries(display, state)

    collected: list[str] = []
    all_hits: list[SearchHit] = []
    queries_run = 0

    for query in all_queries[:MAX_FAST_SEARCH_QUERIES]:
        hits, _ = search_text(query, max_results=5, delay=0, gov_only=False)
        all_hits.extend(hits)
        collected.extend(h.url for h in hits if h.url)
        queries_run += 1
        filtered_so_far = filter_urls_for_jurisdiction(collected, display, state)
        if filtered_so_far:
            break

    filtered = filter_urls_for_jurisdiction(collected, display, state)
    return rank_search_results(filtered), all_hits, queries_run


def discover_official_site(
    jurisdiction_name: str,
    state: str,
    geography_type: str,
    fetcher,
    delay: float = 3.0,
    planning_search_urls: list[str] | None = None,
) -> str | None:
    """Try guessed URLs, search results, and planning-search domain roots."""
    from src.fetch_pages import guess_official_urls

    display = normalize_jurisdiction_name(jurisdiction_name)

    for url in guess_official_urls(display, state):
        if is_blocked_official_url(url):
            continue
        if not url_matches_jurisdiction(url, display, state):
            continue
        html = fetcher.fetch_html(url)
        if html and not is_parking_or_error_page(html):
            return url

    if planning_search_urls:
        for url in planning_search_urls:
            if is_blocked_official_url(url):
                continue
            if not url_matches_jurisdiction(url, display, state):
                continue
            home = official_homepage_from_url(url)
            html = fetcher.fetch_html(home)
            if html and not is_parking_or_error_page(html):
                return home
            if url_matches_jurisdiction(home, display, state):
                return home

    query = f'"{display}" "{state}" official website'
    urls = _search_query_urls(query, max_results=5)
    for url in urls:
        if is_blocked_official_url(url):
            continue
        if not url_matches_jurisdiction(url, display, state):
            continue
        html = fetcher.fetch_html(url)
        if html and not is_parking_or_error_page(html):
            return url

    if planning_search_urls:
        for url in planning_search_urls:
            if is_blocked_official_url(url):
                continue
            if url_matches_jurisdiction(url, display, state):
                return official_homepage_from_url(url)

    time.sleep(delay)
    return None
