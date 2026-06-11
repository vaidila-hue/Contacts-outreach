"""Gmail API OAuth client for outreach drafts and sends."""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Protocol

from src.paths import EXPECTED_GMAIL_ACCOUNT, GMAIL_CACHE_DIR, ROOT

GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
)


class GmailService(Protocol):
    def get_profile_email(self) -> str: ...

    def create_draft(self, to_email: str, subject: str, body: str) -> str: ...

    def send_draft(self, draft_id: str) -> str: ...

    def send_message(self, to_email: str, subject: str, body: str) -> str: ...


class GmailAccountError(Exception):
    pass


class MockGmailService:
    """In-memory Gmail stub for tests."""

    def __init__(self, account: str = EXPECTED_GMAIL_ACCOUNT):
        self.account = account
        self.drafts: dict[str, dict[str, str]] = {}
        self.sent: list[str] = []
        self._counter = 0

    def get_profile_email(self) -> str:
        return self.account

    def create_draft(self, to_email: str, subject: str, body: str) -> str:
        self._counter += 1
        draft_id = f"draft-{self._counter}"
        self.drafts[draft_id] = {
            "to": to_email,
            "subject": subject,
            "body": body,
        }
        return draft_id

    def send_draft(self, draft_id: str) -> str:
        if draft_id not in self.drafts:
            raise ValueError(f"Unknown draft id: {draft_id}")
        self._counter += 1
        message_id = f"msg-{self._counter}"
        self.sent.append(draft_id)
        return message_id

    def send_message(self, to_email: str, subject: str, body: str) -> str:
        self._counter += 1
        draft_id = f"draft-{self._counter}"
        self.drafts[draft_id] = {"to": to_email, "subject": subject, "body": body}
        return self.send_draft(draft_id)


def _credentials_path() -> Path:
    return ROOT / "credentials.json"


def _token_path() -> Path:
    return ROOT / "token.json"


def _build_message(to_email: str, subject: str, body: str) -> dict[str, str]:
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = to_email
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    return {"raw": raw}


def verify_gmail_account(service: GmailService) -> str:
    email = (service.get_profile_email() or "").strip().lower()
    expected = EXPECTED_GMAIL_ACCOUNT.lower()
    if email != expected:
        raise GmailAccountError(
            f"Authenticated Gmail account is {email!r}, expected {expected!r}. "
            "Delete token.json and re-authenticate with the correct account."
        )
    return email


def build_gmail_service() -> GmailService:
    """Build real Gmail API service using OAuth credentials."""
    creds_path = _credentials_path()
    token_path = _token_path()
    if not creds_path.exists():
        raise FileNotFoundError(
            f"Missing {creds_path.name}. Download OAuth client credentials from Google Cloud Console."
        )

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    GMAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    api = build("gmail", "v1", credentials=creds, cache_discovery=False)

    class _RealGmailService:
        def get_profile_email(self) -> str:
            profile = api.users().getProfile(userId="me").execute()
            return profile.get("emailAddress", "")

        def create_draft(self, to_email: str, subject: str, body: str) -> str:
            draft_body = {
                "message": _build_message(to_email, subject, body),
            }
            draft = api.users().drafts().create(userId="me", body=draft_body).execute()
            return draft.get("id", "")

        def send_draft(self, draft_id: str) -> str:
            result = (
                api.users()
                .drafts()
                .send(userId="me", body={"id": draft_id})
                .execute()
            )
            return result.get("id", "")

        def send_message(self, to_email: str, subject: str, body: str) -> str:
            result = (
                api.users()
                .messages()
                .send(userId="me", body=_build_message(to_email, subject, body))
                .execute()
            )
            return result.get("id", "")

    return _RealGmailService()


def preview_action(action: str, row: dict[str, str]) -> str:
    return (
        f"{action}: to={row.get('email')} subject={row.get('subject')!r} "
        f"greeting={row.get('greeting_name')!r} jurisdiction={row.get('jurisdiction_name')}, {row.get('state')}"
    )
