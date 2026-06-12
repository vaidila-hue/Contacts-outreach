"""Tests for CRM overrides, tracking, dashboard, filters, harvest config, and UI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.harvest_config_store import HarvestConfigSettings, load_harvest_config, save_harvest_config
from src.outreach_crm import (
    FILTER_OPTIONS,
    apply_send_side_effects,
    compute_dashboard,
    duplicate_match,
    is_duplicate_of_any,
    merge_outreach_row,
    row_matches_filter,
)
from src.outreach_store import prepare_outreach, read_outreach_rows, update_outreach_rows, write_outreach_rows
from src.outreach_ui import create_app
from src.paths import WORKING_COLUMNS
from src.csv_utils import write_csv


@pytest.fixture
def crm_paths(tmp_path, monkeypatch):
    import src.paths as paths
    import src.harvest_config_store as hcs
    import src.outreach_store as store

    working = tmp_path / "prospects_working.csv"
    outreach = tmp_path / "outreach.csv"
    diagnostics = tmp_path / "harvest_diagnostics.csv"
    harvest_cfg = tmp_path / "harvest_config.json"

    monkeypatch.setattr(paths, "WORKING_CSV", working)
    monkeypatch.setattr(paths, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(paths, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(paths, "HARVEST_CONFIG_JSON", harvest_cfg)
    monkeypatch.setattr(store, "WORKING_CSV", working)
    monkeypatch.setattr(store, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(store, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(hcs, "HARVEST_CONFIG_JSON", harvest_cfg)
    return working, outreach, diagnostics, harvest_cfg


def _working_row(**overrides):
    row = {
        "state": "FL",
        "jurisdiction_name": "Fort Myers",
        "geography_type": "city",
        "population": "91730",
        "county_name": "",
        "official_website_url": "https://www.fortmyers.gov",
        "planning_department_url": "https://www.fortmyers.gov/planning",
        "contact_name": "Nicole DeVaughn",
        "contact_title": "Planning Manager",
        "email": "ndevaughn@fortmyers.gov",
        "email_source_url": "https://www.fortmyers.gov/planning",
        "candidate_source_url": "https://www.fortmyers.gov/planning",
        "discovery_method": "directory_harvest",
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
    row.update(overrides)
    return row


def _update(**fields):
    base = {
        "_orig_email": fields.pop("_orig_email", "ndevaughn@fortmyers.gov"),
        "_orig_state": fields.pop("_orig_state", "FL"),
        "_orig_jurisdiction_name": fields.pop("_orig_jurisdiction_name", "Fort Myers"),
        "email": "ndevaughn@fortmyers.gov",
        "state": "FL",
        "jurisdiction_name": "Fort Myers",
        "greeting_name": "Nicole",
    }
    base.update(fields)
    return base


def test_user_edit_sets_modified_flag_and_persists(crm_paths):
    working, _, _, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    update_outreach_rows([_update(contact_name="Nicole De Vaughn", contact_title="Director of Planning")])
    rows = read_outreach_rows()
    assert rows[0]["contact_name"] == "Nicole De Vaughn"
    assert rows[0]["contact_title"] == "Director of Planning"
    assert rows[0]["contact_name_modified"] == "yes"
    assert rows[0]["contact_title_modified"] == "yes"


def test_future_harvest_preserves_user_edits(crm_paths):
    working, _, _, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    update_outreach_rows([_update(contact_name="Nicole De Vaughn")])
    prepare_outreach()
    rows = read_outreach_rows()
    assert rows[0]["contact_name"] == "Nicole De Vaughn"


def test_reply_tracking_on_send():
    row = {"reply_status": "not_sent", "send_status": "drafted"}
    apply_send_side_effects(row)
    assert row["reply_status"] == "sent_no_reply"

    row2 = {"reply_status": "replied", "send_status": "drafted"}
    apply_send_side_effects(row2)
    assert row2["reply_status"] == "replied"


def test_meeting_and_follow_up_tracking(crm_paths):
    working, _, _, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    update_outreach_rows(
        [
            _update(
                meeting_requested="yes",
                meeting_scheduled_for="2026-06-15T14:00:00+00:00",
                follow_up_needed="yes",
                follow_up_at="2026-06-20",
                outreach_notes="Call back after conference",
            )
        ]
    )
    rows = read_outreach_rows()
    assert rows[0]["meeting_requested"] == "yes"
    assert rows[0]["follow_up_needed"] == "yes"
    assert rows[0]["tracking_modified"] == "yes"


def test_harvest_config_persistence(crm_paths):
    _, _, _, harvest_cfg = crm_paths
    settings = HarvestConfigSettings(
        states=["FL", "WI"],
        min_population=25000,
        max_population=90000,
        limit=25,
        include_counties=True,
        deep_mode=True,
    )
    save_harvest_config(settings)
    loaded = load_harvest_config()
    assert loaded.states == ["FL", "WI"]
    assert loaded.min_population == 25000
    assert loaded.include_counties is True
    assert harvest_cfg.exists()


def test_dashboard_metrics(crm_paths):
    working, _, _, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    rows = read_outreach_rows()
    rows[0]["approved"] = "yes"
    rows[0]["send_status"] = "sent"
    rows[0]["reply_status"] = "replied"
    rows[0]["reply_status"] = "replied"
    stats = compute_dashboard(rows)
    assert stats["total"] == 1
    assert stats["ready"] == 0
    assert stats["sent"] == 1
    assert stats["replies"] == 1
    assert "needs_follow_up" not in stats


def test_filters():
    row = {
        "approved": "yes",
        "send_status": "prepared",
        "reply_status": "replied",
        "follow_up_needed": "",
        "meeting_scheduled_for": "",
        "meeting_completed": "",
    }
    assert row_matches_filter(row, "ready")
    assert row_matches_filter({"send_status": "sent"}, "sent")
    assert row_matches_filter({"send_status": "sent", "approved": "yes"}, "ready") is False
    assert len(FILTER_OPTIONS) == 8


def test_duplicate_prevention():
    a = {
        "email": "a@b.gov",
        "state": "FL",
        "jurisdiction_name": "X",
        "contact_name": "Jane",
        "email_source_url": "https://x.gov/staff",
    }
    b = dict(a)
    assert duplicate_match(a, b)
    c = {"email": "other@b.gov", "state": "FL", "jurisdiction_name": "X", "contact_name": "Jane"}
    assert duplicate_match(a, c)
    assert is_duplicate_of_any(c, [a])


def test_prepare_preserves_outreach_history(crm_paths):
    working, _, _, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    update_outreach_rows([_update(reply_status="replied", outreach_notes="Great call")])
    prepare_outreach()
    rows = read_outreach_rows()
    assert rows[0]["reply_status"] == "replied"
    assert rows[0]["outreach_notes"] == "Great call"


def test_crm_ui_renders_dashboard_and_save(crm_paths):
    working, _, _, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Save changes" in resp.data
        assert b"Queue Ready Emails" in resp.data

        resp = client.post(
            "/save",
            data={
                "_orig_email": "ndevaughn@fortmyers.gov",
                "_orig_state": "FL",
                "_orig_jurisdiction_name": "Fort Myers",
                "greeting_name_0": "Nikki",
                "jurisdiction_type_0": "city",
                "population_0": "91730",
                "jurisdiction_name_0": "Fort Myers",
                "state_0": "FL",
                "contact_name_0": "Nicole De Vaughn",
                "contact_title_0": "Director",
                "email_0": "ndevaughn@fortmyers.gov",
                "jurisdiction_url_0": "https://www.fortmyers.gov",
                "email_source_url_0": "https://www.fortmyers.gov/planning",
                "reply_status_0": "replied",
                "first_reply_at_0": "",
                "follow_up_at_0": "",
                "outreach_notes_0": "note",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
    rows = read_outreach_rows()
    assert rows[0]["greeting_name"] == "Nikki"
    assert rows[0]["contact_name"] == "Nicole De Vaughn"
    assert rows[0]["reply_status"] == "replied"


def test_harvest_modal_save_route(crm_paths):
    _, _, _, harvest_cfg = crm_paths
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.post(
            "/harvest-config/save",
            data={
                "states": ["FL", "OR"],
                "min_population": "20000",
                "max_population": "100000",
                "limit": "100",
                "include_counties": "yes",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
    data = json.loads(harvest_cfg.read_text(encoding="utf-8"))
    assert "FL" in data["states"]
    assert data["include_counties"] is True


def test_gitignore_excludes_secrets_and_data():
    gitignore = Path(__file__).resolve().parents[1] / ".gitignore"
    text = gitignore.read_text(encoding="utf-8")
    for pattern in (
        "credentials.json",
        "token.json",
        "data/outreach.csv",
        "data/prospects_working.csv",
        ".env",
        "__pycache__",
    ):
        assert pattern in text


def test_example_files_exist():
    root = Path(__file__).resolve().parents[1]
    assert (root / "data/examples/outreach.example.csv").exists()
    assert (root / "data/examples/prospects_working.example.csv").exists()
