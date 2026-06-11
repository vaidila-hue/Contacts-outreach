"""Isolated outreach test email workflow (does not touch outreach.csv)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.gmail_client import GmailService, verify_gmail_account
from src.outreach_template import render_outreach_email
from src.paths import GMAIL_CACHE_DIR

TEST_RECIPIENT_EMAIL = "vaidila@gmail.com"
TEST_RECIPIENT_NAME = "Vaidila Satvika"
DEFAULT_TEST_GREETING = "Vaidila"

TEST_HISTORY_PATH = GMAIL_CACHE_DIR / "test_history.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def render_test_outreach(greeting_name: str = DEFAULT_TEST_GREETING) -> dict[str, str]:
    """Build test email content via the same template path as production outreach."""
    greeting = (greeting_name or DEFAULT_TEST_GREETING).strip() or DEFAULT_TEST_GREETING
    subject, body = render_outreach_email(greeting)
    return {
        "to_email": TEST_RECIPIENT_EMAIL,
        "contact_name": TEST_RECIPIENT_NAME,
        "greeting_name": greeting,
        "subject": subject,
        "body": body,
    }


def load_test_history() -> dict[str, str]:
    if not TEST_HISTORY_PATH.exists():
        return {}
    try:
        data = json.loads(TEST_HISTORY_PATH.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def save_test_history(**updates: str) -> dict[str, str]:
    GMAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    history = load_test_history()
    history.update({k: v for k, v in updates.items() if v is not None})
    TEST_HISTORY_PATH.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return history


def create_test_draft(
    service: GmailService,
    greeting_name: str,
    *,
    dry_run: bool = False,
) -> tuple[dict[str, str], str | None]:
    content = render_test_outreach(greeting_name)
    if dry_run:
        return content, None
    draft_id = service.create_draft(content["to_email"], content["subject"], content["body"])
    save_test_history(
        last_test_draft_at=_now_iso(),
        last_test_greeting=content["greeting_name"],
        last_test_draft_id=draft_id,
    )
    return content, draft_id


def send_test_email(
    service: GmailService,
    greeting_name: str,
    *,
    dry_run: bool = False,
) -> tuple[dict[str, str], str | None, str | None]:
    """
    Send test email using production Gmail path: create draft, then send draft.
    """
    content = render_test_outreach(greeting_name)
    if dry_run:
        return content, None, None
    draft_id = service.create_draft(content["to_email"], content["subject"], content["body"])
    message_id = service.send_draft(draft_id)
    save_test_history(
        last_test_send_at=_now_iso(),
        last_test_greeting=content["greeting_name"],
        last_test_draft_id=draft_id,
        last_test_message_id=message_id,
    )
    return content, draft_id, message_id


def run_test_draft(greeting_name: str, service: GmailService | None = None) -> tuple[int, str]:
    if service is None:
        from src.gmail_client import build_gmail_service

        service = build_gmail_service()
        verify_gmail_account(service)
    content, draft_id = create_test_draft(service, greeting_name)
    return 0, f"Test draft created (id={draft_id}) for {content['to_email']}."


def run_test_send(greeting_name: str, service: GmailService | None = None) -> tuple[int, str]:
    if service is None:
        from src.gmail_client import build_gmail_service

        service = build_gmail_service()
        verify_gmail_account(service)
    content, draft_id, message_id = send_test_email(service, greeting_name)
    return 0, f"Test email sent (message id={message_id}) to {content['to_email']}."
