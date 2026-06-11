"""Tests for export-only workflow."""

import csv
from pathlib import Path

import pytest

from src.export_results import export_only, export_outreach
from src.paths import OUTREACH_CSV, WORKING_CSV, WORKING_COLUMNS
from src.csv_utils import write_csv


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    import src.paths as paths
    import src.export_results as exp
    import src.outreach_store as store

    working = tmp_path / "prospects_working.csv"
    outreach = tmp_path / "outreach.csv"
    diagnostics = tmp_path / "harvest_diagnostics.csv"
    monkeypatch.setattr(paths, "WORKING_CSV", working)
    monkeypatch.setattr(paths, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(paths, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(exp, "WORKING_CSV", working)
    monkeypatch.setattr(exp, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(store, "WORKING_CSV", working)
    monkeypatch.setattr(store, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(store, "DIAGNOSTICS_CSV", diagnostics)
    return working, outreach


def test_no_auto_approve_in_export(tmp_data):
    working, outreach = tmp_data
    rows = [
        {
            "state": "RI",
            "jurisdiction_name": "Providence",
            "geography_type": "city",
            "population": "190000",
            "county_name": "",
            "official_website_url": "",
            "planning_department_url": "",
            "contact_name": "Jane Smith",
            "contact_title": "Planning Director",
            "email": "jane.smith@providence.gov",
            "email_source_url": "https://providence.gov/staff",
            "candidate_source_url": "",
            "discovery_method": "page_extraction",
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
    ]
    write_csv(working, rows, WORKING_COLUMNS)
    result = export_outreach(rows)
    assert len(result) == 1
    assert result[0]["approved"] == ""
    assert result[0]["send_status"] == "prepared"


def test_export_only_approved_with_source_url(tmp_data):
    working, outreach = tmp_data
    rows = [
        {
            "state": "RI",
            "jurisdiction_name": "Warwick",
            "geography_type": "city",
            "population": "82000",
            "county_name": "",
            "official_website_url": "",
            "planning_department_url": "",
            "contact_name": "John Adams",
            "contact_title": "Community Development Director",
            "email": "john.adams@warwick.gov",
            "email_source_url": "https://warwick.gov/planning/staff.pdf",
            "candidate_source_url": "https://warwick.gov/planning/staff.pdf",
            "discovery_method": "pdf_extraction",
            "latest_plan_year_found": "",
            "active_update_signal": "",
            "prospect_priority": "medium",
            "prospect_priority_reason": "no plan year found",
            "jurisdiction_match_status": "matched",
            "jurisdiction_match_notes": "",
            "review_status": "approved",
            "outreach_status": "not_started",
            "_status": "done",
        }
    ]
    write_csv(working, rows, WORKING_COLUMNS)
    total, count = export_only()
    assert count == 1
    assert outreach.exists()
    with outreach.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        out_rows = list(reader)
    assert len(out_rows) == 1
    assert out_rows[0]["email_source_url"] == "https://warwick.gov/planning/staff.pdf"
    assert out_rows[0]["send_status"] == "prepared"
