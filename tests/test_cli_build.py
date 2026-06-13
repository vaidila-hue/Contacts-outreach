"""Regression tests for CLI build outreach preservation and harvest summary."""

from __future__ import annotations

import argparse
import csv
import json
from unittest.mock import MagicMock, patch

import pytest

from src.census_seed import Jurisdiction, SeedStats
from src.csv_utils import write_csv
from src.export_results import export_only
from src.harvest_report import format_harvest_dashboard
from src.harvest_summary import load_harvest_summary
from src.outreach_ui import create_app
from src.paths import (
    DIAGNOSTICS_COLUMNS,
    LAST_HARVEST_SUMMARY_JSON,
    OUTREACH_COLUMNS,
    WORKING_COLUMNS,
)
from src.run import run_build


@pytest.fixture
def cli_build_paths(tmp_path, monkeypatch):
    import src.export_results as exp
    import src.harvest_report as hr
    import src.harvest_summary as hs
    import src.outreach_store as store
    import src.paths as paths
    import src.run as run_mod

    working = tmp_path / "prospects_working.csv"
    rejected = tmp_path / "prospects_rejected.csv"
    outreach = tmp_path / "outreach.csv"
    diagnostics = tmp_path / "harvest_diagnostics.csv"
    jurisdictions = tmp_path / "jurisdictions_filtered.csv"
    summary = tmp_path / "last_harvest_summary.json"

    monkeypatch.setattr(paths, "WORKING_CSV", working)
    monkeypatch.setattr(paths, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(paths, "REJECTED_CSV", rejected)
    monkeypatch.setattr(paths, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(paths, "LAST_HARVEST_SUMMARY_JSON", summary)
    monkeypatch.setattr(paths, "JURISDICTIONS_CSV", jurisdictions)

    monkeypatch.setattr(exp, "WORKING_CSV", working)
    monkeypatch.setattr(exp, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(exp, "REJECTED_CSV", rejected)
    monkeypatch.setattr(exp, "DIAGNOSTICS_CSV", diagnostics)

    monkeypatch.setattr(store, "WORKING_CSV", working)
    monkeypatch.setattr(store, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(store, "DIAGNOSTICS_CSV", diagnostics)

    monkeypatch.setattr(hs, "LAST_HARVEST_SUMMARY_JSON", summary)

    monkeypatch.setattr(hr, "DIAGNOSTICS_CSV", diagnostics)

    monkeypatch.setattr(run_mod, "WORKING_CSV", working)
    monkeypatch.setattr(run_mod, "REJECTED_CSV", rejected)
    monkeypatch.setattr(run_mod, "DIAGNOSTICS_CSV", diagnostics)
    return working, outreach, diagnostics, summary, jurisdictions


def _build_args(**overrides):
    defaults = dict(
        clear_outputs=False,
        clear_outreach=False,
        export_only=False,
        states="DE",
        min_pop=20000,
        max_pop=100000,
        limit=0,
        delay=0,
        force_refresh=False,
        include_counties=False,
        deep=False,
        include_pdfs=False,
        include_plan_signals=False,
        person_first=False,
        max_pages_per_jurisdiction=None,
        max_profile_pages_per_jurisdiction=None,
        max_directory_pages_per_jurisdiction=None,
        max_search_queries_per_jurisdiction=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _seed_outreach(outreach_path):
    write_csv(
        outreach_path,
        [
            {
                "contact_name": "Pat Planner",
                "contact_title": "Director",
                "jurisdiction_name": "Wilmington",
                "state": "DE",
                "email": "pat@wilmingtonde.gov",
                "email_source_url": "https://wilmingtonde.gov",
            }
        ],
        OUTREACH_COLUMNS,
    )


@patch("src.run.verify_dependencies")
@patch("src.run.load_dotenv")
@patch("src.run.PageFetcher")
@patch("src.run._discover_jurisdiction")
@patch("src.run.seed_jurisdictions")
def test_normal_build_preserves_outreach_csv(
    mock_seed,
    mock_discover,
    mock_fetcher_cls,
    mock_dotenv,
    mock_verify,
    cli_build_paths,
):
    working, outreach, diagnostics, summary, jurisdictions = cli_build_paths
    _seed_outreach(outreach)

    mock_fetcher_cls.return_value.__enter__.return_value = MagicMock()
    mock_fetcher_cls.return_value.__exit__.return_value = None

    j = Jurisdiction("DE", "Dover", "city", 39000)
    mock_seed.return_value = ([j], SeedStats())
    mock_discover.return_value = (None, None, None, {"final_rejection_reason": "no_planning_contact_found"})

    run_build(_build_args(limit=1))

    rows = list(csv.DictReader(outreach.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["email"] == "pat@wilmingtonde.gov"


@patch("src.run.verify_dependencies")
@patch("src.run.load_dotenv")
@patch("src.run.PageFetcher")
@patch("src.run._discover_jurisdiction")
@patch("src.run.seed_jurisdictions")
def test_build_saves_harvest_summary_for_dashboard(
    mock_seed,
    mock_discover,
    mock_fetcher_cls,
    mock_dotenv,
    mock_verify,
    cli_build_paths,
):
    working, outreach, diagnostics, summary, jurisdictions = cli_build_paths
    _seed_outreach(outreach)

    mock_fetcher_cls.return_value.__enter__.return_value = MagicMock()
    mock_fetcher_cls.return_value.__exit__.return_value = None

    j1 = Jurisdiction("DE", "Dover", "city", 39000)
    j2 = Jurisdiction("DE", "Newark", "city", 31000)
    mock_seed.return_value = ([j1, j2], SeedStats())
    working_row = {
        "state": "DE",
        "jurisdiction_name": "Dover",
        "geography_type": "city",
        "population": "39000",
        "county_name": "",
        "official_website_url": "",
        "planning_department_url": "",
        "contact_name": "Alex",
        "contact_title": "Planner",
        "email": "alex@dover.gov",
        "email_source_url": "https://dover.gov",
        "candidate_source_url": "",
        "discovery_method": "",
        "latest_plan_year_found": "",
        "active_update_signal": "",
        "prospect_priority": "",
        "prospect_priority_reason": "",
        "jurisdiction_match_status": "",
        "jurisdiction_match_notes": "",
        "notes": "",
        "review_status": "pending",
        "outreach_status": "not_started",
        "_status": "done",
    }
    mock_discover.side_effect = [
        (working_row, None, None, {"final_rejection_reason": "(found contact)"}),
        (None, {"state": "DE", "jurisdiction_name": "Newark", "geography_type": "city", "rejection_reason": "no_official_site_found"}, None, {"final_rejection_reason": "no_official_site_found"}),
    ]

    run_build(_build_args(limit=2))

    saved = load_harvest_summary()
    assert saved is not None
    assert saved.run_source == "cli_build"
    assert saved.jurisdictions_processed_count == 2
    assert saved.candidates_added_count == 1
    assert saved.diagnostics_row_count == 2

    dash = format_harvest_dashboard(saved)
    assert dash["jurisdictions_processed"] == "2"
    assert dash["new_contacts"] == "1"

    app = create_app()
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Processed" in resp.data
    assert b">2<" in resp.data or b"2</strong>" in resp.data


@patch("src.run.verify_dependencies")
@patch("src.run.load_dotenv")
@patch("src.run.export_only")
def test_export_only_does_not_overwrite_harvest_summary(
    mock_export_only,
    mock_dotenv,
    mock_verify,
    cli_build_paths,
):
    _, outreach, _, summary, _ = cli_build_paths
    summary.write_text(
        json.dumps(
            {
                "run_completed_at": "2026-06-11T23:17:42+00:00",
                "jurisdictions_processed_count": 60,
                "candidates_added_count": 2,
                "run_source": "cli_build",
                "diagnostics_row_count": 60,
            }
        ),
        encoding="utf-8",
    )
    mock_export_only.return_value = (17, 17)

    run_build(_build_args(export_only=True))

    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["jurisdictions_processed_count"] == 60
    assert data["candidates_added_count"] == 2


def test_clear_outreach_flag_empties_outreach(cli_build_paths):
    from src.export_results import clear_output_csvs

    _, outreach, _, _, _ = cli_build_paths
    _seed_outreach(outreach)
    clear_output_csvs(clear_outreach=True)
    assert list(csv.DictReader(outreach.open(encoding="utf-8"))) == []
