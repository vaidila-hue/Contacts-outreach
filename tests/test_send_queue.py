"""Tests for throttled send queue."""

from __future__ import annotations

import argparse
import threading
from datetime import datetime, timedelta, timezone

import pytest

from src.gmail_client import MockGmailService
from src.outreach_cli import run_outreach_send_ready
from src.outreach_crm import is_ready
from src.outreach_store import prepare_outreach, read_outreach_rows, write_outreach_rows
from src.paths import OUTREACH_COLUMNS, WORKING_COLUMNS
from src.send_queue import (
    BASE_INTERVAL_SECONDS,
    JITTER_SECONDS,
    MAX_EMAILS_PER_DAY,
    MAX_EMAILS_PER_HOUR,
    SendQueueState,
    cancel_queue,
    compute_next_send_at,
    compute_queue_dashboard,
    pause_queue,
    process_send_queue,
    queue_ready_contacts,
    queued_rows,
    rate_limits_exceeded,
    resume_queue,
    send_next_queued,
)
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

    monkeypatch.setattr(paths, "WORKING_CSV", working)
    monkeypatch.setattr(paths, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(paths, "SEND_QUEUE_STATE_JSON", queue_state)
    monkeypatch.setattr(paths, "DEFAULT_MESSAGE_JSON", default_msg)
    monkeypatch.setattr(store, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(store, "WORKING_CSV", working)
    monkeypatch.setattr(sq, "SEND_QUEUE_STATE_JSON", queue_state)
    return working, outreach, queue_state


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


def _prepare_ready_row(queue_paths, email: str = "a@test.gov", jurisdiction: str = "CityA"):
    working, _, _ = queue_paths
    write_csv(working, [_working_row(email=email, jurisdiction_name=jurisdiction)], WORKING_COLUMNS)
    prepare_outreach()
    rows = read_outreach_rows()
    rows[0]["approved"] = "yes"
    write_outreach_rows(rows)


def _prepare_four_ready_rows(queue_paths):
    working, _, _ = queue_paths
    rows = [
        _working_row(
            email=f"user{i}@test.gov",
            jurisdiction_name=f"City{i}",
            contact_name=f"Planner {i}",
            email_source_url=f"https://city{i}.gov/planning",
            candidate_source_url=f"https://city{i}.gov/planning",
        )
        for i in range(4)
    ]
    write_csv(working, rows, WORKING_COLUMNS)
    prepare_outreach()
    outreach = read_outreach_rows()
    for row in outreach:
        row["approved"] = "yes"
    write_outreach_rows(outreach)


def test_queue_ready_does_not_send_immediately(queue_paths):
    _prepare_ready_row(queue_paths)
    service = MockGmailService()
    count, _ = queue_ready_contacts()
    assert count == 1
    assert service.sent == []
    rows = read_outreach_rows()
    assert rows[0]["send_status"] == "queued"
    assert not is_ready(rows[0])


def test_run_outreach_send_ready_queues_not_sends(queue_paths):
    _prepare_ready_row(queue_paths)
    service = MockGmailService()
    args = argparse.Namespace(delay_seconds=0)
    assert run_outreach_send_ready(args, service=service) == 0
    assert service.sent == []
    assert read_outreach_rows()[0]["send_status"] == "queued"


def test_queued_rows_persist(queue_paths):
    _prepare_ready_row(queue_paths)
    queue_ready_contacts()
    assert len(queued_rows()) == 1
    _, _, queue_state = queue_paths
    assert queue_state.exists()


def test_send_one_when_due(queue_paths):
    _prepare_ready_row(queue_paths)
    queue_ready_contacts()
    state = SendQueueState.load()
    state.next_send_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    state.save()
    service = MockGmailService()
    ok, _ = send_next_queued(service=service, force_now=False)
    assert ok
    assert len(service.sent) == 1
    assert read_outreach_rows()[0]["send_status"] == "sent"


def test_not_due_skips_send(queue_paths):
    _prepare_ready_row(queue_paths)
    queue_ready_contacts()
    state = SendQueueState.load()
    state.next_send_at = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0).isoformat()
    state.save()
    service = MockGmailService()
    ok, msg = send_next_queued(service=service)
    assert not ok
    assert "not due" in msg
    assert service.sent == []


def test_daily_max_enforced(queue_paths):
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(MAX_EMAILS_PER_DAY):
        row = {col: "" for col in OUTREACH_COLUMNS}
        row.update(
            {
                "email": f"user{i}@test.gov",
                "state": "FL",
                "jurisdiction_name": f"City{i}",
                "send_status": "sent",
                "sent_at": now.isoformat(),
            }
        )
        rows.append(row)
    write_outreach_rows(rows)
    limited, reason = rate_limits_exceeded(rows, now=now)
    assert limited
    assert "daily" in reason


def test_hourly_max_enforced(queue_paths):
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(MAX_EMAILS_PER_HOUR):
        row = {col: "" for col in OUTREACH_COLUMNS}
        row.update(
            {
                "email": f"user{i}@test.gov",
                "state": "FL",
                "jurisdiction_name": f"City{i}",
                "send_status": "sent",
                "sent_at": now.isoformat(),
            }
        )
        rows.append(row)
    limited, reason = rate_limits_exceeded(rows, now=now)
    assert limited
    assert "hourly" in reason


def test_jitter_applied():
    import random

    now = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
    rng = random.Random(0)
    nxt = compute_next_send_at(now=now, rng=rng)
    dt = datetime.fromisoformat(nxt)
    delta = (dt - now).total_seconds()
    assert BASE_INTERVAL_SECONDS - JITTER_SECONDS <= delta <= BASE_INTERVAL_SECONDS + JITTER_SECONDS


def test_sent_rows_never_resend(queue_paths):
    _prepare_ready_row(queue_paths)
    rows = read_outreach_rows()
    rows[0].update({"send_status": "sent", "sent_at": datetime.now(timezone.utc).isoformat()})
    write_outreach_rows(rows)
    assert len(queued_rows()) == 0


def test_pause_prevents_sending(queue_paths):
    _prepare_ready_row(queue_paths)
    queue_ready_contacts()
    pause_queue()
    state = SendQueueState.load()
    state.next_send_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    state.save()
    service = MockGmailService()
    ok, msg = send_next_queued(service=service)
    assert not ok
    assert "paused" in msg.lower()


def test_resume_allows_sending(queue_paths):
    _prepare_ready_row(queue_paths)
    queue_ready_contacts()
    pause_queue()
    resume_queue()
    service = MockGmailService()
    ok, _ = send_next_queued(service=service, force_now=True)
    assert ok


def test_cancel_queue_clears_queued(queue_paths):
    _prepare_ready_row(queue_paths)
    queue_ready_contacts()
    cleared = cancel_queue()
    assert cleared == 1
    assert read_outreach_rows()[0]["send_status"] == "prepared"
    assert is_ready(read_outreach_rows()[0])


def test_gmail_error_pauses_queue(queue_paths):
    _prepare_ready_row(queue_paths)
    queue_ready_contacts()

    class FailService(MockGmailService):
        def send_message(self, to, subject, body):
            raise RuntimeError("Gmail API error")

    ok, _ = send_next_queued(service=FailService(), force_now=True)
    assert not ok
    state = SendQueueState.load()
    assert state.paused
    assert read_outreach_rows()[0]["send_status"] == "failed"


def test_daily_limit_shown_as_next_send_blocker(queue_paths):
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(MAX_EMAILS_PER_DAY):
        row = {col: "" for col in OUTREACH_COLUMNS}
        row.update(
            {
                "email": f"sent{i}@test.gov",
                "state": "FL",
                "jurisdiction_name": f"SentCity{i}",
                "send_status": "sent",
                "sent_at": now.isoformat(),
            }
        )
        rows.append(row)
    row = {col: "" for col in OUTREACH_COLUMNS}
    row.update(
        {
            "email": "queued@test.gov",
            "state": "FL",
            "jurisdiction_name": "QueuedCity",
            "send_status": "queued",
            "approved": "yes",
            "subject": "Hi",
            "body": "Body",
            "greeting_name": "Test",
        }
    )
    rows.append(row)
    write_outreach_rows(rows)
    state = SendQueueState.load()
    state.next_send_at = (now - timedelta(hours=1)).isoformat()
    state.save()
    dashboard = compute_queue_dashboard(rows)
    assert dashboard["next_send"] == "Daily limit reached"
    assert "daily" in dashboard["block_reason"]
    service = MockGmailService()
    ok, msg = send_next_queued(service=service)
    assert not ok
    assert "daily" in msg


def test_queue_block_reason_when_not_limited(queue_paths):
    _prepare_ready_row(queue_paths)
    queue_ready_contacts()
    dashboard = compute_queue_dashboard()
    assert dashboard["block_reason"] == ""


def test_queue_resumes_after_restart(queue_paths):
    _prepare_ready_row(queue_paths)
    queue_ready_contacts()
    assert SendQueueState.load().queue_batch_id
    state = SendQueueState.load()
    state.paused = False
    state.next_send_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    state.save()
    service = MockGmailService()
    ok, _ = send_next_queued(service=service, force_now=False)
    assert ok


def test_queue_four_rows_does_not_send_immediately(queue_paths):
    _prepare_four_ready_rows(queue_paths)
    service = MockGmailService()
    count, _ = queue_ready_contacts()
    assert count == 4
    assert len(service.sent) == 0
    assert len(queued_rows()) == 4


def test_queue_schedules_first_send_soon_not_one_interval_later(queue_paths):
    _prepare_four_ready_rows(queue_paths)
    before = datetime.now(timezone.utc)
    queue_ready_contacts()
    state = SendQueueState.load()
    due = datetime.fromisoformat(state.next_send_at)
    assert due <= before + timedelta(seconds=5)
    assert due >= before - timedelta(seconds=5)


def test_worker_tick_sends_at_most_one(queue_paths):
    _prepare_four_ready_rows(queue_paths)
    queue_ready_contacts()
    service = MockGmailService()
    ok, _ = process_send_queue(service=service)
    assert ok
    assert len(service.sent) == 1
    assert len(queued_rows()) == 3


def test_second_tick_before_next_send_at_sends_zero(queue_paths):
    _prepare_four_ready_rows(queue_paths)
    queue_ready_contacts()
    service = MockGmailService()
    fixed = datetime(2026, 6, 11, 21, 52, 0, tzinfo=timezone.utc)
    state = SendQueueState.load()
    state.next_send_at = fixed.isoformat()
    state.save()
    ok, _ = process_send_queue(service=service, now=fixed)
    assert ok
    assert len(service.sent) == 1
    ok, msg = process_send_queue(service=service, now=fixed + timedelta(seconds=30))
    assert not ok
    assert "not due" in msg
    assert len(service.sent) == 1


def test_next_due_tick_sends_exactly_one(queue_paths):
    _prepare_four_ready_rows(queue_paths)
    queue_ready_contacts()
    service = MockGmailService()
    fixed = datetime(2026, 6, 11, 21, 52, 0, tzinfo=timezone.utc)
    state = SendQueueState.load()
    state.next_send_at = fixed.isoformat()
    state.save()
    rng = __import__("random").Random(0)
    assert send_next_queued(service=service, now=fixed, rng=rng)[0]
    assert len(service.sent) == 1
    state = SendQueueState.load()
    due = datetime.fromisoformat(state.next_send_at)
    assert due > fixed
    assert send_next_queued(service=service, now=due, rng=rng)[0]
    assert len(service.sent) == 2


def test_queued_rows_share_one_global_next_send_at(queue_paths):
    _prepare_four_ready_rows(queue_paths)
    queue_ready_contacts()
    state = SendQueueState.load()
    first_due = state.next_send_at
    assert first_due
    rows = read_outreach_rows()
    for row in rows:
        if row["send_status"] == "queued":
            assert row.get("next_send_at", "") == ""
    assert SendQueueState.load().next_send_at == first_due


def test_overdue_restart_sends_one_not_burst(queue_paths):
    _prepare_four_ready_rows(queue_paths)
    queue_ready_contacts()
    state = SendQueueState.load()
    overdue = datetime(2026, 6, 11, 20, 0, 0, tzinfo=timezone.utc)
    state.next_send_at = overdue.isoformat()
    state.save()
    service = MockGmailService()
    restart_now = datetime(2026, 6, 11, 21, 52, 0, tzinfo=timezone.utc)
    ok, _ = send_next_queued(service=service, now=restart_now)
    assert ok
    assert len(service.sent) == 1
    assert len(queued_rows()) == 3
    after = SendQueueState.load()
    assert datetime.fromisoformat(after.next_send_at) > restart_now


def test_concurrent_ticks_send_at_most_one(queue_paths):
    _prepare_four_ready_rows(queue_paths)
    queue_ready_contacts()
    service = MockGmailService()
    fixed = datetime(2026, 6, 11, 21, 52, 0, tzinfo=timezone.utc)
    state = SendQueueState.load()
    state.next_send_at = fixed.isoformat()
    state.save()
    results: list[tuple[bool, str]] = []

    def _tick():
        results.append(send_next_queued(service=service, now=fixed))

    threads = [threading.Thread(target=_tick) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(service.sent) == 1
    assert sum(1 for ok, _ in results if ok) == 1
