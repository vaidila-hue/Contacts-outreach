"""CRM logic: overrides, dashboard, filters, duplicate detection, save."""

from __future__ import annotations

from datetime import datetime, timezone

from src.outreach_template import apply_default_templates_to_row, is_message_customized, load_default_message
from src.paths import (
    EDITABLE_CONTENT_FIELDS,
    EDITABLE_TRACKING_FIELDS,
    OUTREACH_COLUMNS,
    REPLY_STATUS_VALUES,
)

SENT_STATUS = "sent"
DRAFTED_STATUS = "drafted"
PREPARED_STATUS = "prepared"

OUTREACH_STATE_FIELDS = (
    "approved",
    "send_status",
    "sent_at",
    "gmail_draft_id",
    "gmail_message_id",
    "prepared_at",
    "approved_at",
    "drafted_at",
    "error",
    "subject",
    "body",
)

TRACKING_FIELDS = (
    "reply_status",
    "first_reply_at",
    "meeting_requested",
    "meeting_scheduled_for",
    "meeting_completed",
    "follow_up_needed",
    "follow_up_at",
    "outreach_notes",
)

REPLY_COUNTS_AS_REPLY = frozenset(
    {
        "replied",
        "meeting_requested",
        "meeting_scheduled",
        "meeting_completed",
        "not_interested",
        "bounced",
        "wrong_contact",
        "do_not_contact",
    }
)

FILTER_OPTIONS = (
    ("all", "Show All"),
    ("ready", "Ready"),
    ("not_sent", "Not Sent"),
    ("sent", "Sent"),
    ("replied", "Replied"),
    ("meeting_scheduled", "Meeting Scheduled"),
    ("meeting_completed", "Meeting Completed"),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_ready(row: dict[str, str]) -> bool:
    approved = (row.get("approved") or "").lower() in ("yes", "true", "1")
    return approved and row.get("send_status") != SENT_STATUS


def format_sent_date_display(sent_at: str) -> str:
    if not (sent_at or "").strip():
        return ""
    try:
        dt = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
        return dt.strftime("%m/%d/%y")
    except ValueError:
        return sent_at[:10] if len(sent_at) >= 10 else sent_at


def modified_flag(field: str) -> str:
    return f"{field}_modified"


def is_field_modified(row: dict[str, str], field: str) -> bool:
    return row.get(modified_flag(field)) == "yes"


def mark_field_modified(row: dict[str, str], field: str) -> None:
    if field in EDITABLE_CONTENT_FIELDS:
        row[modified_flag(field)] = "yes"


def is_tracking_modified(row: dict[str, str]) -> bool:
    return row.get("tracking_modified") == "yes" or row.get("reply_status_modified") == "yes"


def outreach_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        (row.get("email") or "").strip().lower(),
        (row.get("state") or "").strip().upper(),
        (row.get("jurisdiction_name") or "").strip(),
    )


def locate_key(row: dict[str, str]) -> tuple[str, str, str]:
    """Original key from UI hidden fields (before edits)."""
    return (
        (row.get("_orig_email") or row.get("email") or "").strip().lower(),
        (row.get("_orig_state") or row.get("state") or "").strip().upper(),
        (row.get("_orig_jurisdiction_name") or row.get("jurisdiction_name") or "").strip(),
    )


def duplicate_match(existing: dict[str, str], candidate: dict[str, str]) -> bool:
    if outreach_key(existing) == outreach_key(candidate):
        return True
    e_email = (existing.get("email") or "").strip().lower()
    c_email = (candidate.get("email") or "").strip().lower()
    if e_email and c_email and e_email == c_email:
        return True
    e_name = (existing.get("contact_name") or "").strip().lower()
    c_name = (candidate.get("contact_name") or "").strip().lower()
    e_j = (existing.get("jurisdiction_name") or "").strip().lower()
    c_j = (candidate.get("jurisdiction_name") or "").strip().lower()
    e_s = (existing.get("state") or "").strip().upper()
    c_s = (candidate.get("state") or "").strip().upper()
    if e_name and c_name and e_name == c_name and e_j == c_j and e_s == c_s:
        return True
    e_src = (existing.get("email_source_url") or "").strip().lower()
    c_src = (candidate.get("email_source_url") or "").strip().lower()
    if e_src and c_src and c_name and e_src == c_src and e_name == c_name:
        return True
    return False


def is_duplicate_of_any(candidate: dict[str, str], rows: list[dict[str, str]]) -> bool:
    return any(duplicate_match(r, candidate) for r in rows)


def merge_outreach_row(
    existing: dict[str, str] | None,
    fresh: dict[str, str],
) -> dict[str, str]:
    """Merge harvest suggestion into existing CRM record; user edits win."""
    if existing and existing.get("send_status") == SENT_STATUS:
        return dict(existing)

    if not existing:
        fresh.setdefault("reply_status", "not_sent")
        return fresh

    merged = dict(existing)

    for field in EDITABLE_CONTENT_FIELDS:
        if is_field_modified(existing, field):
            continue
        if fresh.get(field):
            merged[field] = fresh[field]

    if not is_field_modified(existing, "greeting_name") and not merged.get("greeting_name"):
        merged["greeting_name"] = fresh.get("greeting_name", "there")

    if existing.get("send_status") in (DRAFTED_STATUS, SENT_STATUS):
        merged["send_status"] = existing["send_status"]
    elif existing.get("send_status"):
        merged["send_status"] = existing["send_status"]

    if is_message_customized(existing):
        merged["subject"] = existing.get("subject", "")
        merged["body"] = existing.get("body", "")
        merged["message_customized"] = existing.get("message_customized", "")
        merged["default_message_version"] = existing.get("default_message_version", "")
    elif existing.get("send_status") not in (SENT_STATUS,):
        default = load_default_message()
        apply_default_templates_to_row(merged, default)

    for field in OUTREACH_STATE_FIELDS:
        if field in ("subject", "body"):
            continue
        if existing.get(field):
            merged[field] = existing[field]

    if not is_tracking_modified(existing):
        for field in TRACKING_FIELDS:
            if existing.get(field):
                merged[field] = existing[field]
            elif field == "reply_status" and not merged.get("reply_status"):
                merged["reply_status"] = fresh.get("reply_status", "not_sent")

    for field in OUTREACH_COLUMNS:
        if field.endswith("_modified") and existing.get(field):
            merged[field] = existing[field]
        if field == "message_customized" and existing.get(field):
            merged[field] = existing[field]

    return merged


def apply_send_side_effects(row: dict[str, str]) -> None:
    reply = (row.get("reply_status") or "").strip()
    if not reply or reply == "not_sent":
        row["reply_status"] = "sent_no_reply"


def compute_dashboard(rows: list[dict[str, str]]) -> dict[str, int]:
    stats = {
        "total": len(rows),
        "ready": 0,
        "sent": 0,
        "replies": 0,
        "meetings_scheduled": 0,
        "meetings_completed": 0,
    }
    for row in rows:
        if is_ready(row):
            stats["ready"] += 1
        status = row.get("send_status", "")
        if status == SENT_STATUS:
            stats["sent"] += 1
        reply = row.get("reply_status", "")
        if reply in REPLY_COUNTS_AS_REPLY:
            stats["replies"] += 1
        if reply == "meeting_scheduled" or (row.get("meeting_scheduled_for") or "").strip():
            stats["meetings_scheduled"] += 1
        if reply == "meeting_completed" or (row.get("meeting_completed") or "").lower() in (
            "yes",
            "true",
            "1",
        ):
            stats["meetings_completed"] += 1
    return stats


def row_matches_filter(row: dict[str, str], filter_name: str) -> bool:
    if filter_name in ("", "all"):
        return True
    approved = (row.get("approved") or "").lower() in ("yes", "true", "1")
    status = row.get("send_status", "")
    reply = row.get("reply_status", "")
    if filter_name == "ready":
        return is_ready(row)
    if filter_name == "approved":
        return is_ready(row)
    if filter_name == "not_sent":
        return status != SENT_STATUS
    if filter_name == "sent":
        return status == SENT_STATUS
    if filter_name == "replied":
        return reply in REPLY_COUNTS_AS_REPLY
    if filter_name == "needs_follow_up":
        return (row.get("follow_up_needed") or "").lower() in ("yes", "true", "1")
    if filter_name == "meeting_scheduled":
        return reply == "meeting_scheduled" or bool((row.get("meeting_scheduled_for") or "").strip())
    if filter_name == "meeting_completed":
        return reply == "meeting_completed" or (row.get("meeting_completed") or "").lower() in (
            "yes",
            "true",
            "1",
        )
    return True


def _normalize_checkbox(value: str) -> str:
    return "yes" if (value or "").strip().lower() in ("yes", "true", "1", "on") else ""


def save_crm_rows(updates: list[dict[str, str]], existing_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Apply UI edits; mark modified flags; return updated row list."""
    by_key = {outreach_key(r): r for r in existing_rows}
    now = _now_iso()

    for upd in updates:
        key = locate_key(upd)
        row = by_key.get(key)
        if row is None:
            continue

        for field in EDITABLE_CONTENT_FIELDS:
            new_val = (upd.get(field) or "").strip()
            old_val = (row.get(field) or "").strip()
            if new_val != old_val:
                row[field] = new_val
                mark_field_modified(row, field)

        approved = _normalize_checkbox(upd.get("approved", row.get("approved", "")))
        if row.get("send_status") == SENT_STATUS:
            approved = ""
        if approved != (row.get("approved") or ""):
            row["approved"] = approved
            row["tracking_modified"] = "yes"
            if approved and not row.get("approved_at"):
                row["approved_at"] = now
            if not approved:
                row["approved_at"] = ""

        checkbox_fields = ("meeting_requested", "meeting_completed", "follow_up_needed")
        for field in EDITABLE_TRACKING_FIELDS:
            if field == "approved":
                continue
            if field in checkbox_fields:
                new_val = _normalize_checkbox(upd.get(field, row.get(field, "")))
            else:
                new_val = (upd.get(field) or row.get(field) or "").strip()
            old_val = row.get(field) or ""
            if field in checkbox_fields:
                old_cmp = old_val
            else:
                old_cmp = old_val.strip()
            if new_val != old_cmp:
                row[field] = new_val
                row["tracking_modified"] = "yes"
                if field == "reply_status":
                    row["reply_status_modified"] = "yes"

        new_key = outreach_key(row)
        if new_key != key:
            by_key.pop(key, None)
            by_key[new_key] = row

    return list(by_key.values())
