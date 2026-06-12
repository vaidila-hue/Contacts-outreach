"""CLI handlers for outreach prepare, draft, and send."""

from __future__ import annotations

import argparse
import time

from src.gmail_client import (
    GmailAccountError,
    GmailService,
    build_gmail_service,
    preview_action,
    verify_gmail_account,
)
from src.outreach_template import render_row_email
from src.outreach_store import (
    apply_draft_result,
    apply_failure,
    apply_send_result,
    is_outreach_sendable,
    is_ready,
    next_draft_candidate,
    next_send_candidate,
    prepare_outreach,
    read_outreach_rows,
    ready_send_candidates,
)
from src.paths import OUTREACH_CSV


def run_outreach_prepare() -> int:
    total, new_rows, _stats = prepare_outreach()
    print(f"Prepared {total} outreach rows ({new_rows} new) -> {OUTREACH_CSV}")
    return 0


def run_outreach_draft(args: argparse.Namespace, service: GmailService | None = None) -> int:
    limit = args.limit or 1
    dry_run = getattr(args, "dry_run", False)
    delay = getattr(args, "delay_seconds", 2.0)
    rows = read_outreach_rows()
    drafted = 0

    if not dry_run and service is None:
        try:
            service = build_gmail_service()
            verify_gmail_account(service)
        except (GmailAccountError, FileNotFoundError) as exc:
            print(f"ERROR: {exc}")
            return 1

    for _ in range(limit):
        row = next_draft_candidate(rows)
        if row is None:
            if drafted == 0:
                print("No approved outreach rows ready to draft.")
            break
        if not is_outreach_sendable(row):
            print(f"Skipping invalid row: {row.get('email')}")
            apply_failure(row, "invalid email or blank subject/body")
            rows = read_outreach_rows()
            continue

        print(preview_action("DRAFT", row))
        if dry_run:
            drafted += 1
            rows = [r for r in rows if r is not row]
            continue

        assert service is not None
        try:
            draft_id = service.create_draft(
                row["email"],
                row["subject"],
                row["body"],
            )
            apply_draft_result(row, draft_id)
            print(f"  Created Gmail draft id={draft_id}")
            drafted += 1
            rows = read_outreach_rows()
            if delay and drafted < limit:
                time.sleep(delay)
        except Exception as exc:
            apply_failure(row, str(exc))
            print(f"  Draft failed: {exc}")
            return 1

    if dry_run:
        print(f"Dry run: would draft {drafted} row(s).")
    else:
        print(f"Drafted {drafted} row(s).")
    return 0


def run_outreach_send(args: argparse.Namespace, service: GmailService | None = None) -> int:
    limit = args.limit or 1
    dry_run = getattr(args, "dry_run", False)
    delay = getattr(args, "delay_seconds", 2.0)
    force = getattr(args, "force", False)
    confirm_force = getattr(args, "confirm_force", False)

    if force and not confirm_force:
        print("ERROR: --force requires --confirm-force")
        return 1

    rows = read_outreach_rows()
    sent = 0

    if not dry_run and service is None:
        try:
            service = build_gmail_service()
            verify_gmail_account(service)
        except (GmailAccountError, FileNotFoundError) as exc:
            print(f"ERROR: {exc}")
            return 1

    for _ in range(limit):
        row = next_send_candidate(rows)
        if row is None:
            if sent == 0:
                print("No drafted outreach rows ready to send.")
            break

        if row.get("send_status") == "sent" and not force:
            print(f"Skipping already sent row: {row.get('email')}")
            continue

        print(preview_action("SEND", row))
        if dry_run:
            sent += 1
            continue

        assert service is not None
        try:
            message_id = service.send_draft(row["gmail_draft_id"])
            apply_send_result(row, message_id)
            print(f"  Sent Gmail message id={message_id}")
            sent += 1
            rows = read_outreach_rows()
            if delay and sent < limit:
                time.sleep(delay)
        except Exception as exc:
            apply_failure(row, str(exc))
            print(f"  Send failed: {exc}")
            return 1

    if dry_run:
        print(f"Dry run: would send {sent} row(s).")
    else:
        print(f"Sent {sent} row(s).")
    return 0


def run_outreach_send_ready(args: argparse.Namespace, service: GmailService | None = None) -> int:
    """Queue all Ready contacts for throttled sending (does not send immediately)."""
    from src.send_queue import queue_ready_contacts

    count, message = queue_ready_contacts()
    print(message)
    return 0 if count >= 0 else 1
