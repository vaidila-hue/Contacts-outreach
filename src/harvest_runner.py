"""Run contact harvest from UI harvest config (append mode)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from src.build_mode import BuildMode, BuildStats, resolve_delay
from src.census_seed import seed_jurisdictions, save_jurisdictions
from src.directory_harvest import harvest_jurisdiction
from src.export_results import merge_working_row, write_diagnostics_csv, write_rejected_csv, write_working_csv
from src.fetch_pages import PageFetcher
from src.harvest_config_store import HarvestConfigSettings, load_harvest_config
from src.manual_urls import load_manual_urls, manual_urls_for_jurisdiction
from src.outreach_store import prepare_outreach
from src.paths import DIAGNOSTICS_COLUMNS, REJECTED_COLUMNS, REJECTED_CSV, WORKING_COLUMNS, WORKING_CSV
from src.csv_utils import read_csv
from src.directory_harvest import sort_jurisdictions_for_harvest
from src.domain_cache import load_domain_cache


@dataclass
class FindMoreResult:
    jurisdictions_processed: int
    contacts_found: int
    new_outreach_rows: int
    total_outreach_rows: int


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


def run_find_more_contacts() -> FindMoreResult:
    """Harvest using saved config; append working rows; merge new outreach contacts only."""
    config = load_harvest_config()
    args = _args_from_config(config)
    mode = BuildMode.from_args(args)
    delay = resolve_delay(args)

    states = [s.strip().upper() for s in config.states if s.strip()]
    jurisdictions, _ = seed_jurisdictions(states, config.min_population, config.max_population)
    jurisdictions = sort_jurisdictions_for_harvest(
        jurisdictions, include_counties=config.include_counties
    )
    save_jurisdictions(jurisdictions)
    pending = jurisdictions[: config.limit] if config.limit else jurisdictions

    working_rows = read_csv(WORKING_CSV, WORKING_COLUMNS)
    rejected_rows = read_csv(REJECTED_CSV, REJECTED_COLUMNS)
    manual_all = load_manual_urls()
    stats = BuildStats()
    diagnostics_rows: list[dict[str, str]] = []
    found = 0

    with PageFetcher(
        delay=delay,
        force_refresh=False,
        use_fetch_cache=mode.harvest.use_fetch_cache,
        fetch_cache_ttl_days=mode.harvest.fetch_cache_ttl_days,
        connect_timeout=5.0,
        read_timeout=10.0,
        max_retries=2 if mode.deep else 1,
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
                found += 1
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

    write_working_csv(working_rows)
    write_rejected_csv(rejected_rows)
    if diagnostics_rows:
        write_diagnostics_csv(diagnostics_rows)

    total, new_rows = prepare_outreach(append_only=True)
    return FindMoreResult(
        jurisdictions_processed=len(pending),
        contacts_found=found,
        new_outreach_rows=new_rows,
        total_outreach_rows=total,
    )
