"""Throttled outreach send queue with daily/hourly limits."""

from __future__ import annotations

import json
import random
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from src.gmail_client import GmailService, build_gmail_service, verify_gmail_account
from src.harvest_report import _fmt_ts_et, _parse_iso_utc
from src.outreach_crm import SENT_STATUS
from src.outreach_store import (
    apply_failure,
    apply_send_result,
    is_outreach_sendable,
    outreach_key,
    read_outreach_rows,
    ready_send_candidates,
    write_outreach_rows,
)
from src.outreach_template import render_row_email
from src.paths import SEND_QUEUE_STATE_JSON

QUEUED_STATUS = "queued"
SENDING_STATUS = "sending"

BASE_INTERVAL_SECONDS = 300
JITTER_SECONDS = 90
MAX_EMAILS_PER_DAY = 25
MAX_EMAILS_PER_HOUR = 10

_send_lock = threading.Lock()


@dataclass
class SendQueueState:
    paused: bool = False
    next_send_at: str = ""
    queue_batch_id: str = ""
    consecutive_errors: int = 0
    pause_reason: str = ""

    @classmethod
    def load(cls) -> SendQueueState:
        if not SEND_QUEUE_STATE_JSON.exists():
            return cls()
        try:
            raw = json.loads(SEND_QUEUE_STATE_JSON.read_text(encoding="utf-8"))
            return cls(
                paused=bool(raw.get("paused", False)),
                next_send_at=str(raw.get("next_send_at") or ""),
                queue_batch_id=str(raw.get("queue_batch_id") or ""),
                consecutive_errors=int(raw.get("consecutive_errors") or 0),
                pause_reason=str(raw.get("pause_reason") or ""),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return cls()

    def save(self) -> None:
        SEND_QUEUE_STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
        SEND_QUEUE_STATE_JSON.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def compute_next_send_at(
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> str:
    now = now or _now_utc()
    rng = rng or random.Random()
    jitter = rng.randint(-JITTER_SECONDS, JITTER_SECONDS)
    nxt = now + timedelta(seconds=BASE_INTERVAL_SECONDS + jitter)
    return nxt.replace(microsecond=0).isoformat()


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return _parse_iso_utc(value)
    except ValueError:
        return None


def _schedule_first_send_at(*, now: datetime | None = None) -> str:
    """Mark the queue eligible for one send on the next worker tick (not in-process)."""
    return (now or _now_utc()).replace(microsecond=0).isoformat()


def _ensure_queue_send_scheduled(state: SendQueueState, *, prior_queued_count: int) -> None:
    """Ensure queued rows have a valid due time without delaying the first send by one interval."""
    due = _parse_iso(state.next_send_at)
    if prior_queued_count == 0 or not state.next_send_at or due is None:
        state.next_send_at = _schedule_first_send_at()


def queued_rows(rows: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    rows = rows if rows is not None else read_outreach_rows()
    queued = [r for r in rows if (r.get("send_status") or "") == QUEUED_STATUS]
    queued.sort(key=lambda r: r.get("queued_at") or "")
    return queued


def sent_since(rows: list[dict[str, str]], since: datetime) -> int:
    count = 0
    for row in rows:
        if row.get("send_status") != SENT_STATUS:
            continue
        sent_at = _parse_iso(row.get("sent_at") or "")
        if sent_at and sent_at >= since:
            count += 1
    return count


def rate_limits_exceeded(rows: list[dict[str, str]] | None = None, *, now: datetime | None = None) -> tuple[bool, str]:
    now = now or _now_utc()
    rows = rows if rows is not None else read_outreach_rows()
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(hours=24)
    if sent_since(rows, day_ago) >= MAX_EMAILS_PER_DAY:
        return True, "daily limit reached"
    if sent_since(rows, hour_ago) >= MAX_EMAILS_PER_HOUR:
        return True, "hourly limit reached"
    return False, ""


def queue_ready_contacts() -> tuple[int, str]:
    """Add Ready unsent contacts to queue; does not send immediately."""
    rows = read_outreach_rows()
    candidates = ready_send_candidates(rows)
    if not candidates:
        return 0, "No Ready contacts to queue."

    state = SendQueueState.load()
    batch_id = str(uuid.uuid4())
    now = _now_iso()
    prior_queued_count = len(queued_rows(rows))
    keys = {outreach_key(c) for c in candidates}
    queued = 0
    for row in rows:
        if outreach_key(row) not in keys:
            continue
        row["send_status"] = QUEUED_STATUS
        row["queued_at"] = now
        row["queue_batch_id"] = batch_id
        row["send_error"] = ""
        row["send_attempt_count"] = row.get("send_attempt_count") or "0"
        queued += 1

    write_outreach_rows(rows)
    state.queue_batch_id = batch_id
    _ensure_queue_send_scheduled(state, prior_queued_count=prior_queued_count)
    state.paused = False
    state.pause_reason = ""
    state.consecutive_errors = 0
    state.save()
    return queued, f"Queued {queued} contact(s) for throttled sending."


def pause_queue(reason: str = "paused by user") -> None:
    state = SendQueueState.load()
    state.paused = True
    state.pause_reason = reason
    state.save()


def resume_queue() -> None:
    state = SendQueueState.load()
    state.paused = False
    state.pause_reason = ""
    state.consecutive_errors = 0
    now = _now_utc()
    nxt = _parse_iso(state.next_send_at)
    if not nxt or nxt > now:
        state.next_send_at = now.replace(microsecond=0).isoformat()
    state.save()


def cancel_queue() -> int:
    rows = read_outreach_rows()
    cleared = 0
    for row in rows:
        if row.get("send_status") != QUEUED_STATUS:
            continue
        row["send_status"] = "prepared"
        row["queued_at"] = ""
        row["queue_batch_id"] = ""
        row["send_error"] = ""
        cleared += 1
    write_outreach_rows(rows)
    state = SendQueueState.load()
    if not queued_rows():
        state.next_send_at = ""
        state.queue_batch_id = ""
    state.save()
    return cleared


def _mark_sending(row: dict[str, str]) -> None:
    rows = read_outreach_rows()
    key = outreach_key(row)
    for r in rows:
        if outreach_key(r) == key:
            r["send_status"] = SENDING_STATUS
            r["last_send_attempt_at"] = _now_iso()
            try:
                r["send_attempt_count"] = str(int(r.get("send_attempt_count") or 0) + 1)
            except ValueError:
                r["send_attempt_count"] = "1"
            break
    write_outreach_rows(rows)


def _send_row(service: GmailService, row: dict[str, str]) -> None:
    if row.get("send_status") == SENT_STATUS:
        return
    if not is_outreach_sendable(row):
        raise ValueError("invalid email or blank subject/body")
    subject, body = render_row_email(row)
    _mark_sending(row)
    message_id = service.send_message(row["email"], subject, body)
    apply_send_result(row, message_id)


def send_next_queued(
    service: GmailService | None = None,
    *,
    force_now: bool = False,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> tuple[bool, str]:
    """Send at most one queued email if due and limits allow."""
    with _send_lock:
        now = now or _now_utc()
        state = SendQueueState.load()
        rows = read_outreach_rows()
        pending = queued_rows(rows)

        if state.paused:
            return False, "Queue paused"
        if not pending:
            return False, "Queue empty"
        limited, reason = rate_limits_exceeded(rows, now=now)
        if limited:
            return False, reason

        if not force_now:
            due = _parse_iso(state.next_send_at)
            if due is None:
                return False, "not due yet"
            if due > now:
                return False, "not due yet"

        row = pending[0]
        if row.get("send_status") == SENT_STATUS:
            return False, "already sent"

        if service is None:
            service = build_gmail_service()
            verify_gmail_account(service)

        try:
            _send_row(service, row)
            state = SendQueueState.load()
            state.consecutive_errors = 0
            completed_at = _now_utc()
            remaining = queued_rows()
            if remaining:
                state.next_send_at = compute_next_send_at(now=completed_at, rng=rng)
            else:
                state.next_send_at = ""
            state.save()
            return True, f"Sent to {row.get('email')}"
        except Exception as exc:
            apply_failure(row, str(exc))
            state = SendQueueState.load()
            state.consecutive_errors += 1
            state.paused = True
            state.pause_reason = str(exc)[:200]
            state.save()
            return False, str(exc)


def process_send_queue(
    service: GmailService | None = None,
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> tuple[bool, str]:
    return send_next_queued(service=service, force_now=False, now=now, rng=rng)


def format_next_send_display(
    state: SendQueueState | None = None,
    rows: list[dict[str, str]] | None = None,
) -> str:
    state = state or SendQueueState.load()
    rows = rows if rows is not None else read_outreach_rows()
    block = queue_block_reason(rows, state)
    if block and queued_rows(rows):
        if "daily" in block:
            return "Daily limit reached"
        if "hourly" in block:
            return "Hourly limit reached"
    if state.paused:
        return "Paused"
    if not state.next_send_at:
        return "—"
    return _fmt_ts_et(state.next_send_at)


def queue_block_reason(
    rows: list[dict[str, str]] | None = None,
    state: SendQueueState | None = None,
    *,
    now: datetime | None = None,
) -> str:
    rows = rows if rows is not None else read_outreach_rows()
    state = state or SendQueueState.load()
    if not queued_rows(rows):
        return ""
    if state.paused:
        return state.pause_reason or "paused"
    limited, reason = rate_limits_exceeded(rows, now=now)
    if limited:
        return reason
    return ""


def compute_queue_dashboard(rows: list[dict[str, str]] | None = None) -> dict[str, str]:
    rows = rows if rows is not None else read_outreach_rows()
    state = SendQueueState.load()
    day_ago = _now_utc() - timedelta(hours=24)
    block = queue_block_reason(rows, state)
    from src.send_queue_worker import get_worker_status

    worker = get_worker_status()
    return {
        "queued": str(len(queued_rows(rows))),
        "sent_today": str(sent_since(rows, day_ago)),
        "next_send": format_next_send_display(state, rows),
        "paused": "yes" if state.paused else "no",
        "block_reason": block,
        "worker_running": "yes" if worker.started else "no",
        "worker_alive": "yes" if worker.thread_alive else "no",
        "worker_last_tick": worker.last_tick_display(),
        "worker_last_result": worker.last_tick_detail or "—",
    }
