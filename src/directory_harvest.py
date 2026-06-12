"""Official-site-first directory harvest (default discovery strategy)."""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

from src.build_mode import BuildStats
from src.census_seed import Jurisdiction
from src.discover_common import (
    DiscoverDiagnostics,
    RI_COUNTY_NOTE,
    reject_row,
    working_row_from_contact,
)
from src.domain_cache import load_domain_cache, lookup_domain_cache, save_domain_cache_entry
from src.extract_contacts import (
    ContactCandidate,
    count_mailto_links,
    extract_contacts_from_html,
    extract_profile_followups,
    is_high_confidence_contact,
    page_warrants_extraction,
    recover_orphan_email_candidates,
    select_best_contact,
)
from src.extract_emails import classify_email, extract_emails_from_text, is_generic_email
from src.fetch_pages import PageFetcher, fetch_profile_for_page_kind, format_fetch_failures
from src.harvest_config import HarvestConfig
from src.jurisdiction_validation import validate_jurisdiction_match
from src.manual_urls import ManualUrlEntry
from src.role_config import matches_allowlisted_title
from src.site_discovery import resolve_official_site
from src.staff_discovery import (
    classify_page_url,
    crawl_priority,
    discover_internal_staff_urls,
    official_netloc,
    url_crawl_kind,
)
from src.url_utils import normalize_url

HARVEST_PROBE_PATHS: tuple[str, ...] = (
    "/planning",
    "/departments/planning",
    "/planning-and-zoning",
    "/community-development",
    "/development-services",
    "/staff",
    "/directory",
    "/Directory.aspx",
    "/departments",
    "/contact",
    "/zoning",
    "/land-use",
)

MAX_PLANNING_PAGE_FETCHES = 5

GEOGRAPHY_PROCESS_ORDER: dict[str, int] = {
    "city": 0,
    "town": 1,
    "village": 2,
    "borough": 3,
    "township": 4,
    "county": 5,
}


def sort_jurisdictions_for_harvest(
    jurisdictions: list[Jurisdiction],
    *,
    include_counties: bool = False,
) -> list[Jurisdiction]:
    filtered = jurisdictions
    if not include_counties:
        filtered = [j for j in jurisdictions if j.geography_type != "county"]
    return sorted(
        filtered,
        key=lambda j: (
            GEOGRAPHY_PROCESS_ORDER.get(j.geography_type, 9),
            -j.population,
            j.state,
            j.jurisdiction_name,
        ),
    )


@dataclass
class HarvestDiagnostics:
    official_domain: str = ""
    official_site_found: bool = False
    planning_page_found: bool = False
    planning_pages_found: int = 0
    directory_pages_found: int = 0
    staff_links_found: int = 0
    profile_links_followed: int = 0
    profile_pages_fetched: int = 0
    mailto_links_found: int = 0
    emails_found: int = 0
    candidate_titles_found: int = 0
    pages_fetched_count: int = 0
    search_queries_run: int = 0
    search_urls_found: int = 0
    manual_url_used: str = ""
    manual_url_result: str = ""
    final_rejection_reason: str = ""
    raw_emails: list[str] = field(default_factory=list)
    generic_emails: list[str] = field(default_factory=list)
    direct_email_candidates_count: int = 0
    elapsed_seconds: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    early_stop: str = "no"
    max_page_limit_hit: str = "no"
    timeout_count: int = 0
    fetch_error_count: int = 0
    resolver_method: str = ""
    search_results_seen: int = 0
    search_results_rejected: int = 0
    planning_fallback_used: str = "no"
    planning_fallback_url: str = ""
    planning_fallback_attempted: str = "no"
    planning_fallback_success: str = "no"
    fetch_failures_by_url: str = ""
    orphan_emails_found: int = 0
    orphan_emails_promoted: int = 0
    candidate_pairing_failures: int = 0


def diagnostics_row(
    j: Jurisdiction,
    hdiag: HarvestDiagnostics,
    *,
    found: bool,
) -> dict[str, str]:
    return {
        "state": j.state,
        "jurisdiction_name": j.jurisdiction_name,
        "geography_type": j.geography_type,
        "population": str(j.population),
        "official_domain": hdiag.official_domain,
        "planning_pages_found": str(hdiag.planning_pages_found),
        "directory_pages_found": str(hdiag.directory_pages_found),
        "staff_links_found": str(hdiag.staff_links_found),
        "profile_links_followed": str(hdiag.profile_links_followed),
        "mailto_links_found": str(hdiag.mailto_links_found),
        "emails_found": str(hdiag.emails_found),
        "candidate_titles_found": str(hdiag.candidate_titles_found),
        "pages_fetched": str(hdiag.pages_fetched_count),
        "search_queries_run": str(hdiag.search_queries_run),
        "found_contact": "yes" if found else "no",
        "final_rejection_reason": hdiag.final_rejection_reason,
        "elapsed_seconds": f"{hdiag.elapsed_seconds:.2f}",
        "cache_hits": str(hdiag.cache_hits),
        "cache_misses": str(hdiag.cache_misses),
        "profile_pages_followed": str(hdiag.profile_pages_fetched),
        "early_stop": hdiag.early_stop,
        "max_page_limit_hit": hdiag.max_page_limit_hit,
        "timeout_count": str(hdiag.timeout_count),
        "fetch_error_count": str(hdiag.fetch_error_count),
        "resolver_method": hdiag.resolver_method,
        "search_results_seen": str(hdiag.search_results_seen),
        "search_results_rejected": str(hdiag.search_results_rejected),
        "planning_fallback_used": hdiag.planning_fallback_used,
        "planning_fallback_url": hdiag.planning_fallback_url,
        "planning_fallback_attempted": hdiag.planning_fallback_attempted,
        "planning_fallback_success": hdiag.planning_fallback_success,
        "fetch_failures_by_url": hdiag.fetch_failures_by_url,
        "orphan_emails_found": str(hdiag.orphan_emails_found),
        "orphan_emails_promoted": str(hdiag.orphan_emails_promoted),
        "candidate_pairing_failures": str(hdiag.candidate_pairing_failures),
    }


def _probe_urls(official_url: str) -> list[tuple[str, str]]:
    """Return (url, page_kind) probe candidates."""
    base = official_url.rstrip("/") + "/"
    seen: set[str] = {normalize_url(official_url)}
    urls: list[tuple[str, str]] = [(normalize_url(official_url), "homepage")]
    for path in HARVEST_PROBE_PATHS:
        url = normalize_url(urljoin(base, path.lstrip("/")))
        if url and url not in seen:
            seen.add(url)
            page_class = classify_page_url(url)
            if page_class == "planning":
                kind = "planning"
            elif page_class == "directory":
                kind = "directory"
            else:
                kind = "probe"
            urls.append((url, kind))
    return urls


def _resolve_official_site(
    j: Jurisdiction,
    fetcher: PageFetcher,
    manual_official: str | None,
    diag: HarvestDiagnostics,
    config: HarvestConfig,
    domain_cache: dict[tuple[str, str, str], dict[str, str]],
) -> tuple[str | None, list[str]]:
    """Return (official_url, manual_direct_urls from planning fallback)."""
    if manual_official:
        url = normalize_url(manual_official)
        if url and config.use_domain_cache:
            save_domain_cache_entry(j, url, "manual", domain_cache)
        diag.resolver_method = "manual"
        return url, []

    if config.use_domain_cache and not config.refresh_domain_cache:
        cached = lookup_domain_cache(j, domain_cache)
        if cached:
            diag.resolver_method = "cache"
            return cached, []

    result = resolve_official_site(
        j,
        fetcher,
        config,
        manual_official=None,
        skip_guess=False,
    )
    diag.search_queries_run = result.search_queries_run
    diag.search_results_seen = result.search_results_seen
    diag.search_results_rejected = result.search_results_rejected
    diag.resolver_method = result.resolver_method

    manual_direct: list[str] = []
    official = result.official_url
    if result.planning_fallback_url:
        diag.planning_fallback_used = "yes"
        diag.planning_fallback_url = result.planning_fallback_url
        manual_direct.append(normalize_url(result.planning_fallback_url))
        if not official:
            official = result.official_url

    if official and config.use_domain_cache:
        method = result.resolver_method or "guess"
        save_domain_cache_entry(j, official, method, domain_cache)
    return official, manual_direct


def _extract_page(
    html: str,
    url: str,
    official: str,
    hdiag: HarvestDiagnostics,
    candidates: list[ContactCandidate],
    source_urls: list[str],
    *,
    page_kind: str,
) -> None:
    if url not in source_urls:
        source_urls.append(url)
    if not page_warrants_extraction(html, url, page_kind=page_kind):
        return
    hdiag.mailto_links_found += count_mailto_links(html)
    if matches_allowlisted_title(html):
        hdiag.candidate_titles_found += 1
    for em in extract_emails_from_text(html):
        if em not in hdiag.raw_emails:
            hdiag.raw_emails.append(em)
            hdiag.emails_found += 1
        if is_generic_email(em) and em not in hdiag.generic_emails:
            hdiag.generic_emails.append(em)
    candidates.extend(extract_contacts_from_html(html, url, official_url=official))


def _high_confidence_found(candidates: list[ContactCandidate], official: str) -> ContactCandidate | None:
    for c in candidates:
        if is_high_confidence_contact(c, official):
            return c
    best = select_best_contact(candidates)
    if best and is_high_confidence_contact(best, official):
        return best
    return None


def _process_fetched_page(
    html: str,
    url: str,
    page_kind: str,
    official: str,
    hdiag: HarvestDiagnostics,
    candidates: list[ContactCandidate],
    source_urls: list[str],
    page_snapshots: list[tuple[str, str, str]],
    *,
    planning_url: str,
) -> str:
    """Extract contacts from a fetched page; return updated planning_url."""
    page_snapshots.append((url, html, page_kind))
    if page_kind == "planning" or classify_page_url(url) == "planning":
        hdiag.planning_pages_found += 1
        hdiag.planning_page_found = True
        if not planning_url:
            planning_url = url
    elif page_kind == "directory" or classify_page_url(url) == "directory":
        hdiag.directory_pages_found += 1
        if not planning_url:
            planning_url = url
    elif page_kind == "manual" and not planning_url:
        planning_url = url

    _extract_page(html, url, official, hdiag, candidates, source_urls, page_kind=page_kind)
    return planning_url


def _crawl_official_site(
    official: str,
    manual_direct: list[str],
    fetcher: PageFetcher,
    hdiag: HarvestDiagnostics,
    candidates: list[ContactCandidate],
    source_urls: list[str],
    page_snapshots: list[tuple[str, str, str]],
    config: HarvestConfig,
) -> str:
    """Priority crawl with per-kind limits and early stop."""
    planning_url = ""
    pages_fetched = 0
    profile_pages_fetched = 0
    planning_pages_fetched = 0
    directory_pages_fetched = 0
    fetched_urls: set[str] = set()
    queued: set[str] = set()
    heap: list[tuple[int, int, str, str]] = []
    seq = 0

    def push(url: str, page_kind: str, link_text: str = "") -> None:
        nonlocal seq
        normalized = normalize_url(url)
        if not normalized or normalized in queued or normalized in fetched_urls:
            return
        queued.add(normalized)
        priority = crawl_priority(normalized, link_text, official, kind=page_kind)
        if page_kind == "manual":
            priority = 1000
        heapq.heappush(heap, (-priority, seq, normalized, page_kind))
        seq += 1

    def fetch_and_process(url: str, page_kind: str) -> str | None:
        nonlocal pages_fetched, profile_pages_fetched, planning_pages_fetched
        nonlocal directory_pages_fetched, planning_url
        if pages_fetched >= config.max_pages_per_jurisdiction:
            hdiag.max_page_limit_hit = "yes"
            return None
        if page_kind == "profile" and profile_pages_fetched >= config.max_profile_pages_per_jurisdiction:
            return None
        if page_kind == "planning" and planning_pages_fetched >= MAX_PLANNING_PAGE_FETCHES:
            return None
        if page_kind == "directory" and directory_pages_fetched >= config.max_directory_pages_per_jurisdiction:
            return None

        profile = fetch_profile_for_page_kind(page_kind)
        if page_kind == "manual":
            hdiag.planning_fallback_attempted = "yes"
        html = fetcher.fetch_html(url, profile=profile)
        if page_kind == "manual" and html:
            hdiag.planning_fallback_success = "yes"
        if not html:
            return None

        fetched_urls.add(url)
        pages_fetched += 1
        if page_kind == "planning":
            planning_pages_fetched += 1
        if page_kind == "profile":
            profile_pages_fetched += 1
            hdiag.profile_pages_fetched += 1
        if page_kind == "directory":
            directory_pages_fetched += 1

        planning_url = _process_fetched_page(
            html,
            url,
            page_kind,
            official,
            hdiag,
            candidates,
            source_urls,
            page_snapshots,
            planning_url=planning_url,
        )
        return html

    # Prefetch planning-fallback / manual URLs first so they cannot be skipped by heap limits.
    for url in manual_direct:
        normalized = normalize_url(url)
        if not normalized:
            continue
        queued.add(normalized)
        html = fetch_and_process(normalized, "manual")
        if html and _high_confidence_found(candidates, official):
            hdiag.early_stop = "yes"
            hdiag.pages_fetched_count = pages_fetched
            return planning_url

    for url, kind in _probe_urls(official):
        push(url, kind)

    while heap:
        if pages_fetched >= config.max_pages_per_jurisdiction:
            hdiag.max_page_limit_hit = "yes"
            break

        _, _, url, page_kind = heapq.heappop(heap)
        if url in fetched_urls:
            continue
        html = fetch_and_process(url, page_kind)
        if not html:
            continue

        if _high_confidence_found(candidates, official):
            hdiag.early_stop = "yes"
            break

        for link_url, score in discover_internal_staff_urls(html, url, official):
            kind = url_crawl_kind(link_url, official)
            before = len(queued)
            push(link_url, kind, link_text=str(score))
            if len(queued) > before:
                hdiag.staff_links_found += 1

        if hdiag.early_stop == "yes":
            break

        if _high_confidence_found(candidates, official):
            hdiag.early_stop = "yes"
            break

        for prof in extract_profile_followups(html, url, official):
            before = len(queued)
            push(prof.profile_url, "profile", prof.name)
            if len(queued) > before:
                hdiag.profile_links_followed += 1

    hdiag.pages_fetched_count = pages_fetched
    return planning_url


def harvest_jurisdiction(
    j: Jurisdiction,
    fetcher: PageFetcher,
    manual_entries: list[ManualUrlEntry] | None = None,
    stats: BuildStats | None = None,
    config: HarvestConfig | None = None,
    domain_cache: dict[tuple[str, str, str], dict[str, str]] | None = None,
) -> tuple[dict[str, str] | None, dict[str, str] | None, dict[str, str]]:
    """
    Official-site-first harvest with staff-directory and profile-page following.
    Returns (working_row, rejected_row, diagnostics_row).
    """
    config = config or HarvestConfig()
    domain_cache = domain_cache if domain_cache is not None else load_domain_cache()
    started = time.monotonic()
    if hasattr(fetcher, "begin_jurisdiction"):
        fetcher.begin_jurisdiction()

    if j.state == "RI" and j.geography_type == "county":
        hdiag = HarvestDiagnostics(final_rejection_reason="no_county_government")
        hdiag.elapsed_seconds = time.monotonic() - started
        diag = DiscoverDiagnostics()
        return (
            None,
            reject_row(
                j,
                "no_county_government",
                notes=RI_COUNTY_NOTE,
                diag=diag,
            ),
            diagnostics_row(j, hdiag, found=False),
        )

    overrides = manual_entries or []
    manual_official: str | None = None
    manual_direct: list[str] = []
    manual_used: list[str] = []
    manual_results: list[str] = []

    for entry in overrides:
        manual_used.append(entry.url)
        if entry.url_type == "official_site":
            html = fetcher.fetch_html(entry.url)
            if html:
                manual_official = normalize_url(entry.url)
                manual_results.append("official_site:ok")
            else:
                manual_results.append("official_site:fetch_failed")
        elif entry.url_type != "pdf":
            manual_direct.append(normalize_url(entry.url))

    hdiag = HarvestDiagnostics(manual_url_used="; ".join(manual_used))
    official, planning_direct = _resolve_official_site(
        j, fetcher, manual_official, hdiag, config, domain_cache
    )
    for url in planning_direct:
        if url not in manual_direct:
            manual_direct.append(url)
    hdiag.official_site_found = bool(official)
    if official:
        hdiag.official_domain = official_netloc(official)

    candidates: list[ContactCandidate] = []
    source_urls: list[str] = []
    page_snapshots: list[tuple[str, str, str]] = []
    planning_url = ""
    crawl_base = ""

    if official or manual_direct:
        crawl_base = official or manual_direct[0]
        if not official:
            hdiag.official_domain = official_netloc(crawl_base)
        planning_url = _crawl_official_site(
            crawl_base,
            manual_direct,
            fetcher,
            hdiag,
            candidates,
            source_urls,
            page_snapshots,
            config,
        )
        orphan_cands, orphans_found, orphans_promoted, pairing_failures = recover_orphan_email_candidates(
            page_snapshots,
            crawl_base,
            candidates,
        )
        hdiag.orphan_emails_found = orphans_found
        hdiag.orphan_emails_promoted = orphans_promoted
        hdiag.candidate_pairing_failures = pairing_failures
        candidates.extend(orphan_cands)

    hdiag.manual_url_result = "; ".join(manual_results)
    for c in candidates:
        if classify_email(c.email, c.name, c.paired_with_name) == "direct":
            hdiag.direct_email_candidates_count += 1

    if hasattr(fetcher, "end_jurisdiction"):
        fstats = fetcher.end_jurisdiction()
        hdiag.cache_hits = fstats.cache_hits
        hdiag.cache_misses = fstats.cache_misses
        hdiag.timeout_count = fstats.timeout_count
        hdiag.fetch_error_count = fstats.fetch_error_count
        hdiag.fetch_failures_by_url = format_fetch_failures(fstats.fetch_failures)
    hdiag.elapsed_seconds = time.monotonic() - started

    diag = DiscoverDiagnostics(
        official_site_found=hdiag.official_site_found,
        planning_page_found=hdiag.planning_page_found or bool(manual_direct),
        pages_fetched_count=hdiag.pages_fetched_count,
        search_urls_found=hdiag.search_urls_found,
        search_queries_run=hdiag.search_queries_run,
        manual_url_used=hdiag.manual_url_used,
        manual_url_result=hdiag.manual_url_result,
        raw_emails=hdiag.raw_emails,
        generic_emails=hdiag.generic_emails,
        candidate_titles_found_count=hdiag.candidate_titles_found,
        direct_email_candidates_count=hdiag.direct_email_candidates_count,
        raw_emails_found_count=len(hdiag.raw_emails),
        generic_emails_found_count=len(hdiag.generic_emails),
    )

    if not official and not manual_direct:
        hdiag.final_rejection_reason = "no_official_site_found"
        result = (
            None,
            reject_row(
                j,
                "no_official_site_found",
                notes=(
                    f"Could not resolve official website "
                    f"(resolver={hdiag.resolver_method or 'none'}, "
                    f"searches={hdiag.search_queries_run}, "
                    f"rejections={hdiag.search_results_rejected})"
                ),
                diag=diag,
            ),
            diagnostics_row(j, hdiag, found=False),
        )
        if stats:
            stats.record_jurisdiction(
                search_queries=hdiag.search_queries_run,
                pages=hdiag.pages_fetched_count,
                found=False,
            )
        return result

    best = select_best_contact(candidates)
    if not planning_url:
        planning_url = official or (manual_direct[0] if manual_direct else "")

    match_status, match_notes = validate_jurisdiction_match(
        j.jurisdiction_name,
        j.state,
        official_url=official or "",
        planning_url=planning_url,
        email=best.email if best else "",
        source_urls=source_urls,
    )

    notes = ""
    if match_status == "mismatch":
        hdiag.final_rejection_reason = "jurisdiction_mismatch"
        result = (
            None,
            reject_row(
                j,
                "jurisdiction_mismatch",
                sources="; ".join(source_urls[:8]),
                notes=match_notes,
                diag=diag,
            ),
            diagnostics_row(j, hdiag, found=False),
        )
        if stats:
            stats.record_jurisdiction(
                search_queries=hdiag.search_queries_run,
                pages=hdiag.pages_fetched_count,
                found=False,
            )
        return result

    if match_status == "uncertain" and match_notes:
        notes = match_notes

    if best and best.orphan_recovered:
        match_status = "uncertain"
        orphan_note = (
            "Orphan email recovery: planning title and direct email found on same page "
            "but not structurally paired; verify contact before outreach."
        )
        match_notes = f"{match_notes}; {orphan_note}".strip("; ").strip() if match_notes else orphan_note
        notes = match_notes

    if best:
        hdiag.final_rejection_reason = ""
        row = working_row_from_contact(
            j,
            official=official,
            planning_url=planning_url,
            contact_name=best.name,
            contact_title=best.title,
            email=best.email,
            email_source_url=best.source_url,
            candidate_source_url=best.source_url,
            discovery_method="directory_harvest",
            plan_year="",
            update_signal="",
            priority="",
            priority_reason="",
            match_status=match_status,
            match_notes=match_notes,
            notes=notes,
        )
        if stats:
            stats.record_jurisdiction(
                search_queries=hdiag.search_queries_run,
                pages=hdiag.pages_fetched_count,
                found=True,
            )
        return row, None, diagnostics_row(j, hdiag, found=True)

    sources = "; ".join(source_urls[:8])
    raw_debug = ", ".join(hdiag.raw_emails[:5])
    generic_debug = ", ".join(hdiag.generic_emails[:3])

    if hdiag.generic_emails and not candidates:
        reason = "only_generic_email_found"
        reject = reject_row(
            j,
            reason,
            email_found=hdiag.generic_emails[0],
            sources=sources,
            notes=f"raw_emails={raw_debug}",
            diag=diag,
        )
    elif candidates:
        reason = "no_direct_email_found"
        reject = reject_row(
            j,
            reason,
            sources=sources,
            notes=f"Contact/title found but no direct email. raw={raw_debug}",
            diag=diag,
        )
    elif source_urls:
        reason = "no_planning_contact_found"
        reject = reject_row(
            j,
            reason,
            sources=sources,
            notes=f"raw_emails={raw_debug}; generic={generic_debug}",
            diag=diag,
        )
    else:
        reason = "no_planning_contact_found"
        reject = reject_row(
            j,
            reason,
            notes="No staff/planning pages returned content on official domain",
            diag=diag,
        )

    hdiag.final_rejection_reason = reason
    if stats:
        stats.record_jurisdiction(
            search_queries=hdiag.search_queries_run,
            pages=hdiag.pages_fetched_count,
            found=False,
        )
    return None, reject, diagnostics_row(j, hdiag, found=False)
