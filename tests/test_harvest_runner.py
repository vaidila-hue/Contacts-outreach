"""Tests for Find More Contacts harvest skip logic and summaries."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.census_seed import Jurisdiction
from src.harvest_runner import run_find_more_contacts, _drop_covered_working_rows
from src.harvest_summary import (
    HarvestRunSummary,
    build_covered_jurisdiction_set,
    partition_jurisdictions,
    represented_jurisdiction_keys,
    unsupported_config_states,
)
from src.harvest_config_store import HarvestConfigSettings
from src.jurisdiction_utils import jurisdiction_match_key, normalize_jurisdiction_key_name
from src.outreach_store import prepare_outreach, read_outreach_rows, write_outreach_rows
from src.outreach_ui import create_app
from src.paths import (
    DIAGNOSTICS_CSV,
    LAST_HARVEST_SUMMARY_JSON,
    OUTREACH_COLUMNS,
    REJECTED_CSV,
    WORKING_COLUMNS,
    WORKING_CSV,
)
from src.csv_utils import read_csv, write_csv


@pytest.fixture
def harvest_paths(tmp_path, monkeypatch):
    import src.paths as paths
    import src.harvest_runner as hr
    import src.harvest_summary as hs
    import src.outreach_store as store
    import src.harvest_config_store as hcs

    working = tmp_path / "prospects_working.csv"
    outreach = tmp_path / "outreach.csv"
    rejected = tmp_path / "rejected.csv"
    diagnostics = tmp_path / "diagnostics.csv"
    harvest_cfg = tmp_path / "harvest_config.json"
    summary = tmp_path / "last_harvest_summary.json"
    jurisdictions = tmp_path / "jurisdictions.csv"

    monkeypatch.setattr(paths, "WORKING_CSV", working)
    monkeypatch.setattr(paths, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(paths, "REJECTED_CSV", rejected)
    monkeypatch.setattr(paths, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(paths, "HARVEST_CONFIG_JSON", harvest_cfg)
    monkeypatch.setattr(paths, "LAST_HARVEST_SUMMARY_JSON", summary)
    monkeypatch.setattr(paths, "JURISDICTIONS_CSV", jurisdictions)
    monkeypatch.setattr(store, "WORKING_CSV", working)
    monkeypatch.setattr(store, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(store, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(hcs, "HARVEST_CONFIG_JSON", harvest_cfg)
    monkeypatch.setattr(hs, "LAST_HARVEST_SUMMARY_JSON", summary)
    import src.harvest_runner as hr
    import src.export_results as er

    monkeypatch.setattr(hr, "WORKING_CSV", working)
    monkeypatch.setattr(hr, "REJECTED_CSV", rejected)
    monkeypatch.setattr(er, "WORKING_CSV", working)
    monkeypatch.setattr(er, "REJECTED_CSV", rejected)
    monkeypatch.setattr(er, "DIAGNOSTICS_CSV", diagnostics)
    return working, outreach, summary, harvest_cfg


def _j(state: str, name: str, pop: int = 50000) -> Jurisdiction:
    return Jurisdiction(
        state=state,
        jurisdiction_name=name,
        geography_type="city",
        population=pop,
    )


def test_represented_jurisdiction_keys_from_outreach():
    rows = [{"state": "FL", "jurisdiction_name": "Miami Beach", "email": "a@b.gov"}]
    assert build_covered_jurisdiction_set(rows) == {("FL", "miami beach")}


def test_empty_outreach_row_not_covered():
    rows = [{"state": "CO", "jurisdiction_name": "Denver", "email": "", "contact_name": ""}]
    assert build_covered_jurisdiction_set(rows) == set()


def test_contact_name_only_counts_as_covered():
    rows = [{"state": "CO", "jurisdiction_name": "Denver", "email": "", "contact_name": "Jane Planner"}]
    assert build_covered_jurisdiction_set(rows) == {("CO", "denver")}


def test_normalize_saint_and_city_town():
    assert normalize_jurisdiction_key_name("St. Louis") == "saint louis"
    assert jurisdiction_match_key("MO", "St. Louis city") == jurisdiction_match_key("MO", "Saint Louis")


def test_partition_skips_represented_jurisdictions():
    all_j = [_j("FL", "Miami Beach"), _j("TX", "Austin"), _j("CA", "Oakland")]
    covered = {("FL", "miami beach")}
    pending, skipped = partition_jurisdictions(all_j, covered)
    assert len(skipped) == 1
    assert skipped[0].jurisdiction_name == "Miami Beach"
    assert [j.jurisdiction_name for j in pending] == ["Austin", "Oakland"]


def test_partition_dedupes_city_and_town_same_name():
    all_j = [_j("CT", "Danbury", pop=86086), Jurisdiction("CT", "Danbury", "town", 86086)]
    covered = {("CT", "danbury")}
    pending, skipped = partition_jurisdictions(all_j, covered)
    assert len(skipped) == 1
    assert len(pending) == 0


def test_limit_applied_after_skip():
    all_j = [_j("FL", f"City{i}") for i in range(5)] + [_j("TX", f"Town{i}") for i in range(5)]
    covered = {("FL", f"city{i}") for i in range(5)}
    pending, skipped = partition_jurisdictions(all_j, covered)
    limited = pending[:3]
    assert len(skipped) == 5
    assert len(limited) == 3
    assert all(j.state == "TX" for j in limited)


def test_unsupported_config_states():
    assert "CA" not in unsupported_config_states(["FL", "OR"])
    assert "ZZ" in unsupported_config_states(["FL", "ZZ"])


def test_prepare_reports_duplicate_categories(harvest_paths):
    working, outreach, _, _ = harvest_paths
    row = {col: "" for col in OUTREACH_COLUMNS}
    row.update(
        {
            "email": "planner@city.gov",
            "state": "TX",
            "jurisdiction_name": "Austin",
            "contact_name": "Jane Planner",
            "greeting_name": "Jane",
            "send_status": "prepared",
        }
    )
    write_outreach_rows([row])
    write_csv(
        working,
        [
            {
                "state": "TX",
                "jurisdiction_name": "Austin",
                "geography_type": "city",
                "population": "50000",
                "county_name": "",
                "official_website_url": "https://austin.gov",
                "planning_department_url": "",
                "contact_name": "Jane Planner",
                "contact_title": "Director",
                "email": "planner@city.gov",
                "email_source_url": "https://austin.gov/staff",
                "candidate_source_url": "",
                "discovery_method": "test",
                "latest_plan_year_found": "",
                "active_update_signal": "",
                "prospect_priority": "",
                "prospect_priority_reason": "",
                "jurisdiction_match_status": "matched",
                "jurisdiction_match_notes": "",
                "notes": "",
                "review_status": "pending",
                "outreach_status": "not_started",
                "_status": "done",
            }
        ],
        WORKING_COLUMNS,
    )
    total, new_count, stats = prepare_outreach(append_only=True)
    assert total == 1
    assert new_count == 0
    assert stats.duplicate_email >= 1 or stats.duplicate_contact_jurisdiction >= 1


def test_run_find_more_skips_existing_and_writes_summary(harvest_paths, monkeypatch):
    working, outreach, summary_path, harvest_cfg = harvest_paths
    existing = {col: "" for col in OUTREACH_COLUMNS}
    existing.update(
        {
            "state": "FL",
            "jurisdiction_name": "Miami Beach",
            "email": "old@city.gov",
            "contact_name": "Old Contact",
            "send_status": "prepared",
        }
    )
    write_outreach_rows([existing])

    config = HarvestConfigSettings(
        states=["FL", "TX"],
        min_population=20000,
        max_population=100000,
        limit=2,
        include_counties=False,
        deep_mode=False,
    )
    from src.harvest_config_store import save_harvest_config

    save_harvest_config(config)

    seeded = [
        _j("FL", "Miami Beach"),
        _j("FL", "Kissimmee"),
        _j("TX", "Austin"),
        _j("TX", "Plano"),
    ]

    harvested_names: list[str] = []

    def fake_harvest(j, *args, **kwargs):
        harvested_names.append(j.jurisdiction_name)
        if j.jurisdiction_name == "Austin":
            working_row = {
                "state": j.state,
                "jurisdiction_name": j.jurisdiction_name,
                "geography_type": "city",
                "population": str(j.population),
                "county_name": "",
                "official_website_url": "https://austin.gov",
                "planning_department_url": "",
                "contact_name": "New Person",
                "contact_title": "Planner",
                "email": "newperson@austin.gov",
                "email_source_url": "https://austin.gov/plan",
                "candidate_source_url": "",
                "discovery_method": "test",
                "latest_plan_year_found": "",
                "active_update_signal": "",
                "prospect_priority": "",
                "prospect_priority_reason": "",
                "jurisdiction_match_status": "matched",
                "jurisdiction_match_notes": "",
                "notes": "",
                "review_status": "pending",
                "outreach_status": "not_started",
                "_status": "done",
            }
            diag = {
                "state": j.state,
                "jurisdiction_name": j.jurisdiction_name,
                "geography_type": "city",
                "population": str(j.population),
                "official_domain": "austin.gov",
                "planning_pages_found": "1",
                "directory_pages_found": "0",
                "staff_links_found": "0",
                "profile_links_followed": "0",
                "mailto_links_found": "0",
                "emails_found": "1",
                "candidate_titles_found": "1",
                "pages_fetched": "1",
                "search_queries_run": "1",
                "found_contact": "yes",
                "final_rejection_reason": "",
                "elapsed_seconds": "1",
                "cache_hits": "0",
                "cache_misses": "0",
                "profile_pages_followed": "0",
                "early_stop": "yes",
                "max_page_limit_hit": "no",
                "timeout_count": "0",
                "fetch_error_count": "0",
                "resolver_method": "search_official",
                "planning_fallback_used": "no",
            }
            return working_row, None, diag
        diag = {
            "state": j.state,
            "jurisdiction_name": j.jurisdiction_name,
            "geography_type": "city",
            "population": str(j.population),
            "official_domain": "",
            "planning_pages_found": "0",
            "directory_pages_found": "0",
            "staff_links_found": "0",
            "profile_links_followed": "0",
            "mailto_links_found": "0",
            "emails_found": "0",
            "candidate_titles_found": "0",
            "pages_fetched": "0",
            "search_queries_run": "0",
            "found_contact": "no",
            "final_rejection_reason": "no_official_site_found",
            "elapsed_seconds": "1",
            "cache_hits": "0",
            "cache_misses": "0",
            "profile_pages_followed": "0",
            "early_stop": "no",
            "max_page_limit_hit": "no",
            "timeout_count": "0",
            "fetch_error_count": "0",
        }
        return None, None, diag

    with patch("src.harvest_runner.seed_jurisdictions", return_value=(seeded, None)):
        with patch("src.harvest_runner.harvest_jurisdiction", side_effect=fake_harvest):
            with patch("src.harvest_runner.PageFetcher") as mock_fetcher:
                mock_fetcher.return_value.__enter__.return_value = object()
                result = run_find_more_contacts()

    assert "Miami Beach" not in harvested_names
    assert result.jurisdictions_skipped_existing_count == 1
    assert result.jurisdictions_available_after_skip_count == 3
    assert result.jurisdictions_processed_count == 2
    assert result.processed_jurisdictions[0]["jurisdiction_name"] == "Kissimmee"
    assert result.candidates_added_count == 1
    assert summary_path.exists()
    saved = json.loads(summary_path.read_text(encoding="utf-8"))
    assert saved["candidates_added_count"] == 1
    rows = read_outreach_rows()
    assert len(rows) == 2


def test_harvest_summary_message_explains_zero_contacts():
    summary = HarvestRunSummary(
        jurisdictions_processed_count=60,
        jurisdictions_skipped_existing_count=38,
        candidates_added_count=0,
        top_rejection_reasons=[
            {"reason": "no_official_site_found", "count": 29},
            {"reason": "(found contact)", "count": 13},
            {"reason": "no_planning_contact_found", "count": 11},
        ],
        duplicates_skipped_count=13,
    )
    msg = summary.format_message()
    assert "No new contacts added" in msg
    assert "no official site found" in msg.lower() or "29" in msg


def test_drop_covered_working_rows():
    covered = {("CO", "denver")}
    rows = [
        {"state": "CO", "jurisdiction_name": "Denver", "email": "a@denver.gov"},
        {"state": "TX", "jurisdiction_name": "Austin", "email": "b@austin.gov"},
    ]
    kept = _drop_covered_working_rows(rows, covered)
    assert len(kept) == 1
    assert kept[0]["jurisdiction_name"] == "Austin"


def test_stale_covered_working_not_counted_as_duplicate_after_crawl(harvest_paths):
    working, outreach, _, _ = harvest_paths
    crm = {col: "" for col in OUTREACH_COLUMNS}
    crm.update(
        {
            "state": "CO",
            "jurisdiction_name": "Denver",
            "email": "planner@denver.gov",
            "contact_name": "Denver Planner",
            "send_status": "prepared",
        }
    )
    write_outreach_rows([crm])
    write_csv(
        working,
        [
            {
                "state": "CO",
                "jurisdiction_name": "Denver",
                "geography_type": "city",
                "population": "700000",
                "county_name": "",
                "official_website_url": "https://denver.gov",
                "planning_department_url": "",
                "contact_name": "Denver Planner",
                "contact_title": "Director",
                "email": "planner@denver.gov",
                "email_source_url": "https://denver.gov/plan",
                "candidate_source_url": "",
                "discovery_method": "test",
                "latest_plan_year_found": "",
                "active_update_signal": "",
                "prospect_priority": "",
                "prospect_priority_reason": "",
                "jurisdiction_match_status": "matched",
                "jurisdiction_match_notes": "",
                "notes": "",
                "review_status": "pending",
                "outreach_status": "not_started",
                "_status": "done",
            }
        ],
        WORKING_COLUMNS,
    )
    covered = build_covered_jurisdiction_set([crm])
    working_rows = _drop_covered_working_rows(read_csv(working, WORKING_COLUMNS), covered)
    write_csv(working, working_rows, WORKING_COLUMNS)
    total, new_count, stats = prepare_outreach(
        append_only=True,
        processed_jurisdiction_keys={("TX", "austin")},
    )
    assert total == 1
    assert new_count == 0
    assert stats.duplicate_after_crawl == 0


def test_duplicate_after_crawl_counted_for_processed_jurisdiction(harvest_paths):
    working, outreach, _, _ = harvest_paths
    crm = {col: "" for col in OUTREACH_COLUMNS}
    crm.update(
        {
            "state": "TX",
            "jurisdiction_name": "Austin",
            "email": "shared@example.gov",
            "contact_name": "Existing",
            "send_status": "prepared",
        }
    )
    write_outreach_rows([crm])
    write_csv(
        working,
        [
            {
                "state": "TX",
                "jurisdiction_name": "Plano",
                "geography_type": "city",
                "population": "300000",
                "county_name": "",
                "official_website_url": "https://plano.gov",
                "planning_department_url": "",
                "contact_name": "Other Person",
                "contact_title": "Planner",
                "email": "shared@example.gov",
                "email_source_url": "https://plano.gov/staff",
                "candidate_source_url": "",
                "discovery_method": "test",
                "latest_plan_year_found": "",
                "active_update_signal": "",
                "prospect_priority": "",
                "prospect_priority_reason": "",
                "jurisdiction_match_status": "matched",
                "jurisdiction_match_notes": "",
                "notes": "",
                "review_status": "pending",
                "outreach_status": "not_started",
                "_status": "done",
            }
        ],
        WORKING_COLUMNS,
    )
    _, _, stats = prepare_outreach(
        append_only=True,
        processed_jurisdiction_keys={jurisdiction_match_key("TX", "Plano")},
    )
    assert stats.duplicate_after_crawl == 1
    assert stats.duplicate_email == 1


def test_ui_shows_harvest_summary_from_file(harvest_paths):
    _, _, summary_path, _ = harvest_paths
    summary = HarvestRunSummary(
        config_states=["FL"],
        min_population=20000,
        max_population=90000,
        limit=60,
        candidates_added_count=0,
        jurisdictions_processed_count=60,
        top_rejection_reasons=[{"reason": "no_official_site_found", "count": 29}],
    )
    summary_path.write_text(json.dumps(summary.__dict__, indent=2), encoding="utf-8")
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/?harvest=1")
        html = resp.data.decode("utf-8")
        assert "Harvest complete" in html
        assert "no_official_site_found" in html
        assert "Last harvest" in html
        assert "harvest-panel" not in html
        assert "Recommendation" not in html
