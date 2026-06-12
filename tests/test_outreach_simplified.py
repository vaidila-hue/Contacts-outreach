"""Tests for simplified CRM workflow: Ready, Send Ready, messages, filters."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pytest

from src.gmail_client import MockGmailService
from src.outreach_cli import run_outreach_send_ready
from src.outreach_crm import FILTER_OPTIONS, format_sent_date_display, is_ready, row_matches_filter
from src.outreach_store import (
    delete_outreach_row,
    prepare_outreach,
    read_outreach_rows,
    ready_send_candidates,
    save_default_message_for_outreach,
    save_row_message,
    write_outreach_rows,
)
from src.outreach_template import load_default_message, render_row_email
from src.outreach_ui import create_app
from src.paths import WORKING_COLUMNS
from src.csv_utils import write_csv


@pytest.fixture
def crm_paths(tmp_path, monkeypatch):
    import src.paths as paths
    import src.outreach_store as store
    import src.outreach_template as ot

    working = tmp_path / "prospects_working.csv"
    outreach = tmp_path / "outreach.csv"
    diagnostics = tmp_path / "harvest_diagnostics.csv"
    default_msg = tmp_path / "default_message.json"

    monkeypatch.setattr(paths, "WORKING_CSV", working)
    monkeypatch.setattr(paths, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(paths, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(paths, "DEFAULT_MESSAGE_JSON", default_msg)
    monkeypatch.setattr(store, "WORKING_CSV", working)
    monkeypatch.setattr(store, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(store, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(ot, "DEFAULT_MESSAGE_JSON", default_msg)
    return working, outreach, default_msg


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


def test_ready_filter_excludes_sent(crm_paths):
    row_ready = {"approved": "yes", "send_status": "prepared"}
    row_sent = {"approved": "yes", "send_status": "sent"}
    assert row_matches_filter(row_ready, "ready")
    assert not row_matches_filter(row_sent, "ready")
    assert is_ready(row_ready)
    assert not is_ready(row_sent)


def test_sent_filter_includes_sent_only():
    assert row_matches_filter({"send_status": "sent"}, "sent")
    assert not row_matches_filter({"send_status": "prepared", "approved": "yes"}, "sent")


def test_filters_simplified():
    labels = [label for _, label in FILTER_OPTIONS]
    assert "Ready" in labels
    assert "Not Sent" in labels
    assert "Not Approved" not in labels
    assert "Prepared" not in labels
    assert "Drafted" not in labels
    assert "Needs Follow-Up" not in labels


def test_not_sent_filter():
    assert row_matches_filter({"send_status": "prepared", "approved": ""}, "not_sent")
    assert row_matches_filter({"send_status": "prepared", "approved": "yes"}, "not_sent")
    assert not row_matches_filter({"send_status": "sent"}, "not_sent")
    assert row_matches_filter({"send_status": "prepared", "approved": "yes"}, "ready")
    assert not row_matches_filter({"send_status": "prepared", "approved": ""}, "ready")


def test_sent_date_display_format():
    iso = "2026-06-11T14:30:00+00:00"
    assert format_sent_date_display(iso) == "06/11/26"
    assert format_sent_date_display("") == ""


def test_send_ready_queues_only_ready_unsent(crm_paths):
    working, _, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    rows = read_outreach_rows()
    rows[0]["approved"] = "yes"
    write_outreach_rows(rows)

    service = MockGmailService()
    args = argparse.Namespace(delay_seconds=0)
    assert run_outreach_send_ready(args, service=service) == 0
    after = read_outreach_rows()
    assert after[0]["send_status"] == "queued"
    assert after[0]["approved"] == "yes"
    assert service.sent == []


def test_sent_rows_not_resent(crm_paths):
    working, _, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    rows = read_outreach_rows()
    rows[0].update(
        {
            "approved": "yes",
            "send_status": "sent",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "gmail_message_id": "msg-1",
        }
    )
    write_outreach_rows(rows)
    assert ready_send_candidates() == []


def test_default_message_save_persists(crm_paths):
    crm_paths
    saved = save_default_message_for_outreach("New subject", "Hi {greeting_name},\n\nCustom body.")
    assert saved.subject == "New subject"
    assert load_default_message().body.startswith("Hi {greeting_name}")


def test_row_message_customization_persists(crm_paths):
    working, _, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    assert save_row_message(
        "ndevaughn@fortmyers.gov",
        "FL",
        "Fort Myers",
        "Custom subject",
        "Hi {greeting_name},\n\nCustom row body.",
    )
    rows = read_outreach_rows()
    assert rows[0]["message_customized"] == "yes"
    assert rows[0]["subject"] == "Custom subject"


def test_default_message_does_not_overwrite_customized_row(crm_paths):
    working, _, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    save_row_message("ndevaughn@fortmyers.gov", "FL", "Fort Myers", "Keep", "Hi {greeting_name}, keep.")
    save_default_message_for_outreach("Changed", "Hi {greeting_name}, changed.")
    rows = read_outreach_rows()
    assert rows[0]["subject"] == "Keep"


def test_greeting_substitution_at_render_time(crm_paths):
    working, _, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    rows = read_outreach_rows()
    rows[0]["greeting_name"] = "Nikki"
    _, body = render_row_email(rows[0])
    assert "Hi Nikki," in body


def test_ui_renders_simplified_controls(crm_paths):
    working, _, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/")
        html = resp.data.decode("utf-8")
        assert resp.status_code == 200
        assert "Planzookie Outreach CRM" in html
        assert "Ready contacts → send emails" not in html
        assert "Email name" in html
        assert "Greeting" not in html
        assert "Follow-up</th>" not in html
        assert "Needs Follow-Up" not in html
        assert "Queue Ready Emails" in html
        assert "Pause Sending" in html
        assert "Send Next Now" in html
        assert "Queued:" in html or ">Queued<" in html
        assert "Default Message" in html
        assert "row-menu" in html
        assert "menu-dropdown" in html
        assert ">Details</button>" in html
        assert "menu-delete" in html
        assert "flash-msg" in html
        assert "msg-dismiss" in html
        assert "row-alt" in html
        assert "initFlashMessage" in html
        assert "Create draft for next approved row" not in html


def test_delete_row_removes_contact(crm_paths):
    working, _, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    assert delete_outreach_row("ndevaughn@fortmyers.gov", "FL", "Fort Myers")
    assert read_outreach_rows() == []


def test_delete_row_route(crm_paths):
    working, _, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.post(
            "/row/delete",
            data={
                "orig_email": "ndevaughn@fortmyers.gov",
                "orig_state": "FL",
                "orig_jurisdiction_name": "Fort Myers",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Contact removed" in resp.data
    assert read_outreach_rows() == []
