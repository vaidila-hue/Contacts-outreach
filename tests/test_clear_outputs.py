"""Tests for --clear-outputs behavior."""

import csv
from pathlib import Path

import pytest

from src.csv_utils import write_csv
from src.export_results import clear_output_csvs
from src.paths import OUTREACH_COLUMNS, REJECTED_COLUMNS, WORKING_COLUMNS
from src.run import run_build


@pytest.fixture
def tmp_outputs(tmp_path, monkeypatch):
    import src.export_results as exp
    import src.paths as paths
    import src.run as run_mod

    working = tmp_path / "prospects_working.csv"
    rejected = tmp_path / "prospects_rejected.csv"
    outreach = tmp_path / "outreach.csv"
    jurisdictions = tmp_path / "jurisdictions_filtered.csv"

    for mod in (paths, exp):
        monkeypatch.setattr(mod, "WORKING_CSV", working)
        monkeypatch.setattr(mod, "REJECTED_CSV", rejected)
        monkeypatch.setattr(mod, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(run_mod, "WORKING_CSV", working)
    monkeypatch.setattr(paths, "JURISDICTIONS_CSV", jurisdictions)

    write_csv(
        working,
        [{"state": "DE", "jurisdiction_name": "Old", "geography_type": "city", "population": "1",
          "county_name": "", "official_website_url": "", "planning_department_url": "",
          "contact_name": "", "contact_title": "", "email": "", "email_source_url": "",
          "candidate_source_url": "", "discovery_method": "",
          "latest_plan_year_found": "", "active_update_signal": "",
          "prospect_priority": "", "prospect_priority_reason": "",
          "jurisdiction_match_status": "", "jurisdiction_match_notes": "",
          "notes": "",
          "review_status": "pending", "outreach_status": "not_started", "_status": "done"}],
        WORKING_COLUMNS,
    )
    write_csv(
        rejected,
        [{"state": "DE", "jurisdiction_name": "Bear CDP", "geography_type": "place", "population": "1",
          "rejection_reason": "unclear_source", "email_found": "", "source_urls": "", "notes": "",
          "official_site_found": "no", "planning_page_found": "no", "pages_fetched_count": "0",
          "pdfs_fetched_count": "0", "raw_emails_found_count": "0", "generic_emails_found_count": "0",
          "candidate_titles_found_count": "0", "direct_email_candidates_count": "0",
          "best_rejection_reason": "unclear_source", "search_urls_found": "0",
          "search_urls_fetched": "0", "manual_url_used": "", "manual_url_result": "",
          "candidate_source_url": "", "email_source_url": "", "discovery_method": "",
          "jurisdiction_match_notes": "", "candidate_name": "", "candidate_title": ""}],
        REJECTED_COLUMNS,
    )
    write_csv(outreach, [{"contact_name": "X", "contact_title": "", "jurisdiction_name": "Y",
                          "state": "DE", "email": "x@y.gov", "email_source_url": "https://y.gov"}],
                OUTREACH_COLUMNS)
    return working, rejected, outreach


def test_clear_output_csvs_preserves_outreach_by_default(tmp_outputs):
    working, rejected, outreach = tmp_outputs
    clear_output_csvs()
    assert list(csv.DictReader(working.open(encoding="utf-8"))) == []
    assert list(csv.DictReader(rejected.open(encoding="utf-8"))) == []
    assert len(list(csv.DictReader(outreach.open(encoding="utf-8")))) == 1


def test_clear_output_csvs_clears_outreach_when_flagged(tmp_outputs):
    working, rejected, outreach = tmp_outputs
    clear_output_csvs(clear_outreach=True)
    assert list(csv.DictReader(outreach.open(encoding="utf-8"))) == []


def test_clear_outputs_rejects_export_only(tmp_outputs, capsys):
    import argparse

    args = argparse.Namespace(
        clear_outputs=True,
        export_only=True,
        states="DE",
        min_pop=20000,
        max_pop=100000,
        limit=0,
        delay=0,
        force_refresh=False,
    )
    with pytest.raises(SystemExit) as exc:
        run_build(args)
    assert exc.value.code == 1
    assert "cannot be used with --export-only" in capsys.readouterr().out
