"""Lightweight plan-year and active-update metadata."""

from __future__ import annotations

import re
from datetime import datetime

PLAN_PHRASES = (
    "comprehensive plan",
    "master plan",
    "general plan",
    "comp plan",
    "future land use",
)

UPDATE_PHRASES = (
    "comprehensive plan update",
    "plan update",
    "planning process",
    "rfq",
    "rfp",
    "request for proposals",
    "underway",
    "public hearing",
    "draft plan",
)


def extract_plan_metadata(text: str) -> tuple[str, str]:
    """Return (latest_plan_year_found, active_update_signal)."""
    if not text:
        return "", ""
    lower = text.lower()
    current_year = datetime.now().year
    years: list[int] = []
    for phrase in PLAN_PHRASES:
        for m in re.finditer(re.escape(phrase) + r".{0,40}(20\d{2}|19\d{2})", lower):
            years.append(int(m.group(1)))
        for m in re.finditer(r"(20\d{2}|19\d{2}).{0,40}" + re.escape(phrase), lower):
            years.append(int(m.group(1)))
    latest = str(max(years)) if years else ""

    signal = ""
    for phrase in UPDATE_PHRASES:
        if phrase in lower:
            signal = phrase
            break
    if signal:
        for y in range(current_year, current_year - 2, -1):
            if str(y) in text:
                signal = f"{signal} ({y})"
                break
    return latest, signal
