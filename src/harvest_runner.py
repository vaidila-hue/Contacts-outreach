"""Run contact harvest from UI harvest config (append mode)."""

from __future__ import annotations

import argparse
from collections import Counter

from src.build_mode import BuildMode, BuildStats, resolve_delay
from src.census_seed import seed_jurisdictions, save_jurisdictions
from src.directory_harvest import harvest_jurisdiction, sort_jurisdictions_for_harvest
from src.domain_cache import load_domain_cache
from src.export_results import merge_working_row, write_diagnostics_csv, write_rejected_csv, write_working_csv
from src.fetch_pages import PageFetcher
from src.harvest_config_store import HarvestConfigSettings, load_harvest_config
from src.harvest_report import analyze_harvest_run, enrich_summary, save_harvest_report
from src.harvest_status import clear_harvest_running, set_harvest_running
from src.harvest_summary import (
    HarvestRunSummary,
    build_covered_jurisdiction_set,
    jurisdiction_record,
    now_iso,
    partition_jurisdictions,
    save_harvest_summary,
    unsupported_config_states,
)
from src.jurisdiction_utils import jurisdiction_match_key
from src.manual_urls import load_manual_urls, manual_urls_for_jurisdiction
from src.outreach_store import prepare_outreach, read_outreach_rows
from src.paths import DIAGNOSTICS_COLUMNS, REJECTED_COLUMNS, REJECTED_CSV, WORKING_COLUMNS, WORKING_CSV
from src.csv_utils import read_csv


def _args_from_config(config: HarvestConfigSettings) -> argparse.Namespace:
    return argparse.Namespace(
        states=config.states_csv(),
        min_pop=config.min_population,
        max_pop=config.max_population,
        limit=config.limit,
        include_counties=config.include_counties,
        deep=config.deep_mode,
        delay=None,
        force_refresh=False,
        max_pages_per_jurisdiction=None,
        max_profile_pages_per_jurisdiction=None,
        max_directory_pages_per_jurisdiction=None,
        max_search_queries_per_jurisdiction=None,
        no_fetch_cache=False,
        fetch_cache_ttl_days=7,
        no_domain_cache=False,
        refresh_domain_cache=False,
        include_pdfs=False,
        include_plan_signals=False,
        person_first=False,
    )


def _top_rejection_reasons(diagnostics_rows: list[dict[str, str]]) -> list[dict[str, str | int]]:
    counts = Counter(
        (row.get("final_rejection_reason") or "").strip() or "(found contact)"
        for row in diagnostics_rows
    )
    return [{"reason": reason, "count": count} for reason, count in counts.most_common()]


def _drop_covered_working_rows(
    working_rows: list[dict[str, str]], covered: set[tuple[str, str]]
) -> list[dict[str, str]]:
    return [
        row
        for row in working_rows
        if jurisdiction_match_key(row.get("state", ""), row.get("jurisdiction_name", ""))
        not in covered
    ]


def run_find_more_contacts() -> HarvestRunSummary:
    """Harvest using saved config; skip CRM jurisdictions; append new outreach contacts only."""
    set_harvest_running()
    try:
        return _run_find_more_contacts_impl()
    finally:
        clear_harvest_running()


def _run_find_more_contacts_impl() -> HarvestRunSummary:
    """Harvest using saved config; skip CRM jurisdictions; append new outreach contacts only."""
    started = now_iso()
    config = load_harvest_config()
    args = _args_from_config(config)
    mode = BuildMode.from_args(args)
    delay = resolve_delay(args)

    states = [s.strip().upper() for s in config.states if s.strip()]
    unsupported = unsupported_config_states(states)
    jurisdictions, _ = seed_jurisdictions(states, config.min_population, config.max_population)
    jurisdictions = sort_jurisdictions_for_harvest(
        jurisdictions, include_counties=config.include_counties
    )
    seeded_count = len(jurisdictions)
    save_jurisdictions(jurisdictions)

    outreach_rows = read_outreach_rows()
    covered = build_covered_jurisdiction_set(outreach_rows)
    pending, skipped = partition_jurisdictions(jurisdictions, covered)
    available_after_skip = len(pending)
    if config.limit:
        pending = pending[: config.limit]
    processed_keys = {jurisdiction_match_key(j.state, j.jurisdiction_name) for j in pending}

    working_rows = _drop_covered_working_rows(read_csv(WORKING_CSV, WORKING_COLUMNS), covered)
    rejected_rows = read_csv(REJECTED_CSV, REJECTED_COLUMNS)
    manual_all = load_manual_urls()
    stats = BuildStats()
    diagnostics_rows: list[dict[str, str]] = []
    candidates_found = 0
    rejected_added = 0

    with PageFetcher(
        delay=delay,
        force_refresh=False,
        use_fetch_cache=mode.harvest.use_fetch_cache,
        fetch_cache_ttl_days=mode.harvest.fetch_cache_ttl_days,
        connect_timeout=5.0,
        read_timeout=10.0,
        max_retries=2 if mode.deep else 2,
        planning_connect_timeout=8.0,
        planning_read_timeout=20.0,
        planning_max_retries=3,
    ) as fetcher:
        domain_cache = load_domain_cache()
        for j in pending:
            overrides = manual_urls_for_jurisdiction(manual_all, j.state, j.jurisdiction_name)
            working, rejected, diag_row = harvest_jurisdiction(
                j,
                fetcher,
                overrides,
                stats=stats,
                config=mode.harvest,
                domain_cache=domain_cache,
            )
            if diag_row:
                diagnostics_rows.append(diag_row)
            if working:
                working_rows = merge_working_row(working_rows, working)
                candidates_found += 1
            if rejected:
                rejected_rows = [
                    r
                    for r in rejected_rows
                    if not (
                        r["state"] == rejected["state"]
                        and r["jurisdiction_name"] == rejected["jurisdiction_name"]
                        and r["geography_type"] == rejected["geography_type"]
                    )
                ]
                rejected_rows.append(rejected)
                rejected_added += 1

    write_working_csv(working_rows)
    write_rejected_csv(rejected_rows)
    if diagnostics_rows:
        write_diagnostics_csv(diagnostics_rows)

    total, new_rows, prepare_stats = prepare_outreach(
        append_only=True,
        processed_jurisdiction_keys=processed_keys,
    )

    summary = HarvestRunSummary(
        run_started_at=started,
        run_completed_at=now_iso(),
        config_states=states,
        min_population=config.min_population,
        max_population=config.max_population,
        limit=config.limit,
        include_counties=config.include_counties,
        deep_mode=config.deep_mode,
        unsupported_states=unsupported,
        jurisdictions_seeded_count=seeded_count,
        jurisdictions_considered_count=seeded_count,
        jurisdictions_skipped_existing_count=len(skipped),
        jurisdictions_available_after_skip_count=available_after_skip,
        jurisdictions_processed_count=len(pending),
        candidates_found_count=candidates_found,
        candidates_added_count=new_rows,
        duplicates_skipped_count=prepare_stats.duplicate_after_crawl,
        duplicate_after_crawl_count=prepare_stats.duplicate_after_crawl,
        duplicate_email=prepare_stats.duplicate_email,
        duplicate_contact_jurisdiction=prepare_stats.duplicate_contact_jurisdiction,
        duplicate_source_name=prepare_stats.duplicate_source_name,
        duplicate_email_jurisdiction=prepare_stats.duplicate_email_jurisdiction,
        generic_skipped=prepare_stats.generic_skipped,
        rejected_count=rejected_added,
        total_outreach_contacts_after=total,
        processed_jurisdictions=[jurisdiction_record(j) for j in pending],
        skipped_existing_jurisdictions=[jurisdiction_record(j) for j in skipped],
        top_rejection_reasons=_top_rejection_reasons(diagnostics_rows),
    )
    analysis = analyze_harvest_run(summary, diagnostics_rows=diagnostics_rows)
    enrich_summary(summary, analysis)
    save_harvest_summary(summary)
    save_harvest_report(summary, analysis, diagnostics_rows=diagnostics_rows)
    summary.print_summary()
    return summary


# Backward-compatible alias for older imports/tests
FindMoreResult = HarvestRunSummary
