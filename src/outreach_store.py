"""Outreach CSV merge, prepare, and persistence."""

from __future__ import annotations

from src.csv_utils import read_csv, write_csv
from src.extract_emails import classify_email, is_generic_email
from src.greeting_name import greeting_name_from_contact_name
from src.outreach_crm import (
    PREPARED_STATUS,
    QUEUED_STATUS,
    SENDING_STATUS,
    SENT_STATUS,
    apply_send_side_effects,
    classify_duplicate,
    is_duplicate_of_any,
    is_ready,
    merge_outreach_row,
    outreach_key,
    save_crm_rows,
)
from src.harvest_summary import PrepareStats
from src.jurisdiction_utils import jurisdiction_match_key
from src.outreach_template import (
    DefaultMessage,
    apply_default_templates_to_row,
    is_message_customized,
    load_default_message,
    render_row_email,
    save_default_message,
)
from src.paths import (
    DIAGNOSTICS_CSV,
    DIAGNOSTICS_COLUMNS,
    OUTREACH_COLUMNS,
    WORKING_COLUMNS,
    WORKING_CSV,
)
from src import paths

# Re-export for tests that monkeypatch outreach_store.OUTREACH_CSV.
OUTREACH_CSV = paths.OUTREACH_CSV

DRAFTED_STATUS = "drafted"


def empty_outreach_row() -> dict[str, str]:
    return {col: "" for col in OUTREACH_COLUMNS}


def read_outreach_rows() -> list[dict[str, str]]:
    from src import paths

    rows = read_csv(paths.OUTREACH_CSV, OUTREACH_COLUMNS)
    for row in rows:
        if not row.get("reply_status"):
            row["reply_status"] = "not_sent"
    return rows


def write_outreach_rows(rows: list[dict[str, str]]) -> None:
    from src.outreach_persistence import write_outreach_csv_atomic

    write_outreach_csv_atomic(rows)


def _now_iso() -> str:
    from src.outreach_crm import _now_iso as now

    return now()


def _diagnostics_lookup() -> dict[tuple[str, str], dict[str, str]]:
    rows = read_csv(DIAGNOSTICS_CSV, DIAGNOSTICS_COLUMNS)
    lookup: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row.get("state", "").upper(), row.get("jurisdiction_name", "").strip())
        lookup[key] = row
    return lookup


def _working_candidates() -> list[dict[str, str]]:
    working = read_csv(WORKING_CSV, WORKING_COLUMNS)
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in working:
        if row.get("jurisdiction_match_status") == "mismatch":
            continue
        email = (row.get("email") or "").strip().lower()
        if not email or is_generic_email(email):
            continue
        if classify_email(email, row.get("contact_name", ""), True) != "direct":
            continue
        if not row.get("contact_name"):
            continue
        key = (
            email,
            row.get("state", "").upper(),
            row.get("jurisdiction_name", "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        candidates.append(row)
    return candidates


def _jurisdiction_url(working_row: dict[str, str], diag_row: dict[str, str] | None) -> str:
    for field in ("official_website_url", "planning_department_url"):
        val = (working_row.get(field) or "").strip()
        if val:
            return val
    if diag_row:
        domain = (diag_row.get("official_domain") or "").strip()
        if domain:
            return f"https://{domain}"
    return ""


def _build_row_from_sources(
    working_row: dict[str, str],
    diag_row: dict[str, str] | None,
) -> dict[str, str]:
    greeting = greeting_name_from_contact_name(working_row.get("contact_name", ""))
    default = load_default_message()
    jurisdiction_type = working_row.get("geography_type") or (
        diag_row.get("geography_type", "") if diag_row else ""
    )
    population = working_row.get("population") or (
        diag_row.get("population", "") if diag_row else ""
    )
    row = empty_outreach_row()
    row.update(
        {
            "approved": "",
            "greeting_name": greeting,
            "send_status": PREPARED_STATUS,
            "sent_at": "",
            "reply_status": "not_sent",
            "first_reply_at": "",
            "meeting_requested": "",
            "meeting_scheduled_for": "",
            "meeting_completed": "",
            "follow_up_needed": "",
            "follow_up_at": "",
            "outreach_notes": "",
            "jurisdiction_type": jurisdiction_type,
            "population": str(population),
            "jurisdiction_name": working_row.get("jurisdiction_name", ""),
            "state": working_row.get("state", ""),
            "contact_name": working_row.get("contact_name", ""),
            "contact_title": working_row.get("contact_title", ""),
            "email": (working_row.get("email") or "").strip().lower(),
            "jurisdiction_url": _jurisdiction_url(working_row, diag_row),
            "email_source_url": working_row.get("email_source_url", "")
            or working_row.get("candidate_source_url", ""),
            "subject": default.subject,
            "body": default.body,
            "message_customized": "",
            "default_message_version": str(default.version),
            "gmail_draft_id": "",
            "gmail_message_id": "",
            "prepared_at": _now_iso(),
            "approved_at": "",
            "drafted_at": "",
            "error": "",
        }
    )
    return row


def prepare_outreach(
    *,
    append_only: bool = False,
    processed_jurisdiction_keys: set[tuple[str, str]] | None = None,
) -> tuple[int, int, PrepareStats]:
    """Merge working + diagnostics into outreach.csv. Returns (total_rows, new_rows, stats)."""
    existing_rows = read_outreach_rows()
    result: list[dict[str, str]] = [dict(r) for r in existing_rows]
    diag_lookup = _diagnostics_lookup()
    stats = PrepareStats()
    working = read_csv(WORKING_CSV, WORKING_COLUMNS)
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for row in working:
        if row.get("jurisdiction_match_status") == "mismatch":
            stats.mismatch_skipped += 1
            continue
        email = (row.get("email") or "").strip().lower()
        if not email or is_generic_email(email):
            stats.generic_skipped += 1
            continue
        if classify_email(email, row.get("contact_name", ""), True) != "direct":
            stats.generic_skipped += 1
            continue
        if not row.get("contact_name"):
            stats.generic_skipped += 1
            continue
        key = (
            email,
            row.get("state", "").upper(),
            row.get("jurisdiction_name", "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        candidates.append(row)

    stats.candidates_eligible = len(candidates)

    for working_row in candidates:
        key = (
            (working_row.get("email") or "").strip().lower(),
            working_row.get("state", "").upper(),
            working_row.get("jurisdiction_name", "").strip(),
        )
        diag = diag_lookup.get((key[1], key[2]))
        fresh = _build_row_from_sources(working_row, diag)

        matched_idx: int | None = None
        dup_kind: str | None = None
        for i, existing in enumerate(result):
            kind = classify_duplicate(existing, fresh)
            if kind:
                matched_idx = i
                dup_kind = kind
                break

        if matched_idx is not None:
            result[matched_idx] = merge_outreach_row(result[matched_idx], fresh)
            stats.merged_updates += 1
            cand_j_key = jurisdiction_match_key(fresh.get("state", ""), fresh.get("jurisdiction_name", ""))
            count_dup = (
                processed_jurisdiction_keys is None or cand_j_key in processed_jurisdiction_keys
            )
            if count_dup:
                stats.duplicate_after_crawl += 1
                if dup_kind == "duplicate_email":
                    stats.duplicate_email += 1
                elif dup_kind == "duplicate_contact_jurisdiction":
                    stats.duplicate_contact_jurisdiction += 1
                elif dup_kind == "duplicate_source_name":
                    stats.duplicate_source_name += 1
                elif dup_kind == "duplicate_email_jurisdiction":
                    stats.duplicate_email_jurisdiction += 1
            continue

        result.append(fresh)
        stats.new_added += 1

    if not append_only:
        result.sort(key=lambda r: (r.get("state", ""), r.get("jurisdiction_name", ""), r.get("email", "")))

    write_outreach_rows(result)
    return len(result), stats.new_added, stats


def update_outreach_rows(updates: list[dict[str, str]]) -> None:
    """Save CRM edits from UI."""
    rows = read_outreach_rows()
    updated = save_crm_rows(updates, rows)
    write_outreach_rows(updated)


def delete_outreach_row(orig_email: str, orig_state: str, orig_jurisdiction: str) -> bool:
    """Remove one outreach row by its original key."""
    rows = read_outreach_rows()
    key = (
        orig_email.strip().lower(),
        orig_state.strip().upper(),
        orig_jurisdiction.strip(),
    )
    kept = [r for r in rows if outreach_key(r) != key]
    if len(kept) == len(rows):
        return False
    write_outreach_rows(kept)
    return True


def is_approved(row: dict[str, str]) -> bool:
    return (row.get("approved") or "").strip().lower() in ("yes", "true", "1")


def is_valid_email_address(email: str) -> bool:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False
    local, _, domain = email.partition("@")
    return bool(local.strip()) and bool(domain.strip()) and "." in domain


def is_outreach_sendable(row: dict[str, str]) -> bool:
    """Harvest/draft eligibility: requires a non-generic direct email."""
    email = (row.get("email") or "").strip().lower()
    if not email or is_generic_email(email):
        return False
    subject, body = render_row_email(row)
    if not subject.strip():
        return False
    if not body.strip():
        return False
    return True


def is_manually_sendable(row: dict[str, str]) -> bool:
    """Manual CRM queue/send: any syntactically valid email if Ready."""
    email = (row.get("email") or "").strip().lower()
    if not is_valid_email_address(email):
        return False
    subject, body = render_row_email(row)
    if not subject.strip():
        return False
    if not body.strip():
        return False
    return True


def row_has_generic_email(row: dict[str, str]) -> bool:
    email = (row.get("email") or "").strip().lower()
    return bool(email) and is_generic_email(email)


def ready_queue_skip_reason(row: dict[str, str]) -> str | None:
    """Why an approved row cannot be queued, or None if eligible."""
    if not is_approved(row):
        return None
    status = row.get("send_status") or ""
    if status == SENT_STATUS:
        return "already sent"
    if status == QUEUED_STATUS:
        return "already queued"
    if status == SENDING_STATUS:
        return "currently sending"
    email = (row.get("email") or "").strip().lower()
    if not email:
        return "missing email"
    if not is_valid_email_address(email):
        return "invalid email"
    subject, body = render_row_email(row)
    if not subject.strip():
        return "missing subject"
    if not body.strip():
        return "missing message"
    return None


def ready_send_candidates(rows: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    rows = rows if rows is not None else read_outreach_rows()
    return [row for row in rows if is_ready(row) and ready_queue_skip_reason(row) is None]


def save_default_message_for_outreach(subject: str, body: str) -> DefaultMessage:
    saved = save_default_message(DefaultMessage(subject=subject.strip(), body=body, version=0))
    rows = read_outreach_rows()
    for row in rows:
        if row.get("send_status") == SENT_STATUS:
            continue
        if is_message_customized(row):
            continue
        apply_default_templates_to_row(row, saved)
    write_outreach_rows(rows)
    return saved


def save_row_message(
    orig_email: str,
    orig_state: str,
    orig_jurisdiction: str,
    subject: str,
    body: str,
) -> bool:
    rows = read_outreach_rows()
    key = (
        orig_email.strip().lower(),
        orig_state.strip().upper(),
        orig_jurisdiction.strip(),
    )
    for row in rows:
        if outreach_key(row) == key:
            row["subject"] = subject.strip()
            row["body"] = body
            row["message_customized"] = "yes"
            write_outreach_rows(rows)
            return True
    return False


def row_message_templates(row: dict[str, str]) -> tuple[str, str]:
    if is_message_customized(row) and (row.get("subject") or row.get("body")):
        return (row.get("subject") or "").strip(), (row.get("body") or "").strip()
    default = load_default_message()
    return default.subject, default.body


def next_draft_candidate(rows: list[dict[str, str]] | None = None) -> dict[str, str] | None:
    rows = rows if rows is not None else read_outreach_rows()
    for row in rows:
        if row.get("send_status") == SENT_STATUS:
            continue
        if row.get("send_status") == DRAFTED_STATUS and row.get("gmail_draft_id"):
            continue
        if not is_approved(row):
            continue
        if not is_outreach_sendable(row):
            continue
        return row
    return None


def next_send_candidate(rows: list[dict[str, str]] | None = None) -> dict[str, str] | None:
    rows = rows if rows is not None else read_outreach_rows()
    for row in rows:
        if row.get("send_status") != DRAFTED_STATUS:
            continue
        if not row.get("gmail_draft_id"):
            continue
        return row
    return None


def apply_draft_result(row: dict[str, str], draft_id: str) -> None:
    rows = read_outreach_rows()
    key = outreach_key(row)
    for r in rows:
        if outreach_key(r) == key:
            r["send_status"] = DRAFTED_STATUS
            r["gmail_draft_id"] = draft_id
            r["drafted_at"] = _now_iso()
            r["error"] = ""
            break
    write_outreach_rows(rows)


def apply_send_result(row: dict[str, str], message_id: str) -> None:
    rows = read_outreach_rows()
    key = outreach_key(row)
    for r in rows:
        if outreach_key(r) == key:
            r["send_status"] = SENT_STATUS
            r["gmail_message_id"] = message_id
            r["sent_at"] = _now_iso()
            r["approved"] = ""
            r["error"] = ""
            apply_send_side_effects(r)
            break
    write_outreach_rows(rows)


def apply_failure(row: dict[str, str], error: str) -> None:
    rows = read_outreach_rows()
    key = outreach_key(row)
    for r in rows:
        if outreach_key(r) == key:
            r["send_status"] = "failed"
            r["error"] = error[:500]
            r["send_error"] = error[:500]
            break
    write_outreach_rows(rows)
