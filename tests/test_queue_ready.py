"""Tests for Queue Ready Emails skip reporting and form-state queueing."""

from __future__ import annotations

import pytest

from src.outreach_store import (
    is_outreach_sendable,
    prepare_outreach,
    read_outreach_rows,
    ready_queue_skip_reason,
    save_row_message,
    write_outreach_rows,
)
from src.outreach_ui import create_app
from src.paths import OUTREACH_COLUMNS, WORKING_COLUMNS
from src.send_queue import queue_ready_contacts
from src.csv_utils import write_csv


@pytest.fixture
def queue_paths(tmp_path, monkeypatch):
    import src.paths as paths
    import src.outreach_store as store
    import src.send_queue as sq

    working = tmp_path / "prospects_working.csv"
    outreach = tmp_path / "outreach.csv"
    queue_state = tmp_path / "send_queue_state.json"
    default_msg = tmp_path / "default_message.json"
    cfg = tmp_path / "send_queue_config.json"

    monkeypatch.setattr(paths, "WORKING_CSV", working)
    monkeypatch.setattr(paths, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(paths, "SEND_QUEUE_STATE_JSON", queue_state)
    monkeypatch.setattr(paths, "SEND_QUEUE_CONFIG_JSON", cfg)
    monkeypatch.setattr(paths, "DEFAULT_MESSAGE_JSON", default_msg)
    monkeypatch.setattr(store, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(store, "WORKING_CSV", working)
    monkeypatch.setattr(sq, "SEND_QUEUE_STATE_JSON", queue_state)
    import src.send_queue_config_store as sqcs

    monkeypatch.setattr(sqcs, "SEND_QUEUE_CONFIG_JSON", cfg)
    return working, outreach, queue_state


@pytest.fixture
def crm_paths(tmp_path, monkeypatch):
    import src.paths as paths
    import src.outreach_store as store
    import src.outreach_template as ot
    import src.send_queue as sq
    import src.send_queue_config_store as sqcs

    working = tmp_path / "prospects_working.csv"
    outreach = tmp_path / "outreach.csv"
    diagnostics = tmp_path / "harvest_diagnostics.csv"
    default_msg = tmp_path / "default_message.json"
    queue_state = tmp_path / "send_queue_state.json"
    cfg = tmp_path / "send_queue_config.json"

    for mod in (paths, store):
        monkeypatch.setattr(mod, "WORKING_CSV", working)
        monkeypatch.setattr(mod, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(paths, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(paths, "DEFAULT_MESSAGE_JSON", default_msg)
    monkeypatch.setattr(paths, "SEND_QUEUE_STATE_JSON", queue_state)
    monkeypatch.setattr(paths, "SEND_QUEUE_CONFIG_JSON", cfg)
    monkeypatch.setattr(ot, "DEFAULT_MESSAGE_JSON", default_msg)
    monkeypatch.setattr(sq, "SEND_QUEUE_STATE_JSON", queue_state)
    monkeypatch.setattr(sqcs, "SEND_QUEUE_CONFIG_JSON", cfg)
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


def _outreach_row(**overrides):
    row = {col: "" for col in OUTREACH_COLUMNS}
    row.update(
        {
            "approved": "yes",
            "greeting_name": "Planner",
            "send_status": "prepared",
            "reply_status": "not_sent",
            "jurisdiction_type": "city",
            "population": "50000",
            "jurisdiction_name": "Test City",
            "state": "FL",
            "contact_name": "Jane Planner",
            "contact_title": "Director",
            "email": "jane@test.gov",
            "jurisdiction_url": "https://test.gov",
            "email_source_url": "https://test.gov/plan",
            "subject": "Question from a planner",
            "body": "Hi {greeting_name},\n\nTest body.",
        }
    )
    row.update(overrides)
    return row


def test_ready_row_queues_successfully(queue_paths):
    working, _, _ = queue_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    rows = read_outreach_rows()
    rows[0]["approved"] = "yes"
    write_outreach_rows(rows)

    result = queue_ready_contacts()
    assert result.queued == 1
    assert result.skipped == []
    assert result.generic_warning_count == 0
    assert "Queued 1 contact(s)" in result.format_message()
    assert read_outreach_rows()[0]["send_status"] == "queued"


def test_santa_fe_generic_email_queues_when_ready(queue_paths):
    write_outreach_rows(
        [
            _outreach_row(
                jurisdiction_name="Santa Fe",
                state="NM",
                email="planning@santafenm.gov",
                contact_name="Santa Fe Planning Team",
                greeting_name="Santa Fe Planning Team",
            )
        ]
    )
    assert ready_queue_skip_reason(read_outreach_rows()[0]) is None
    assert not is_outreach_sendable(read_outreach_rows()[0])
    result = queue_ready_contacts()
    assert result.queued == 1
    assert result.skipped == []
    assert result.generic_warning_count == 1
    msg = result.format_message()
    assert "Queued 1 contact(s)" in msg
    assert "Warning: 1 generic email address" in msg
    row = read_outreach_rows()[0]
    assert row["send_status"] == "queued"
    assert row.get("send_error", "") == ""


def test_missing_email_skipped_with_reason(queue_paths):
    write_outreach_rows([_outreach_row(email="")])
    result = queue_ready_contacts()
    assert result.queued == 0
    assert result.skipped[0].reason == "missing email"


def test_already_sent_skipped_with_reason(queue_paths):
    write_outreach_rows(
        [
            _outreach_row(
                send_status="sent",
                sent_at="2026-06-12T12:00:00+00:00",
            )
        ]
    )
    result = queue_ready_contacts()
    assert result.queued == 0
    assert result.skipped[0].reason == "already sent"


def test_queue_banner_queues_both_direct_and_generic(queue_paths):
    write_outreach_rows(
        [
            _outreach_row(email="good@test.gov", jurisdiction_name="Good City"),
            _outreach_row(
                email="planning@city.gov",
                jurisdiction_name="Santa Fe",
                state="NM",
            ),
        ]
    )
    result = queue_ready_contacts()
    assert result.queued == 2
    assert result.skipped == []
    assert result.generic_warning_count == 1
    msg = result.format_message()
    assert "Queued 2 contact(s)" in msg
    assert "Warning: 1 generic email address" in msg
    assert "Skipped" not in msg


def test_harvest_prepare_still_skips_generic_working_row(queue_paths):
    working, _, _ = queue_paths
    write_csv(
        working,
        [
            _working_row(
                email="planning@santafenm.gov",
                contact_name="Santa Fe Planning Team",
                jurisdiction_name="Santa Fe",
                state="NM",
            )
        ],
        WORKING_COLUMNS,
    )
    total, new_count, stats = prepare_outreach()
    assert total == 0
    assert new_count == 0
    assert stats.generic_skipped >= 1


def test_generic_email_row_message_customization(queue_paths):
    write_outreach_rows(
        [
            _outreach_row(
                email="planning@santafenm.gov",
                jurisdiction_name="Santa Fe",
                state="NM",
            )
        ]
    )
    row = read_outreach_rows()[0]
    ok = save_row_message(
        row["email"],
        row["state"],
        row["jurisdiction_name"],
        "Custom subject",
        "Please forward to a senior planner.",
    )
    assert ok
    updated = read_outreach_rows()[0]
    assert updated["subject"] == "Custom subject"
    assert "forward" in updated["body"]
    result = queue_ready_contacts()
    assert result.queued == 1


def test_queue_ready_from_form_without_prior_save(crm_paths):
    working, outreach, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    rows = read_outreach_rows()
    assert rows[0]["approved"] != "yes"

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.post(
            "/queue-ready",
            data={
                "_orig_email": rows[0]["email"],
                "_orig_state": rows[0]["state"],
                "_orig_jurisdiction_name": rows[0]["jurisdiction_name"],
                "approved_0": "yes",
                "greeting_name_0": rows[0]["greeting_name"],
                "jurisdiction_name_0": rows[0]["jurisdiction_name"],
                "state_0": rows[0]["state"],
                "contact_name_0": rows[0]["contact_name"],
                "contact_title_0": rows[0]["contact_title"],
                "email_0": rows[0]["email"],
                "reply_status_0": "not_sent",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "Queued 1 contact(s)" in resp.data.decode("utf-8")

    after = read_outreach_rows()[0]
    assert after["approved"] == "yes"
    assert after["send_status"] == "queued"


def test_ui_queue_ready_shows_generic_warning(crm_paths):
    write_outreach_rows(
        [
            _outreach_row(
                email="planning@santafenm.gov",
                jurisdiction_name="Santa Fe",
                state="NM",
            )
        ]
    )
    rows = read_outreach_rows()
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.post(
            "/queue-ready",
            data={
                "_orig_email": rows[0]["email"],
                "_orig_state": rows[0]["state"],
                "_orig_jurisdiction_name": rows[0]["jurisdiction_name"],
                "approved_0": "yes",
                "greeting_name_0": rows[0]["greeting_name"],
                "jurisdiction_name_0": rows[0]["jurisdiction_name"],
                "state_0": rows[0]["state"],
                "contact_name_0": rows[0]["contact_name"],
                "contact_title_0": rows[0]["contact_title"],
                "email_0": rows[0]["email"],
                "reply_status_0": "not_sent",
            },
            follow_redirects=True,
        )
        html = resp.data.decode("utf-8")
        assert "Warning: 1 generic email address" in html
        assert "Generic email" in html
        assert "Not queued:" not in html
