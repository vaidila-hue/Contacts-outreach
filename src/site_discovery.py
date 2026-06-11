"""Official-site and planning-department discovery with multi-query search."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import urlparse

from src.census_seed import Jurisdiction
from src.fetch_pages import PageFetcher, guess_official_urls, is_municipal_url
from src.harvest_config import HarvestConfig
from src.jurisdiction_utils import (
    is_blocked_official_url,
    is_parking_or_error_page,
    jurisdiction_slug,
    normalize_jurisdiction_name,
    official_homepage_from_url,
    url_matches_jurisdiction,
)
from src.search_providers import SearchHit, search_text
from src.staff_discovery import classify_page_url, official_netloc
from src.url_utils import normalize_url

MAX_GUESS_ATTEMPTS = 10

PLANNING_PATH_KEYWORDS: tuple[str, ...] = (
    "planning",
    "community-development",
    "community development",
    "development-services",
    "development services",
    "planning-division",
    "planning division",
    "zoning",
    "land-use",
    "land use",
)

SOCIAL_MEDIA_HOSTS: tuple[str, ...] = (
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "instagram.com",
    "youtube.com",
    "tiktok.com",
)

THIRD_PARTY_DIRECTORY_HOSTS: tuple[str, ...] = (
    "wikipedia.org",
    "wikidata.org",
    "yellowpages.com",
    "yelp.com",
    "mapquest.com",
    "municipalcodeonline.com",
    "usnews.com",
    "niche.com",
    "bestplaces.net",
)

CHAMBER_TOURISM_FRAGMENTS: tuple[str, ...] = (
    "chamber",
    "visit",
    "tourism",
    "convention",
    "visitor",
    "travel",
)

SCHOOL_FRAGMENTS: tuple[str, ...] = (
    ".edu",
    "k12.",
    "schools.",
    "schooldistrict",
    "unified.org",
)


@dataclass
class UrlEvaluation:
    url: str
    title: str
    snippet: str
    query: str
    accepted: bool
    reason: str


@dataclass
class QueryTrace:
    query: str
    provider: str
    raw_count: int
    evaluations: list[UrlEvaluation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class SiteResolutionResult:
    official_url: str | None = None
    planning_fallback_url: str | None = None
    resolver_method: str = ""
    search_queries_run: int = 0
    search_results_seen: int = 0
    search_results_rejected: int = 0
    guess_attempts: int = 0
    query_traces: list[QueryTrace] = field(default_factory=list)


@dataclass
class DiscoveryReport:
    jurisdiction_name: str
    state: str
    geography_type: str
    resolution: SiteResolutionResult
    official_domain: str = ""
    planning_pages_found: int = 0
    pages_fetched: int = 0
    final_outcome: str = ""
    guess_urls_tried: list[str] = field(default_factory=list)


def official_site_search_queries(
    jurisdiction_name: str,
    state: str,
    geography_type: str = "city",
) -> list[str]:
    display = normalize_jurisdiction_name(jurisdiction_name)
    st = state.upper()
    queries = [
        f'"{display}" "{st}" official website',
        f'"{display}" "{st}" city official website',
        f'"{display}" "{st}" planning department',
        f'"{display}" "{st}" community development',
        f'"{display}" "{st}" planning division',
        f'"{display}" "{st}" planning staff',
    ]
    if geography_type == "county" or "county" in display.lower():
        queries.extend(
            [
                f'"{display}" "{st}" county planning department',
                f'"{display}" "{st}" county community development',
            ]
        )
    return queries


def planning_department_search_queries(
    jurisdiction_name: str,
    state: str,
    geography_type: str = "city",
) -> list[str]:
    display = normalize_jurisdiction_name(jurisdiction_name)
    st = state.upper()
    queries = [
        f'"{display}" "{st}" planning department',
        f'"{display}" "{st}" community development',
        f'"{display}" "{st}" planning division',
        f'"{display}" "{st}" planning staff',
    ]
    if geography_type == "county" or "county" in display.lower():
        queries.extend(
            [
                f'"{display}" "{st}" county planning department',
                f'"{display}" "{st}" county community development',
            ]
        )
    return queries


def _host(url: str) -> str:
    return urlparse(url).netloc.lower()


def _combined_text(hit: SearchHit) -> str:
    return f"{hit.title} {hit.snippet} {hit.url}".lower()


def _slug_in_text(slug: str, text: str) -> bool:
    if not slug:
        return False
    compact = text.replace(".", "").replace("-", "").replace(" ", "")
    return slug in compact or f"cityof{slug}" in compact or f"{slug}city" in compact


def matches_municipal_domain_pattern(url: str, jurisdiction_name: str, state: str) -> bool:
    """True when host matches common municipal naming patterns."""
    if not url:
        return False
    host = _host(url).lstrip("www.")
    slug = jurisdiction_slug(jurisdiction_name)
    state_lower = state.lower()
    if not slug:
        return is_municipal_url(url)

    patterns = (
        f"cityof{slug}.org",
        f"cityof{slug}.gov",
        f"{slug}city.org",
        f"{slug}{state_lower}.gov",
        f"{slug}{state_lower}.org",
        f"{slug}.gov",
        f"{slug}.org",
        f"www.{slug}.gov",
        f"www.{slug}.org",
    )
    if host in patterns or host.lstrip("www.") in patterns:
        return True
    compact = host.replace(".", "").replace("-", "")
    if f"cityof{slug}" in compact:
        return True
    if f"{slug}{state_lower}" in compact:
        return True
    if slug in compact and host.endswith((".gov", ".org", ".us")):
        return True
    return is_municipal_url(url)


def is_planning_department_url(url: str) -> bool:
    lower = url.lower()
    if classify_page_url(url) == "planning":
        return True
    return any(kw.replace(" ", "-") in lower or kw.replace("-", " ") in lower for kw in PLANNING_PATH_KEYWORDS)


def is_civic_vendor_host(host: str) -> bool:
    lower = host.lower()
    return any(
        frag in lower
        for frag in (
            "civicplus",
            "granicus",
            "revize",
            "municipalonline",
            "egov",
            "cms9",
        )
    )


def classify_search_rejection(
    hit: SearchHit,
    jurisdiction_name: str,
    state: str,
    geography_type: str = "city",
    *,
    planning_context: bool = False,
) -> tuple[bool, str]:
    """Return (accepted, reason). Reason is empty when accepted."""
    url = (hit.url or "").strip()
    if not url:
        return False, "empty_url"
    if is_blocked_official_url(url):
        return False, "blocked_url"

    host = _host(url)
    text = _combined_text(hit)
    slug = jurisdiction_slug(jurisdiction_name)
    display = normalize_jurisdiction_name(jurisdiction_name).lower()

    if any(s in host for s in SOCIAL_MEDIA_HOSTS):
        return False, "social_media"
    if any(s in host for s in THIRD_PARTY_DIRECTORY_HOSTS):
        return False, "third_party_directory"
    if any(frag in text or frag in host for frag in SCHOOL_FRAGMENTS):
        return False, "school_domain"
    if any(frag in text or frag in host for frag in CHAMBER_TOURISM_FRAGMENTS):
        return False, "chamber/tourism"

    from src.jurisdiction_validation import host_implies_wrong_state

    if host_implies_wrong_state(host, state):
        return False, "wrong_state"

    is_county = geography_type == "county" or "county" in display
    if not is_county and "county" in host and f"{slug}county" not in host.replace(".", ""):
        if slug and slug not in host.replace(".", ""):
            return False, "county_when_city_requested"

    if planning_context and is_planning_department_url(url):
        if url_matches_jurisdiction(url, jurisdiction_name, state):
            return True, "accepted"
        if slug and _slug_in_text(slug, text) and is_municipal_url(url):
            return True, "accepted"

    if not is_municipal_url(url) and not is_civic_vendor_host(host):
        return False, "unsupported_domain_pattern"

    if is_civic_vendor_host(host):
        if slug and _slug_in_text(slug, text):
            return True, "accepted"
        return False, "title_mismatch"

    if slug and len(slug) >= 4 and not _slug_in_text(slug, text) and slug not in host.replace(".", ""):
        if not url_matches_jurisdiction(url, jurisdiction_name, state):
            return False, "wrong_jurisdiction"

    if not url_matches_jurisdiction(url, jurisdiction_name, state):
        return False, "content_mismatch"

    if not planning_context and not matches_municipal_domain_pattern(url, jurisdiction_name, state):
        if slug in host.replace(".", "") or f"cityof{slug}" in host.replace(".", ""):
            pass
        elif not url_matches_jurisdiction(url, jurisdiction_name, state):
            return False, "unsupported_domain_pattern"

    return True, "accepted"


def _evaluate_hits(
    hits: list[SearchHit],
    query: str,
    jurisdiction_name: str,
    state: str,
    geography_type: str,
    *,
    planning_context: bool = False,
) -> list[UrlEvaluation]:
    out: list[UrlEvaluation] = []
    for hit in hits:
        accepted, reason = classify_search_rejection(
            hit,
            jurisdiction_name,
            state,
            geography_type,
            planning_context=planning_context,
        )
        out.append(
            UrlEvaluation(
                url=hit.url,
                title=hit.title,
                snippet=hit.snippet,
                query=query,
                accepted=accepted,
                reason=reason if not accepted else "accepted",
            )
        )
    return out


def _try_guess_official(j: Jurisdiction, fetcher: PageFetcher, report: SiteResolutionResult) -> str | None:
    for url in guess_official_urls(j.jurisdiction_name, j.state)[:MAX_GUESS_ATTEMPTS]:
        report.guess_attempts += 1
        if is_blocked_official_url(url):
            continue
        if not url_matches_jurisdiction(url, j.jurisdiction_name, j.state):
            continue
        html = fetcher.fetch_html(url)
        if html and not is_parking_or_error_page(html):
            return url
    return None


def _run_search_queries(
    queries: list[str],
    j: Jurisdiction,
    fetcher: PageFetcher,
    report: SiteResolutionResult,
    config: HarvestConfig,
    *,
    planning_context: bool = False,
    fetch_homepage: bool = True,
) -> tuple[str | None, str | None]:
    """Return (official_url, planning_url) from search."""
    official: str | None = None
    planning: str | None = None

    for query in queries:
        if report.search_queries_run >= config.max_search_queries_per_jurisdiction:
            break
        hits, provider = search_text(query, max_results=5, delay=0, gov_only=False)
        report.search_queries_run += 1
        report.search_results_seen += len(hits)
        evaluations = _evaluate_hits(
            hits,
            query,
            j.jurisdiction_name,
            j.state,
            j.geography_type,
            planning_context=planning_context,
        )
        trace = QueryTrace(query=query, provider=provider, raw_count=len(hits))
        trace.evaluations = evaluations
        report.query_traces.append(trace)

        for ev in evaluations:
            if ev.accepted:
                continue
            report.search_results_rejected += 1

        for ev, hit in zip(evaluations, hits):
            if not ev.accepted:
                continue
            url = hit.url
            if is_planning_department_url(url):
                html = fetcher.fetch_html(url)
                planning = url
                official = official_homepage_from_url(url)
                if html and not is_parking_or_error_page(html):
                    break
                # Accepted planning page — infer domain and crawl from it even if fetch failed here.
                break
            if fetch_homepage:
                html = fetcher.fetch_html(url)
                if html and not is_parking_or_error_page(html):
                    official = url
                    break
                home = official_homepage_from_url(url)
                if normalize_url(home) != normalize_url(url):
                    home_html = fetcher.fetch_html(home)
                    if home_html and not is_parking_or_error_page(home_html):
                        official = home
                        break
        if official or planning:
            break
    return official, planning


def resolve_official_site(
    j: Jurisdiction,
    fetcher: PageFetcher,
    config: HarvestConfig,
    *,
    manual_official: str | None = None,
    skip_guess: bool = False,
) -> SiteResolutionResult:
    """Multi-query official resolution with planning-department fallback."""
    report = SiteResolutionResult()

    if manual_official:
        report.official_url = manual_official
        report.resolver_method = "manual"
        return report

    if not skip_guess:
        guessed = _try_guess_official(j, fetcher, report)
        if guessed:
            report.official_url = guessed
            report.resolver_method = "guess"
            return report

    official_queries = official_site_search_queries(
        j.jurisdiction_name, j.state, j.geography_type
    )
    official, planning = _run_search_queries(
        official_queries,
        j,
        fetcher,
        report,
        config,
        planning_context=False,
        fetch_homepage=True,
    )
    if official or planning:
        report.official_url = official or (official_homepage_from_url(planning) if planning else None)
        if planning:
            report.planning_fallback_url = planning
            report.resolver_method = "planning_search_fallback"
        else:
            report.resolver_method = "search_official"
        return report

    if report.search_queries_run >= config.max_search_queries_per_jurisdiction:
        return report

    planning_queries = planning_department_search_queries(
        j.jurisdiction_name, j.state, j.geography_type
    )
    _, planning = _run_search_queries(
        planning_queries,
        j,
        fetcher,
        report,
        config,
        planning_context=True,
        fetch_homepage=False,
    )
    if planning:
        report.planning_fallback_url = planning
        if not report.official_url:
            report.official_url = official_homepage_from_url(planning)
        report.resolver_method = "planning_search_fallback"
    return report


def diagnose_discovery(
    jurisdiction_name: str,
    state: str,
    geography_type: str = "city",
    population: int = 0,
    *,
    fetcher: PageFetcher | None = None,
    config: HarvestConfig | None = None,
) -> DiscoveryReport:
    """Full discovery trace for CLI diagnostics (no domain cache)."""
    from src.fetch_pages import PageFetcher as PF

    j = Jurisdiction(state=state.upper(), jurisdiction_name=jurisdiction_name, geography_type=geography_type, population=population)
    fetcher = fetcher or PF(use_fetch_cache=False)
    config = config or HarvestConfig(
        max_search_queries_per_jurisdiction=12,
        use_fetch_cache=False,
        use_domain_cache=False,
    )

    report = SiteResolutionResult()
    guess_urls = guess_official_urls(j.jurisdiction_name, j.state)[:MAX_GUESS_ATTEMPTS]
    official = _try_guess_official(j, fetcher, report)
    if official:
        report.official_url = official
        report.resolver_method = "guess"
    else:
        official_queries = official_site_search_queries(j.jurisdiction_name, j.state, j.geography_type)
        off, _ = _run_search_queries(
            official_queries, j, fetcher, report, config, planning_context=False
        )
        if off:
            report.official_url = off
            report.resolver_method = "search_official"
        else:
            plan_queries = planning_department_search_queries(j.jurisdiction_name, j.state, j.geography_type)
            _, planning = _run_search_queries(
                plan_queries, j, fetcher, report, config, planning_context=True, fetch_homepage=False
            )
            if planning:
                report.planning_fallback_url = planning
                report.official_url = official_homepage_from_url(planning)
                report.resolver_method = "planning_search_fallback"

    pages_fetched = report.guess_attempts + report.search_queries_run
    planning_found = 1 if report.planning_fallback_url else 0
    official_domain = official_netloc(report.official_url) if report.official_url else ""

    if report.official_url or report.planning_fallback_url:
        outcome = report.resolver_method or "resolved"
    else:
        outcome = "no_official_site_found"

    return DiscoveryReport(
        jurisdiction_name=jurisdiction_name,
        state=state.upper(),
        geography_type=geography_type,
        resolution=report,
        official_domain=official_domain,
        planning_pages_found=planning_found,
        pages_fetched=pages_fetched,
        final_outcome=outcome,
        guess_urls_tried=guess_urls,
    )


def format_discovery_report(report: DiscoveryReport) -> str:
    lines: list[str] = []
    r = report.resolution
    lines.append(f"=== Discovery: {report.jurisdiction_name}, {report.state} ({report.geography_type}) ===")
    lines.append("")
    lines.append("Guess URLs tried (in order):")
    for url in report.guess_urls_tried:
        lines.append(f"  - {url}")
    lines.append("")
    lines.append("Search queries:")
    for trace in r.query_traces:
        lines.append(f'  Query: "{trace.query}"')
        lines.append(f"  Provider: {trace.provider} | Raw results: {trace.raw_count}")
        if not trace.evaluations:
            lines.append("  (no results)")
        for i, ev in enumerate(trace.evaluations, 1):
            status = "ACCEPT" if ev.accepted else "REJECT"
            lines.append(f"  [{i}] {status} ({ev.reason})")
            lines.append(f"      URL: {ev.url}")
            if ev.title:
                lines.append(f"      Title: {ev.title[:120]}")
        lines.append("")
    lines.append(f"Search queries run: {r.search_queries_run}")
    lines.append(f"Search results seen: {r.search_results_seen}")
    lines.append(f"Search results rejected: {r.search_results_rejected}")
    lines.append(f"Resolver method: {r.resolver_method or '(none)'}")
    lines.append(f"Official domain: {report.official_domain or '(none)'}")
    if r.official_url:
        lines.append(f"Official URL: {r.official_url}")
    if r.planning_fallback_url:
        lines.append(f"Planning fallback URL: {r.planning_fallback_url}")
        lines.append(f"Planning fallback used: yes")
    else:
        lines.append("Planning fallback used: no")
    lines.append(f"Planning pages found: {report.planning_pages_found}")
    lines.append(f"Pages fetched (approx): {report.pages_fetched}")
    lines.append(f"Final outcome: {report.final_outcome}")
    return "\n".join(lines)


def rejection_summary_json(report: SiteResolutionResult) -> str:
    """Compact JSON of rejected URLs for diagnostics CSV."""
    rejected = []
    for trace in report.query_traces:
        for ev in trace.evaluations:
            if not ev.accepted:
                rejected.append({"url": ev.url, "reason": ev.reason, "query": ev.query})
    return json.dumps(rejected[:20], ensure_ascii=False)
