"""Default outreach message persistence and template rendering."""

from __future__ import annotations

import json
from dataclasses import dataclass

from src.paths import DEFAULT_MESSAGE_JSON

DEFAULT_SUBJECT = "Question from a fellow planner"

DEFAULT_BODY_TEMPLATE = """Hi {greeting_name},

I'm an urban planner developing software to help towns and cities generate comprehensive plans faster and more affordably, driven by community goals and preferences.

Would you be willing to share 10-15 minutes of candid feedback to help me understand what is needed, what would be considered useful, and what would make this genuinely helpful for local planning staff?

Your experience and input would help shape something genuinely useful.

Thank you for considering this request.

Sincerely,
Vaidila"""


@dataclass
class DefaultMessage:
    subject: str
    body: str
    version: int = 1

    def as_dict(self) -> dict[str, str | int]:
        return {"subject": self.subject, "body": self.body, "version": self.version}


def default_message() -> DefaultMessage:
    return DefaultMessage(subject=DEFAULT_SUBJECT, body=DEFAULT_BODY_TEMPLATE, version=1)


def load_default_message() -> DefaultMessage:
    if not DEFAULT_MESSAGE_JSON.exists():
        return default_message()
    try:
        raw = json.loads(DEFAULT_MESSAGE_JSON.read_text(encoding="utf-8"))
        defaults = default_message()
        return DefaultMessage(
            subject=str(raw.get("subject", defaults.subject)),
            body=str(raw.get("body", defaults.body)),
            version=int(raw.get("version", defaults.version)),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return default_message()


def save_default_message(message: DefaultMessage) -> DefaultMessage:
    DEFAULT_MESSAGE_JSON.parent.mkdir(parents=True, exist_ok=True)
    current = load_default_message()
    next_version = (current.version + 1) if DEFAULT_MESSAGE_JSON.exists() else 1
    saved = DefaultMessage(subject=message.subject, body=message.body, version=next_version)
    DEFAULT_MESSAGE_JSON.write_text(json.dumps(saved.as_dict(), indent=2), encoding="utf-8")
    return saved


def greeting_name_value(row: dict[str, str]) -> str:
    name = (row.get("greeting_name") or "there").strip()
    return name or "there"


def render_template_text(template: str, greeting_name: str) -> str:
    if "{greeting_name}" in template:
        return template.format(greeting_name=greeting_name)
    return template


def templates_for_row(row: dict[str, str]) -> tuple[str, str]:
    default = load_default_message()
    if is_message_customized(row):
        return (row.get("subject") or "").strip(), (row.get("body") or "").strip()
    subject = (row.get("subject") or "").strip() or default.subject
    body = (row.get("body") or "").strip() or default.body
    return subject, body


def render_row_email(row: dict[str, str]) -> tuple[str, str]:
    greeting = greeting_name_value(row)
    subject_tpl, body_tpl = templates_for_row(row)
    return render_template_text(subject_tpl, greeting), render_template_text(body_tpl, greeting)


def apply_default_templates_to_row(row: dict[str, str], message: DefaultMessage | None = None) -> None:
    msg = message or load_default_message()
    row["subject"] = msg.subject
    row["body"] = msg.body
    row["default_message_version"] = str(msg.version)


def is_message_customized(row: dict[str, str]) -> bool:
    return (row.get("message_customized") or "").lower() in ("yes", "true", "1")


def render_outreach_email(greeting_name: str) -> tuple[str, str]:
    """Render using the saved default message templates."""
    row = {"greeting_name": greeting_name}
    default = load_default_message()
    row["subject"] = default.subject
    row["body"] = default.body
    return render_row_email(row)
