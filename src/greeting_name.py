"""Extract first-name greeting from contact names."""

from __future__ import annotations

import re

HONORIFICS = frozenset({"dr", "mr", "mrs", "ms", "miss", "prof", "professor"})
CREDENTIALS = frozenset({"aicp", "pe", "pmp", "faicp", "asla", "aia", "phd", "md", "esq"})
TITLE_WORDS = frozenset(
    {
        "planning",
        "director",
        "manager",
        "administrator",
        "coordinator",
        "planner",
        "department",
        "community",
        "development",
        "services",
    }
)
SKIP_TOKENS = frozenset({"contact", "information"})


def greeting_name_from_contact_name(contact_name: str) -> str:
    """
    Return a first-name greeting, or 'there' when not confident.

    Nicole DeVaughn -> Nicole
    Thomas Mooney -> Thomas
    Dr. Jane Smith -> Jane
    Sara Rutkowski, AICP -> Sara
    """
    raw = (contact_name or "").strip()
    if not raw:
        return "there"

    # Use portion before comma (drop credentials)
    primary = raw.split(",", 1)[0].strip()
    primary = re.sub(r"\([^)]*\)", "", primary).strip()
    tokens = [t for t in re.split(r"\s+", primary) if t]
    if not tokens:
        return "there"

    cleaned: list[str] = []
    for token in tokens:
        bare = re.sub(r"[^A-Za-z.\-']", "", token)
        if not bare:
            continue
        lower = bare.lower().rstrip(".")
        if lower in HONORIFICS:
            continue
        if lower in CREDENTIALS:
            continue
        if lower in SKIP_TOKENS:
            continue
        cleaned.append(bare)

    if not cleaned:
        return "there"
    if all(re.sub(r"[^a-z]", "", t.lower()) in TITLE_WORDS for t in cleaned):
        return "there"

    first = cleaned[0]
    if not re.match(r"^[A-Za-z][A-Za-z\-']+$", first):
        return "there"
    if len(first) < 2:
        return "there"
    if first.isupper() and len(first) <= 2:
        return "there"

    return first[0].upper() + first[1:].lower()
