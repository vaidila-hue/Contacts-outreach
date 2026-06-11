"""CLI entry point and build pipeline."""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Allow running as python src/run.py from project root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.build_mode import BuildMode, BuildStats, resolve_delay
from src.directory_harvest import harvest_jurisdiction, sort_jurisdictions_for_harvest
from src.domain_cache import load_domain_cache
from src.discover_common import (
    DiscoverDiagnostics,
    RI_COUNTY_NOTE,
    reject_row as _reject_row,
    working_row_from_contact,
    working_row_from_jurisdiction,
)
from src.census_seed import (
    Jurisdiction,
    load_jurisdictions,
    print_seed_summary,
    save_jurisdictions,
    seed_jurisdictions,
)
from src.csv_utils import empty_row, read_csv
from src.export_results import (
    clear_output_csvs,
    export_only,
    export_outreach,
    merge_working_row,
    write_diagnostics_csv,
    write_outreach_csv,
    write_rejected_csv,
    write_working_csv,
)
from src.extract_contacts import (
    ContactCandidate,
    extract_contacts_from_html,
    select_best_contact,
)
from src.extract_emails import classify_email, extract_emails_from_text, is_generic_email
from src.extract_pdf import extract_contacts_from_pdf, extract_text_from_pdf
from src.extract_plan_signals import extract_plan_metadata
from src.deps_check import verify_dependencies
from src.jurisdiction_utils import filter_urls_for_jurisdiction, official_homepage_from_url
from src.prospect_priority import compute_prospect_priority
from src.fetch_pages import PageFetcher, find_pdf_links
from src.manual_urls import ManualUrlEntry, load_manual_urls, manual_urls_for_jurisdiction
from src.outreach_cli import run_outreach_draft, run_outreach_prepare, run_outreach_send
from src.outreach_launch import (
    CRM_URL,
    PortInUseError,
    check_port_available,
    is_crm_server_running,
    is_port_in_use,
    open_crm_browser,
)
from src.outreach_ui import run_outreach_server
from src.paths import (
    DEFAULT_MAX_POP,
    DEFAULT_MIN_POP,
    DEFAULT_STATES,
    REJECTED_COLUMNS,
    REJECTED_CSV,
    WORKING_COLUMNS,
    WORKING_CSV,
    DIAGNOSTICS_CSV,
    OUTREACH_PORT,
)
from src.person_first_discovery import (
    PersonFirstResult,
    person_first_working_eligible,
    run_person_first_pass,
)
from src.jurisdiction_validation import (
    search_snippet_working_eligible,
    validate_jurisdiction_match,
)
from src.role_config import MAX_FAST_PAGES, matches_allowlisted_title
from src.search_web import (
    discover_official_site,
    fast_planning_search,
    rank_search_results,
    search_planning_pages,
)
from src.search_providers import SearchHit, active_search_provider, brave_api_configured, diagnose_search


def _parse_states(states_arg: str) -> list[str]:
    return [s.strip().upper() for s in states_arg.split(",") if s.strip()]


def _discovery_method_for_contact(
    source_url: str,
    manual_direct: list[str],
    manual_pdfs: list[str],
    *,
    from_search_snippet: bool = False,
) -> str:
    if from_search_snippet:
        return "search_snippet"
    lower = source_url.lower()
    if source_url in manual_direct or source_url in manual_pdfs:
        return "manual_url"
    if lower.endswith(".pdf"):
        return "pdf_extraction"
    return "page_extraction"


_working_row_from_contact = working_row_from_contact
_working_row_from_jurisdiction = working_row_from_jurisdiction


def _collect_pages(
    fetcher: PageFetcher,
    official_url: str | None,
    search_urls: list[str],
    manual_direct_urls: list[str] | None = None,
) -> list[str]:
    """Prioritize manual overrides, then search-found pages, then domain probes."""
    manual_direct_urls = manual_direct_urls or []
    candidates: list[str] = []
    candidates.extend(manual_direct_urls)
    candidates.extend(search_urls)
    if official_url:
        candidates.append(official_url)
        candidates.extend(fetcher.probe_domain(official_url))
    seen: set[str] = set()
    unique: list[str] = []
    manual_set = set(manual_direct_urls)
    for p in candidates:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    manual_part = [u for u in unique if u in manual_set]
    other_part = rank_search_results([u for u in unique if u not in manual_set])[:5]
    return manual_part + other_part


def _collect_pages_fast(
    official_url: str | None,
    search_urls: list[str],
    manual_direct_urls: list[str] | None = None,
) -> list[str]:
    """Fast mode: manual overrides, top search result, and official site only."""
    manual_direct_urls = manual_direct_urls or []
    pages: list[str] = list(manual_direct_urls)
    if search_urls:
        pages.append(search_urls[0])
    if official_url and official_url not in pages:
        pages.append(official_url)
    seen: set[str] = set()
    unique: list[str] = []
    for url in pages:
        if url and url not in seen:
            seen.add(url)
            unique.append(url)
    return unique[: MAX_FAST_PAGES + len(manual_direct_urls)]


def _extract_from_search_hits(
    hits: list[SearchHit],
    diag: DiscoverDiagnostics,
    all_candidates: list[ContactCandidate],
    source_urls: list[str],
) -> None:
    for hit in hits:
        text = f"{hit.title}\n{hit.snippet}".strip()
        if not text:
            continue
        title = matches_allowlisted_title(text) or ""
        if title:
            diag.candidate_titles_found_count += 1
        for em in extract_emails_from_text(text):
            if em not in diag.raw_emails:
                diag.raw_emails.append(em)
            if is_generic_email(em):
                if em not in diag.generic_emails:
                    diag.generic_emails.append(em)
                continue
            if hit.url and hit.url not in source_urls:
                source_urls.append(hit.url)
            all_candidates.append(
                ContactCandidate(
                    name="",
                    title=title,
                    email=em,
                    source_url=hit.url,
                    paired_with_name=False,
                )
            )


def _extract_from_html(
    html: str,
    url: str,
    official: str | None,
    fetcher: PageFetcher,
    diag: DiscoverDiagnostics,
    all_candidates: list[ContactCandidate],
    source_urls: list[str],
    *,
    include_pdfs: bool = True,
) -> str:
    """Parse HTML page and optionally linked PDFs; return appended text for plan metadata."""
    combined = " " + html
    source_urls.append(url)
    if matches_allowlisted_title(html):
        diag.candidate_titles_found_count += 1
    for em in extract_emails_from_text(html):
        if em not in diag.raw_emails:
            diag.raw_emails.append(em)
        if is_generic_email(em) and em not in diag.generic_emails:
            diag.generic_emails.append(em)
    all_candidates.extend(extract_contacts_from_html(html, url))

    if not include_pdfs:
        return combined

    base = official or url
    if base:
        for pdf_url in find_pdf_links(html, url, base):
            pdf_bytes = fetcher.fetch_pdf(pdf_url)
            if not pdf_bytes:
                continue
            diag.pdfs_fetched_count += 1
            source_urls.append(pdf_url)
            all_candidates.extend(extract_contacts_from_pdf(pdf_bytes, pdf_url))
            pdf_text = extract_text_from_pdf(pdf_bytes)
            combined += " " + pdf_text
            if matches_allowlisted_title(pdf_text):
                diag.candidate_titles_found_count += 1
            for em in extract_emails_from_text(pdf_text):
                if em not in diag.raw_emails:
                    diag.raw_emails.append(em)
    return combined


def _extract_from_pdf_url(
    pdf_url: str,
    fetcher: PageFetcher,
    diag: DiscoverDiagnostics,
    all_candidates: list[ContactCandidate],
    source_urls: list[str],
) -> str:
    pdf_bytes = fetcher.fetch_pdf(pdf_url)
    if not pdf_bytes:
        return ""
    diag.pdfs_fetched_count += 1
    source_urls.append(pdf_url)
    all_candidates.extend(extract_contacts_from_pdf(pdf_bytes, pdf_url))
    pdf_text = extract_text_from_pdf(pdf_bytes)
    if matches_allowlisted_title(pdf_text):
        diag.candidate_titles_found_count += 1
    for em in extract_emails_from_text(pdf_text):
        if em not in diag.raw_emails:
            diag.raw_emails.append(em)
    return " " + pdf_text


def _manual_type_for_url(url: str, entries: list[ManualUrlEntry]) -> str:
    for entry in entries:
        if entry.url == url:
            return entry.url_type
    return "manual"


def _finalize_discover(
    j: Jurisdiction,
    *,
    official: str | None,
    planning_url: str,
    diag: DiscoverDiagnostics,
    all_candidates: list[ContactCandidate],
    combined_text: str,
    source_urls: list[str],
    manual_direct: list[str],
    manual_pdfs: list[str],
    mode: BuildMode,
    search_hit_urls: set[str] | None = None,
    fetched_page_urls: set[str] | None = None,
) -> tuple[dict[str, str] | None, dict[str, str] | None, str]:
    diag.raw_emails_found_count = len(diag.raw_emails)
    diag.generic_emails_found_count = len(diag.generic_emails)
    for c in all_candidates:
        if classify_email(c.email, c.name, c.paired_with_name) == "direct":
            diag.direct_email_candidates_count += 1

    best = select_best_contact(all_candidates)
    if mode.include_plan_signals:
        plan_year, update_signal = extract_plan_metadata(combined_text)
    else:
        plan_year, update_signal = "", ""
    priority, priority_reason = compute_prospect_priority(plan_year, update_signal)

    match_status, match_notes = validate_jurisdiction_match(
        j.jurisdiction_name,
        j.state,
        official_url=official or "",
        planning_url=planning_url,
        email=best.email if best else "",
        source_urls=source_urls,
    )

    if match_status == "mismatch":
        return None, _reject_row(
            j,
            "jurisdiction_mismatch",
            sources="; ".join(source_urls[:8]),
            notes=match_notes,
            diag=diag,
        ), combined_text

    if best:
        from_snippet = (
            search_hit_urls is not None
            and best.source_url in search_hit_urls
            and (fetched_page_urls is None or best.source_url not in fetched_page_urls)
        )
        method = _discovery_method_for_contact(
            best.source_url,
            manual_direct,
            manual_pdfs,
            from_search_snippet=from_snippet,
        )
        if method == "search_snippet":
            snippet_ok, snippet_notes = search_snippet_working_eligible(
                best.email,
                best.source_url,
                j.jurisdiction_name,
                j.state,
                official or "",
            )
            if not snippet_ok:
                return None, _reject_row(
                    j,
                    "snippet_non_official_source",
                    email_found=best.email,
                    sources=best.source_url,
                    notes=snippet_notes,
                    diag=diag,
                    discovery_method=method,
                    email_source_url=best.source_url,
                    jurisdiction_match_notes=match_notes or snippet_notes,
                ), combined_text
        row = _working_row_from_contact(
            j,
            official=official,
            planning_url=planning_url,
            contact_name=best.name,
            contact_title=best.title,
            email=best.email,
            email_source_url=best.source_url,
            candidate_source_url=best.source_url,
            discovery_method=method,
            plan_year=plan_year,
            update_signal=update_signal,
            priority=priority,
            priority_reason=priority_reason,
            match_status=match_status,
            match_notes=match_notes,
        )
        return row, None, combined_text

    return None, None, combined_text


def _discover_jurisdiction(
    j: Jurisdiction,
    fetcher: PageFetcher,
    delay: float,
    manual_entries: list[ManualUrlEntry] | None = None,
    mode: BuildMode | None = None,
    stats: BuildStats | None = None,
    domain_cache: dict | None = None,
) -> tuple[dict[str, str] | None, dict[str, str] | None, str, dict[str, str] | None]:
    """
    Returns (working_row, rejected_row, combined_text, diagnostics_row).
    diagnostics_row is set for directory harvest mode only.
    """
    empty_diag: dict[str, str] | None = None
    mode = mode or BuildMode()
    if not mode.deep:
        working, rejected, diag_row = harvest_jurisdiction(
            j,
            fetcher,
            manual_entries,
            stats=stats,
            config=mode.harvest,
            domain_cache=domain_cache,
        )
        return working, rejected, "", diag_row

    if j.state == "RI" and j.geography_type == "county":
        diag = DiscoverDiagnostics()
        return None, _reject_row(
            j,
            "no_county_government",
            notes=RI_COUNTY_NOTE,
            diag=diag,
        ), "", None

    overrides = manual_entries or []
    manual_direct: list[str] = []
    manual_pdfs: list[str] = []
    manual_used: list[str] = []
    manual_results: list[str] = []
    official: str | None = None

    for entry in overrides:
        manual_used.append(entry.url)
        if entry.url_type == "official_site":
            html = fetcher.fetch_html(entry.url)
            if html:
                official = entry.url
                manual_results.append("official_site:ok")
            else:
                manual_results.append("official_site:fetch_failed")
        elif entry.url_type == "pdf":
            if mode.include_pdfs or mode.deep:
                manual_pdfs.append(entry.url)
        else:
            manual_direct.append(entry.url)

    search_hits: list[SearchHit] = []
    queries_run = 0
    if mode.deep:
        search_urls, queries_run = search_planning_pages(
            j.jurisdiction_name,
            j.state,
            j.geography_type,
            j.county_name,
            delay,
        )
        search_urls = filter_urls_for_jurisdiction(search_urls, j.jurisdiction_name, j.state)
        if not official:
            official = discover_official_site(
                j.jurisdiction_name,
                j.state,
                j.geography_type,
                fetcher,
                delay,
                planning_search_urls=search_urls,
            )
        page_urls = _collect_pages(fetcher, official, search_urls, manual_direct)
    else:
        search_urls, search_hits, queries_run = fast_planning_search(
            j.jurisdiction_name,
            j.state,
            j.geography_type,
            j.county_name,
            delay,
        )
        if not official and search_urls:
            official = official_homepage_from_url(search_urls[0])
        page_urls = _collect_pages_fast(official, search_urls, manual_direct)

    planning_url = (
        manual_direct[0]
        if manual_direct
        else (search_urls[0] if search_urls else (page_urls[0] if page_urls else ""))
    )

    diag = DiscoverDiagnostics(
        official_site_found=bool(official),
        planning_page_found=bool(search_urls or manual_direct),
        search_urls_found=len(search_urls),
        search_queries_run=queries_run,
        manual_url_used="; ".join(manual_used),
    )
    all_candidates: list[ContactCandidate] = []
    combined_text = ""
    source_urls: list[str] = []
    fetched_pages = 0
    fetched_page_urls: set[str] = set()
    search_url_set = set(search_urls)
    search_hit_urls = {h.url for h in search_hits if h.url}

    if not mode.deep:
        _extract_from_search_hits(search_hits, diag, all_candidates, source_urls)
        snippet_best = select_best_contact(all_candidates)
        if snippet_best:
            page_urls = [u for u in page_urls if u in manual_direct]

    if mode.include_pdfs or mode.deep:
        for pdf_url in manual_pdfs:
            pdf_text = _extract_from_pdf_url(pdf_url, fetcher, diag, all_candidates, source_urls)
            if pdf_text:
                combined_text += pdf_text
                manual_results.append("pdf:ok")
            else:
                manual_results.append("pdf:fetch_failed")

    for url in page_urls:
        html = fetcher.fetch_html(url)
        if not html:
            if url in manual_direct:
                manual_results.append(f"{_manual_type_for_url(url, overrides)}:fetch_failed")
            continue
        fetched_pages += 1
        fetched_page_urls.add(url)
        if url in search_url_set:
            diag.search_urls_fetched += 1
        if url in manual_direct:
            manual_results.append(f"{_manual_type_for_url(url, overrides)}:ok")
        combined_text += _extract_from_html(
            html,
            url,
            official,
            fetcher,
            diag,
            all_candidates,
            source_urls,
            include_pdfs=mode.include_pdfs or mode.deep,
        )

    diag.pages_fetched_count = fetched_pages
    diag.manual_url_result = "; ".join(manual_results)

    working, rejected, combined_text = _finalize_discover(
        j,
        official=official,
        planning_url=planning_url,
        diag=diag,
        all_candidates=all_candidates,
        combined_text=combined_text,
        source_urls=source_urls,
        manual_direct=manual_direct,
        manual_pdfs=manual_pdfs,
        mode=mode,
        search_hit_urls=search_hit_urls if not mode.deep else None,
        fetched_page_urls=fetched_page_urls,
    )
    if working or rejected:
        if stats is not None:
            stats.record_jurisdiction(
                search_queries=diag.search_queries_run,
                pages=diag.pages_fetched_count,
                pdfs=diag.pdfs_fetched_count,
                found=working is not None,
            )
        return working, rejected, combined_text, None

    if mode.person_first or mode.deep:
        pf = run_person_first_pass(
            j.jurisdiction_name,
            j.state,
            j.geography_type,
            j.county_name,
            official,
            fetcher,
            delay,
        )
        if pf:
            if pf.jurisdiction_match_status == "mismatch":
                result = (
                    None,
                    _reject_row(
                        j,
                        "jurisdiction_mismatch",
                        sources=f"{pf.candidate_source_url}; {pf.email_source_url}",
                        notes=pf.jurisdiction_match_notes,
                        diag=diag,
                        pf=pf,
                    ),
                    combined_text,
                    None,
                )
            elif not person_first_working_eligible(pf, j.jurisdiction_name, j.state, official):
                result = (
                    None,
                    _reject_row(
                        j,
                        "jurisdiction_uncertain_person_first",
                        sources=f"{pf.candidate_source_url}; {pf.email_source_url}",
                        notes=pf.jurisdiction_match_notes,
                        diag=diag,
                        pf=pf,
                    ),
                    combined_text,
                    None,
                )
            else:
                plan_year, update_signal = ("", "")
                if mode.include_plan_signals or mode.deep:
                    plan_year, update_signal = extract_plan_metadata(combined_text)
                pf_priority, pf_priority_reason = compute_prospect_priority(
                    plan_year, update_signal
                )
                result = (
                    _working_row_from_contact(
                        j,
                        official=official,
                        planning_url=planning_url,
                        contact_name=pf.contact_name,
                        contact_title=pf.contact_title,
                        email=pf.email,
                        email_source_url=pf.email_source_url,
                        candidate_source_url=pf.candidate_source_url,
                        discovery_method=pf.discovery_method,
                        plan_year=plan_year,
                        update_signal=update_signal,
                        priority=pf_priority,
                        priority_reason=pf_priority_reason,
                        match_status=pf.jurisdiction_match_status,
                        match_notes=pf.jurisdiction_match_notes,
                    ),
                    None,
                    combined_text,
                    None,
                )
            if stats is not None:
                stats.record_jurisdiction(
                    search_queries=diag.search_queries_run,
                    pages=diag.pages_fetched_count,
                    pdfs=diag.pdfs_fetched_count,
                    found=result[0] is not None,
                )
            return result

    sources = "; ".join(source_urls[:8])
    raw_debug = ", ".join(diag.raw_emails[:5])
    generic_debug = ", ".join(diag.generic_emails[:3])

    if diag.generic_emails and not all_candidates:
        result = (
            None,
            _reject_row(
                j,
                "only_generic_email_found",
                email_found=diag.generic_emails[0],
                sources=sources,
                notes=f"raw_emails={raw_debug}",
                diag=diag,
            ),
            combined_text,
            None,
        )
    elif all_candidates:
        result = (
            None,
            _reject_row(
                j,
                "no_direct_email_found",
                sources=sources,
                notes=f"Contact/title found but no direct email. raw={raw_debug}",
                diag=diag,
            ),
            combined_text,
            None,
        )
    elif source_urls:
        result = (
            None,
            _reject_row(
                j,
                "no_planning_contact_found",
                sources=sources,
                notes=f"raw_emails={raw_debug}; generic={generic_debug}",
                diag=diag,
            ),
            combined_text,
            None,
        )
    else:
        result = (
            None,
            _reject_row(
                j,
                "unclear_source",
                notes="No usable pages found",
                diag=diag,
            ),
            combined_text,
            None,
        )

    if stats is not None:
        stats.record_jurisdiction(
            search_queries=diag.search_queries_run,
            pages=diag.pages_fetched_count,
            pdfs=diag.pdfs_fetched_count,
            found=False,
        )
    return result


def run_build(args: argparse.Namespace) -> None:
    load_dotenv(ROOT / ".env")
    verify_dependencies()

    if args.clear_outputs and args.export_only:
        print("Error: --clear-outputs cannot be used with --export-only.")
        raise SystemExit(1)

    if args.export_only:
        total, approved = export_only()
        print(f"Export-only: {approved} contacts in outreach.csv (from {total} working rows)")
        return

    mode = BuildMode.from_args(args)
    delay = resolve_delay(args)
    started = time.monotonic()

    if args.clear_outputs:
        clear_output_csvs()
        print("Cleared prospects_working.csv, prospects_rejected.csv, outreach.csv, and harvest_diagnostics.csv.")

    states = _parse_states(args.states)
    existing_working = read_csv(WORKING_CSV, WORKING_COLUMNS)
    done_keys = {
        (r["state"], r["jurisdiction_name"], r["geography_type"])
        for r in existing_working
        if r.get("_status") == "done"
    }

    mode_label = "deep (legacy search-first)" if mode.deep else "directory harvest"
    include_counties = getattr(args, "include_counties", False)
    geo_note = "all geographies" if include_counties else "cities/towns/villages/boroughs/townships (no counties)"
    print(f"Build mode: {mode_label} (delay={delay}s; {geo_note})")
    print(f"Seeding jurisdictions for {len(states)} states...")
    jurisdictions, seed_stats = seed_jurisdictions(states, args.min_pop, args.max_pop)
    jurisdictions = sort_jurisdictions_for_harvest(
        jurisdictions, include_counties=include_counties
    )
    save_jurisdictions(jurisdictions)
    print_seed_summary(seed_stats, len(jurisdictions))

    pending = [
        j for j in jurisdictions
        if j.key() not in done_keys or args.force_refresh
    ]
    if args.limit:
        pending = pending[: args.limit]

    working_rows = list(existing_working)
    rejected_rows = read_csv(REJECTED_CSV, REJECTED_COLUMNS)
    manual_all = load_manual_urls()
    stats = BuildStats()
    diagnostics_rows: list[dict[str, str]] = []

    processed = 0
    found = 0

    with PageFetcher(
        delay=delay,
        force_refresh=args.force_refresh,
        use_fetch_cache=mode.harvest.use_fetch_cache,
        fetch_cache_ttl_days=mode.harvest.fetch_cache_ttl_days,
        connect_timeout=5.0,
        read_timeout=10.0,
        max_retries=2 if mode.deep else 1,
    ) as fetcher:
        domain_cache = load_domain_cache()
        for j in pending:
            print(f"  [{processed + 1}/{len(pending)}] {j.jurisdiction_name}, {j.state}...")
            try:
                overrides = manual_urls_for_jurisdiction(manual_all, j.state, j.jurisdiction_name)
                working, rejected, _, diag_row = _discover_jurisdiction(
                    j,
                    fetcher,
                    delay,
                    overrides,
                    mode=mode,
                    stats=stats,
                    domain_cache=domain_cache,
                )
                if diag_row:
                    diagnostics_rows.append(diag_row)
                if working:
                    working_rows = merge_working_row(working_rows, working)
                    found += 1
                if rejected:
                    rejected_rows = [
                        r for r in rejected_rows
                        if not (
                            r["state"] == rejected["state"]
                            and r["jurisdiction_name"] == rejected["jurisdiction_name"]
                            and r["geography_type"] == rejected["geography_type"]
                        )
                    ]
                    rejected_rows.append(rejected)
            except Exception as exc:
                stats.record_jurisdiction()
                print(f"    Error: {exc}")
            processed += 1

    write_working_csv(working_rows)
    write_rejected_csv(rejected_rows)
    write_outreach_csv([])
    if diagnostics_rows:
        write_diagnostics_csv(diagnostics_rows)

    stats.elapsed_seconds = time.monotonic() - started
    avg = stats.elapsed_seconds / max(stats.jurisdictions_processed, 1)

    print(f"\nDone. Processed {processed} jurisdictions, {found} with direct email candidates.")
    print(f"  Working: {WORKING_CSV}")
    print(f"  Rejected: {REJECTED_CSV}")
    print(f"  Review:   {ROOT / 'data' / 'review.html'}")
    if diagnostics_rows:
        print(f"  Diagnostics: {DIAGNOSTICS_CSV}")
    print("\nPerformance:")
    print(f"  Elapsed: {stats.elapsed_seconds:.1f}s")
    print(f"  Jurisdictions processed: {stats.jurisdictions_processed}")
    print(f"  Average per jurisdiction: {avg:.1f}s")
    print(f"  Search queries run: {stats.search_queries_run}")
    print(f"  Pages fetched: {stats.pages_fetched}")
    print(f"  PDFs scanned: {stats.pdfs_scanned}")
    print(f"  Candidates found: {stats.candidates_found}")
    print("Review data/review.html or prospects_working.csv; set review_status=approved, then run:")
    print("  python src/run.py build --export-only")


def run_test_search(args: argparse.Namespace) -> int:
    load_dotenv(ROOT / ".env")
    verify_dependencies()
    jurisdiction = getattr(args, "jurisdiction", None) or "South Burlington"
    state = getattr(args, "state", None) or "VT"
    query = (
        f'"{jurisdiction}" "{state}" "Planning Director"'
        if not getattr(args, "query", None)
        else args.query
    )

    print(f"Search provider order: brave={'yes' if brave_api_configured() else 'no'}, ddgs=fallback")
    print(f"Active provider for this query: {active_search_provider()}")
    print(f"Query: {query}")
    print(f"Jurisdiction filter: {jurisdiction}, {state}")
    print()

    diag = diagnose_search(query, jurisdiction, state, max_results=8, gov_only=False)
    print(f"Provider used: {diag.provider}")
    print(f"Raw results: {diag.raw_count}")
    if diag.errors:
        print("Search provider errors:")
        for err in diag.errors:
            print(f"  - {err}")
        print()

    for i, hit in enumerate(diag.hits, 1):
        fr = diag.filtered[i - 1] if i - 1 < len(diag.filtered) else None
        status = fr.reason if fr else "n/a"
        accepted = fr.accepted if fr else False
        print(f"[{i}] {'ACCEPT' if accepted else 'REJECT'} ({status})")
        print(f"    URL: {hit.url}")
        print(f"    Title: {hit.title[:120]}")
        print(f"    Snippet: {hit.snippet[:160]}")
        print()

    accepted_urls = [fr.hit.url for fr in diag.filtered if fr.accepted]
    print(f"Filtered URLs accepted: {len(accepted_urls)}")
    for url in accepted_urls:
        print(f"  - {url}")
    return 0 if diag.raw_count > 0 else 1


def run_test_census(args: argparse.Namespace) -> int:
    """Smoke test: load .env, verify Census API key, fetch jurisdiction count."""
    env_path = ROOT / ".env"
    loaded = load_dotenv(env_path)
    key = os.environ.get("CENSUS_API_KEY", "").strip()

    print(f".env path: {env_path}")
    print(f".env loaded: {loaded and env_path.exists()}")
    if key:
        print(f"CENSUS_API_KEY: set ({len(key)} chars)")
    else:
        print("CENSUS_API_KEY: NOT SET")
        print("WARNING: Census API requires a key. Get one at https://api.census.gov/data/key_signup.html")
        return 1

    states = _parse_states(args.states)
    print(f"Testing Census seed for states: {', '.join(states)}")
    print(f"Population range: {args.min_pop:,} – {args.max_pop:,}")

    try:
        jurisdictions, seed_stats = seed_jurisdictions(states, args.min_pop, args.max_pop)
    except Exception as exc:
        print(f"FAILURE: Census API request failed — {exc}")
        return 1

    print("SUCCESS: Census seed completed")
    print_seed_summary(seed_stats, len(jurisdictions))
    return 0


def run_outreach_open() -> int:
    if is_crm_server_running():
        open_crm_browser()
        print(f"Contacts CRM is already running at {CRM_URL}")
        print("Opened browser.")
        return 0
    if is_port_in_use():
        print(
            f"Error: port {OUTREACH_PORT} is in use but does not appear to be the Contacts CRM.\n"
            f"Free port {OUTREACH_PORT} so the CRM can run at {CRM_URL}."
        )
        return 1
    run_outreach_server(open_browser=True)
    return 0


def run_outreach(args: argparse.Namespace) -> int:
    if args.open:
        return run_outreach_open()

    actions = sum(
        1
        for flag in (args.prepare, args.serve, args.draft, args.send)
        if flag
    )
    if actions != 1:
        print("Specify exactly one of: --prepare, --serve, --draft, --send (or use --open)")
        return 1
    if args.prepare:
        return run_outreach_prepare()
    if args.serve:
        try:
            check_port_available()
        except PortInUseError as exc:
            print(f"Error: {exc}")
            return 1
        run_outreach_server(open_browser=True)
        return 0
    if args.draft:
        return run_outreach_draft(args)
    return run_outreach_send(args)


def run_diagnose_discovery(args: argparse.Namespace) -> int:
    load_dotenv(ROOT / ".env")
    verify_dependencies()
    jurisdiction = getattr(args, "jurisdiction", None) or "Merced"
    state = getattr(args, "state", None) or "CA"
    geography_type = getattr(args, "geography_type", None) or "city"

    from src.site_discovery import diagnose_discovery, format_discovery_report

    report = diagnose_discovery(
        jurisdiction,
        state,
        geography_type=geography_type,
    )
    print(format_discovery_report(report))
    ok = report.final_outcome != "no_official_site_found"
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover direct planning-related contacts for local governments."
    )
    parser.add_argument("command", nargs="?", default="build", choices=["build", "test-census", "test-search", "diagnose-discovery", "outreach"])
    parser.add_argument(
        "--states",
        default=DEFAULT_STATES,
        help="Comma-separated state abbreviations",
    )
    parser.add_argument("--min-pop", type=int, default=DEFAULT_MIN_POP)
    parser.add_argument("--max-pop", type=int, default=DEFAULT_MAX_POP)
    parser.add_argument("--limit", type=int, default=0, help="Max jurisdictions to process")
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Seconds between HTTP/search requests (default: 0.75 fast, 3.0 deep)",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Heavy workflow: page crawl, PDFs, person-first, plan metadata",
    )
    parser.add_argument(
        "--include-pdfs",
        action="store_true",
        help="Scan PDFs (also enabled by --deep)",
    )
    parser.add_argument(
        "--include-plan-signals",
        action="store_true",
        help="Extract plan-year/update metadata (also enabled by --deep)",
    )
    parser.add_argument(
        "--person-first",
        action="store_true",
        dest="person_first",
        help="Run person-first second pass (also enabled by --deep)",
    )
    parser.add_argument(
        "--include-counties",
        action="store_true",
        help="Include counties in processing queue (default: cities/towns first, counties excluded)",
    )
    parser.add_argument("--export-only", action="store_true", help="Regenerate outreach.csv from approvals")
    parser.add_argument("--force-refresh", action="store_true", help="Re-process done jurisdictions")
    parser.add_argument(
        "--clear-outputs",
        action="store_true",
        help="Clear working/rejected/outreach CSVs before build (does not clear cache)",
    )
    parser.add_argument(
        "--max-pages-per-jurisdiction",
        type=int,
        default=None,
        help="Max HTML pages fetched per jurisdiction (default: 10; --deep: 25)",
    )
    parser.add_argument(
        "--max-profile-pages-per-jurisdiction",
        type=int,
        default=None,
        help="Max staff profile pages per jurisdiction (default: 4; --deep: 10)",
    )
    parser.add_argument(
        "--max-directory-pages-per-jurisdiction",
        type=int,
        default=None,
        help="Max directory pages per jurisdiction (default: 4; --deep: 8)",
    )
    parser.add_argument(
        "--max-search-queries-per-jurisdiction",
        type=int,
        default=None,
        help="Max search queries for official-site fallback (default: 8; --deep: 12)",
    )
    parser.add_argument(
        "--no-fetch-cache",
        action="store_true",
        help="Disable disk-backed HTTP response cache",
    )
    parser.add_argument(
        "--fetch-cache-ttl-days",
        type=int,
        default=7,
        help="Fetch cache TTL in days (default: 7)",
    )
    parser.add_argument(
        "--no-domain-cache",
        action="store_true",
        help="Disable official-domain resolution cache",
    )
    parser.add_argument(
        "--refresh-domain-cache",
        action="store_true",
        help="Ignore cached official domains and re-resolve",
    )
    parser.add_argument(
        "--query",
        default="",
        help="Override search query for test-search",
    )
    parser.add_argument("--jurisdiction", default="South Burlington", help="Jurisdiction name for test-search / diagnose-discovery")
    parser.add_argument("--state", default="VT", help="State abbreviation for test-search / diagnose-discovery")
    parser.add_argument(
        "--geography-type",
        default="city",
        dest="geography_type",
        help="Geography type for diagnose-discovery (city, town, county)",
    )
    parser.add_argument("--prepare", action="store_true", help="Outreach: merge contacts into outreach.csv")
    parser.add_argument("--serve", action="store_true", help="Outreach: start local CRM UI and open browser")
    parser.add_argument(
        "--open",
        action="store_true",
        help="Outreach: open CRM in browser; start server if not already running",
    )
    parser.add_argument("--draft", action="store_true", help="Outreach: create Gmail draft(s)")
    parser.add_argument("--send", action="store_true", help="Outreach: send drafted Gmail message(s)")
    parser.add_argument("--dry-run", action="store_true", help="Outreach: preview draft/send without changes")
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=2.0,
        help="Outreach: delay between Gmail API calls (default: 2)",
    )
    parser.add_argument("--force", action="store_true", help="Outreach: allow forced resend (requires --confirm-force)")
    parser.add_argument("--confirm-force", action="store_true", help="Outreach: confirm --force")
    args = parser.parse_args()

    if args.command == "build":
        run_build(args)
    elif args.command == "test-census":
        raise SystemExit(run_test_census(args))
    elif args.command == "test-search":
        raise SystemExit(run_test_search(args))
    elif args.command == "diagnose-discovery":
        raise SystemExit(run_diagnose_discovery(args))
    elif args.command == "outreach":
        raise SystemExit(run_outreach(args))


if __name__ == "__main__":
    main()
