"""Direct vs generic email classification."""

from __future__ import annotations

import re
from dataclasses import dataclass

EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

GENERIC_LOCAL_PARTS: frozenset[str] = frozenset(
    {
        "planning",
        "info",
        "contact",
        "zoning",
        "communitydevelopment",
        "commdev",
        "cd",
        "admin",
        "department",
        "clerk",
        "office",
        "planningdept",
        "noreply",
        "donotreply",
        "webmaster",
        "helpdesk",
        "customerservice",
        "publicworks",
        "building",
        "permits",
    }
)


@dataclass
class EmailCandidate:
    email: str
    source_url: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


def extract_emails_from_text(text: str) -> list[str]:
    return list({normalize_email(m) for m in EMAIL_RE.findall(text or "")})


def local_part(email: str) -> str:
    return normalize_email(email).split("@", 1)[0]


def infer_name_from_email(email: str) -> str:
    """Best-effort name when staff page lists title + email only (manual review expected)."""
    lp = re.sub(r"[^a-z.\-]", "", local_part(email))
    if "." in lp:
        parts = [p for p in lp.split(".") if p]
        if len(parts) >= 2:
            return " ".join(p.capitalize() for p in parts[:2])
    if len(lp) > 3:
        return f"{lp[0].upper()}. {lp[1:].capitalize()}"
    return lp.capitalize()


def is_generic_email(email: str) -> bool:
    lp = local_part(email)
    lp_clean = re.sub(r"[^a-z0-9]", "", lp)
    if lp in GENERIC_LOCAL_PARTS or lp_clean in GENERIC_LOCAL_PARTS:
        return True
    for generic in GENERIC_LOCAL_PARTS:
        if lp == generic or lp.startswith(generic + ".") or lp.startswith(generic + "-"):
            return True
    return False


def _name_tokens(name: str) -> list[str]:
    parts = re.sub(r"[^a-zA-Z\s\-']", "", name).lower().split()
    return [p for p in parts if len(p) > 1]


def email_matches_name(email: str, name: str) -> bool:
    lp = re.sub(r"[^a-z0-9.\-]", "", local_part(email))
    tokens = _name_tokens(name)
    if len(tokens) < 2:
        return False
    first, last = tokens[0], tokens[-1]
    patterns = {
        f"{first}.{last}",
        f"{first}{last}",
        f"{first[0]}{last}",
        f"{first[0]}.{last}",
        f"{first}_{last}",
        f"{last}.{first}",
    }
    return lp in patterns or any(p in lp for p in patterns)


def is_direct_email(email: str, contact_name: str = "", paired_with_name: bool = False) -> bool:
    if is_generic_email(email):
        return False
    lp = local_part(email)
    if paired_with_name:
        return True
    if "." in lp or "-" in lp:
        parts = re.split(r"[.\-]", lp)
        if any(len(p) > 2 for p in parts):
            return True
    if contact_name and email_matches_name(email, contact_name):
        return True
    return False


def classify_email(email: str, contact_name: str = "", paired_with_name: bool = False) -> str:
    """Return 'direct', 'generic', or 'unclear'."""
    email = normalize_email(email)
    if is_generic_email(email):
        return "generic"
    if is_direct_email(email, contact_name, paired_with_name):
        return "direct"
    return "unclear"
