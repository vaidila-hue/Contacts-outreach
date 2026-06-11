"""Manual URL overrides for jurisdictions where search misses real pages."""

from __future__ import annotations

from dataclasses import dataclass

from src.csv_utils import read_csv
from src.jurisdiction_utils import normalize_jurisdiction_name
from src.paths import MANUAL_URLS_CSV

MANUAL_URL_COLUMNS = [
    "state",
    "jurisdiction_name",
    "url",
    "url_type",
    "notes",
]

VALID_URL_TYPES = frozenset(
    {"official_site", "planning_page", "staff_directory", "pdf"}
)


@dataclass(frozen=True)
class ManualUrlEntry:
    state: str
    jurisdiction_name: str
    url: str
    url_type: str
    notes: str = ""


def load_manual_urls(path=None) -> list[ManualUrlEntry]:
    path = path or MANUAL_URLS_CSV
    rows = read_csv(path, MANUAL_URL_COLUMNS)
    entries: list[ManualUrlEntry] = []
    for row in rows:
        url = (row.get("url") or "").strip()
        url_type = (row.get("url_type") or "").strip().lower()
        if not url or url_type not in VALID_URL_TYPES:
            continue
        entries.append(
            ManualUrlEntry(
                state=(row.get("state") or "").strip().upper(),
                jurisdiction_name=normalize_jurisdiction_name(
                    (row.get("jurisdiction_name") or "").strip()
                ),
                url=url,
                url_type=url_type,
                notes=(row.get("notes") or "").strip(),
            )
        )
    return entries


def manual_urls_for_jurisdiction(
    entries: list[ManualUrlEntry],
    state: str,
    jurisdiction_name: str,
) -> list[ManualUrlEntry]:
    display = normalize_jurisdiction_name(jurisdiction_name)
    state = state.upper()
    return [
        e
        for e in entries
        if e.state == state and e.jurisdiction_name == display
    ]
