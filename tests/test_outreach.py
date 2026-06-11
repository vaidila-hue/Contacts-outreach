"""Tests for outreach prepare, greeting names, and Gmail workflow."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import pytest

from src.gmail_client import GmailAccountError, MockGmailService, verify_gmail_account
from src.greeting_name import greeting_name_from_contact_name
from src.outreach_cli import run_outreach_draft, run_outreach_send
from src.outreach_store import (
    merge_outreach_row,
    next_draft_candidate,
    next_send_candidate,
    outreach_key,
    prepare_outreach,
    read_outreach_rows,
    update_outreach_rows,
    write_outreach_rows,
)
from src.outreach_template import render_outreach_email
from src.outreach_test import create_test_draft, load_test_history, render_test_outreach, send_test_email
from src.paths import (
    DIAGNOSTICS_CSV,
    OUTREACH_COLUMNS,
    OUTREACH_CSV,
    WORKING_COLUMNS,
    WORKING_CSV,
)
from src.csv_utils import write_csv


@pytest.fixture
def outreach_paths(tmp_path, monkeypatch):
    import src.paths as paths
    import src.outreach_store as store

    working = tmp_path / "prospects_working.csv"
    outreach = tmp_path / "outreach.csv"
    diagnostics = tmp_path / "harvest_diagnostics.csv"
    monkeypatch.setattr(paths, "WORKING_CSV", working)
    monkeypatch.setattr(paths, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(paths, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(store, "WORKING_CSV", working)
    monkeypatch.setattr(store, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(store, "DIAGNOSTICS_CSV", diagnostics)
    return working, outreach, diagnostics


def _sample_working_row(**overrides) -> dict[str, str]:
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


@pytest.mark.parametrize(
    "contact,expected",
    [
        ("Nicole DeVaughn", "Nicole"),
        ("Thomas Mooney", "Thomas"),
        ("Dr. Jane Smith", "Jane"),
        ("Sara Rutkowski, AICP", "Sara"),
        ("", "there"),
        ("Planning Director", "there"),
    ],
)
def test_greeting_name_extraction(contact, expected):
    assert greeting_name_from_contact_name(contact) == expected


def test_render_outreach_email_uses_greeting():
    subject, body = render_outreach_email("Nicole")
    assert subject == "Question from a fellow planner"
    assert body.startswith("Hi Nicole,")


def test_prepare_creates_outreach_rows(outreach_paths):
    working, outreach, diagnostics = outreach_paths
    write_csv(working, [_sample_working_row()], WORKING_COLUMNS)
    write_csv(
        diagnostics,
        [
            {
                "state": "FL",
                "jurisdiction_name": "Fort Myers",
                "geography_type": "city",
                "population": "91730",
                "official_domain": "www.fortmyers.gov",
                "planning_pages_found": "1",
                "directory_pages_found": "0",
                "staff_links_found": "0",
                "profile_links_followed": "0",
                "mailto_links_found": "0",
                "emails_found": "0",
                "candidate_titles_found": "0",
                "pages_fetched": "1",
                "search_queries_run": "0",
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
            }
        ],
        [
            "state",
            "jurisdiction_name",
            "geography_type",
            "population",
            "official_domain",
            "planning_pages_found",
            "directory_pages_found",
            "staff_links_found",
            "profile_links_followed",
            "mailto_links_found",
            "emails_found",
            "candidate_titles_found",
            "pages_fetched",
            "search_queries_run",
            "found_contact",
            "final_rejection_reason",
            "elapsed_seconds",
            "cache_hits",
            "cache_misses",
            "profile_pages_followed",
            "early_stop",
            "max_page_limit_hit",
            "timeout_count",
            "fetch_error_count",
        ],
    )

    total, new_rows = prepare_outreach()
    assert total == 1
    assert new_rows == 1
    rows = read_outreach_rows()
    assert rows[0]["greeting_name"] == "Nicole"
    assert rows[0]["jurisdiction_type"] == "city"
    assert rows[0]["population"] == "91730"
    assert rows[0]["send_status"] == "prepared"
    assert "fortmyers.gov" in rows[0]["jurisdiction_url"]


def test_prepare_preserves_sent_rows(outreach_paths):
    working, outreach, diagnostics = outreach_paths
    write_csv(working, [_sample_working_row()], WORKING_COLUMNS)
    sent_row = {col: "" for col in OUTREACH_COLUMNS}
    sent_row.update(
        {
            "approved": "yes",
            "greeting_name": "Nicki",
            "send_status": "sent",
            "sent_at": "2026-01-01T00:00:00+00:00",
            "jurisdiction_type": "city",
            "population": "91730",
            "jurisdiction_name": "Fort Myers",
            "state": "FL",
            "contact_name": "Nicole DeVaughn",
            "contact_title": "Planning Manager",
            "email": "ndevaughn@fortmyers.gov",
            "jurisdiction_url": "https://www.fortmyers.gov",
            "email_source_url": "https://www.fortmyers.gov/planning",
            "subject": "Question from a fellow planner",
            "body": "Hi Nicki,",
            "gmail_draft_id": "draft-1",
            "gmail_message_id": "msg-1",
            "prepared_at": "2025-12-01T00:00:00+00:00",
        }
    )
    write_outreach_rows([sent_row])
    prepare_outreach()
    rows = read_outreach_rows()
    assert len(rows) == 1
    assert rows[0]["send_status"] == "sent"
    assert rows[0]["greeting_name"] == "Nicki"
    assert rows[0]["sent_at"] == "2026-01-01T00:00:00+00:00"


def test_manual_greeting_preserved_on_prepare(outreach_paths):
    working, outreach, diagnostics = outreach_paths
    write_csv(working, [_sample_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    update_outreach_rows(
        [
            {
                "email": "ndevaughn@fortmyers.gov",
                "state": "FL",
                "jurisdiction_name": "Fort Myers",
                "approved": "yes",
                "greeting_name": "Nikki",
            }
        ]
    )
    prepare_outreach()
    rows = read_outreach_rows()
    assert rows[0]["greeting_name"] == "Nikki"


def test_approved_checkbox_persists(outreach_paths):
    working, outreach, diagnostics = outreach_paths
    write_csv(working, [_sample_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    update_outreach_rows(
        [
            {
                "email": "ndevaughn@fortmyers.gov",
                "state": "FL",
                "jurisdiction_name": "Fort Myers",
                "approved": "yes",
                "greeting_name": "Nicole",
            }
        ]
    )
    rows = read_outreach_rows()
    assert rows[0]["approved"] == "yes"
    assert rows[0]["approved_at"]


def test_generic_email_skipped_in_prepare(outreach_paths):
    working, outreach, diagnostics = outreach_paths
    write_csv(
        working,
        [_sample_working_row(email="planning@fortmyers.gov", contact_name="Planning Dept")],
        WORKING_COLUMNS,
    )
    total, _ = prepare_outreach()
    assert total == 0


def test_blank_subject_body_not_sendable(outreach_paths):
    working, outreach, diagnostics = outreach_paths
    write_csv(working, [_sample_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    rows = read_outreach_rows()
    rows[0]["approved"] = "yes"
    rows[0]["subject"] = ""
    rows[0]["body"] = ""
    rows[0]["message_customized"] = "yes"
    write_outreach_rows(rows)
    assert next_draft_candidate() is None


def test_gmail_account_mismatch_fails():
    service = MockGmailService(account="wrong@example.com")
    with pytest.raises(GmailAccountError):
        verify_gmail_account(service)


def test_dry_run_draft_does_not_mutate_csv(outreach_paths, capsys):
    working, outreach, diagnostics = outreach_paths
    write_csv(working, [_sample_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    update_outreach_rows(
        [
            {
                "email": "ndevaughn@fortmyers.gov",
                "state": "FL",
                "jurisdiction_name": "Fort Myers",
                "approved": "yes",
                "greeting_name": "Nicole",
            }
        ]
    )
    before = read_outreach_rows()[0]["send_status"]
    args = argparse.Namespace(limit=1, dry_run=True, delay_seconds=0)
    code = run_outreach_draft(args, service=MockGmailService())
    assert code == 0
    after = read_outreach_rows()[0]["send_status"]
    assert before == after == "prepared"
    assert "Dry run" in capsys.readouterr().out


def test_draft_one_at_a_time(outreach_paths):
    working, outreach, diagnostics = outreach_paths
    write_csv(working, [_sample_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    update_outreach_rows(
        [
            {
                "email": "ndevaughn@fortmyers.gov",
                "state": "FL",
                "jurisdiction_name": "Fort Myers",
                "approved": "yes",
                "greeting_name": "Nicole",
            }
        ]
    )
    service = MockGmailService()
    args = argparse.Namespace(limit=1, dry_run=False, delay_seconds=0)
    assert run_outreach_draft(args, service=service) == 0
    rows = read_outreach_rows()
    assert rows[0]["send_status"] == "drafted"
    assert rows[0]["gmail_draft_id"] == "draft-1"
    assert rows[0]["drafted_at"]
    assert len(service.drafts) == 1


def test_send_one_at_a_time_updates_sent_at(outreach_paths):
    working, outreach, diagnostics = outreach_paths
    write_csv(working, [_sample_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    update_outreach_rows(
        [
            {
                "email": "ndevaughn@fortmyers.gov",
                "state": "FL",
                "jurisdiction_name": "Fort Myers",
                "approved": "yes",
                "greeting_name": "Nicole",
            }
        ]
    )
    service = MockGmailService()
    draft_args = argparse.Namespace(limit=1, dry_run=False, delay_seconds=0)
    run_outreach_draft(draft_args, service=service)
    send_args = argparse.Namespace(
        limit=1,
        dry_run=False,
        delay_seconds=0,
        force=False,
        confirm_force=False,
    )
    assert run_outreach_send(send_args, service=service) == 0
    rows = read_outreach_rows()
    assert rows[0]["send_status"] == "sent"
    assert rows[0]["gmail_message_id"] == "msg-2"
    assert rows[0]["sent_at"]
    assert rows[0]["reply_status"] == "sent_no_reply"


def test_duplicate_send_prevention(outreach_paths):
    working, outreach, diagnostics = outreach_paths
    write_csv(working, [_sample_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    rows = read_outreach_rows()
    rows[0].update(
        {
            "approved": "yes",
            "send_status": "sent",
            "gmail_draft_id": "draft-1",
            "gmail_message_id": "msg-1",
            "sent_at": "2026-01-01T00:00:00+00:00",
        }
    )
    write_outreach_rows(rows)
    assert next_send_candidate() is None


def test_merge_preserves_existing_greeting():
    fresh = {col: "" for col in OUTREACH_COLUMNS}
    fresh.update({"greeting_name": "Nicole", "send_status": "prepared", "email": "a@b.gov", "state": "FL", "jurisdiction_name": "X"})
    existing = dict(fresh)
    existing["greeting_name"] = "Nikki"
    existing["greeting_name_modified"] = "yes"
    merged = merge_outreach_row(existing, fresh)
    assert merged["greeting_name"] == "Nikki"


def test_render_test_outreach_uses_production_template():
    from src.outreach_template import render_outreach_email
    from src.outreach_test import render_test_outreach, TEST_RECIPIENT_EMAIL

    content = render_test_outreach("Vaidila")
    subject, body = render_outreach_email("Vaidila")
    assert content["to_email"] == TEST_RECIPIENT_EMAIL
    assert content["subject"] == subject
    assert content["body"] == body
    assert content["body"].startswith("Hi Vaidila,")


def test_create_test_draft_does_not_modify_outreach_csv(outreach_paths, tmp_path, monkeypatch):
    import src.outreach_test as ot

    working, outreach, diagnostics = outreach_paths
    history = tmp_path / "test_history.json"
    monkeypatch.setattr(ot, "TEST_HISTORY_PATH", history)

    before = read_outreach_rows()
    service = MockGmailService()
    content, draft_id = create_test_draft(service, "Vaidila")
    after = read_outreach_rows()

    assert before == after
    assert draft_id == "draft-1"
    assert content["to_email"] == "vaidila@gmail.com"
    assert service.drafts[draft_id]["body"] == content["body"]
    assert history.exists()


def test_send_test_email_uses_draft_then_send(outreach_paths, tmp_path, monkeypatch):
    import src.outreach_test as ot

    outreach_paths
    history = tmp_path / "test_history.json"
    monkeypatch.setattr(ot, "TEST_HISTORY_PATH", history)

    service = MockGmailService()
    content, draft_id, message_id = send_test_email(service, "Testy")
    assert draft_id == "draft-1"
    assert message_id == "msg-2"
    assert content["body"].startswith("Hi Testy,")
    assert draft_id in service.sent
    hist = load_test_history()
    assert hist["last_test_greeting"] == "Testy"
    assert hist["last_test_send_at"]


def test_test_ui_page_renders(client=None):
    from src.outreach_ui import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/test")
        assert resp.status_code == 200
        assert b"vaidila@gmail.com" in resp.data
        assert b"Create Test Draft" in resp.data
        assert b"Send Test Email" in resp.data


def test_test_draft_route_does_not_touch_outreach_csv(outreach_paths, tmp_path, monkeypatch):
    import src.outreach_test as ot
    from src.outreach_ui import create_app

    working, outreach, diagnostics = outreach_paths
    prepare_outreach()
    before = read_outreach_rows()
    history = tmp_path / "test_history.json"
    monkeypatch.setattr(ot, "TEST_HISTORY_PATH", history)

    app = create_app()
    app.config["TESTING"] = True

    class StubService(MockGmailService):
        pass

    with app.test_client() as client:
        with monkeypatch.context() as m:
            m.setattr("src.outreach_ui.build_gmail_service", lambda: StubService())
            m.setattr("src.outreach_ui.verify_gmail_account", lambda s: s.get_profile_email())
            resp = client.post("/test/draft", data={"greeting_name": "Vaidila"})
            assert resp.status_code == 302

    after = read_outreach_rows()
    assert before == after
