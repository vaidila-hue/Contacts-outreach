"""Export working, rejected, and outreach CSVs."""

from __future__ import annotations

from src.csv_utils import read_csv, write_csv
from src.extract_emails import classify_email, is_generic_email
from src.paths import (
    DIAGNOSTICS_COLUMNS,
    DIAGNOSTICS_CSV,
    OUTREACH_COLUMNS,
    OUTREACH_CSV,
    REJECTED_COLUMNS,
    REJECTED_CSV,
    WORKING_COLUMNS,
    WORKING_CSV,
)
from src.review_html import write_review_html

MATCH_SORT_ORDER = {"matched": 0, "uncertain": 1, "mismatch": 2}
PRIORITY_SORT_ORDER = {"high": 0, "medium": 1, "unknown": 2, "low": 3, "research_only": 4}


def sort_working_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(
        rows,
        key=lambda r: (
            MATCH_SORT_ORDER.get(r.get("jurisdiction_match_status", ""), 9),
            PRIORITY_SORT_ORDER.get(r.get("prospect_priority", ""), 9),
            r.get("state", ""),
            r.get("jurisdiction_name", ""),
        ),
    )


def filter_working_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        r for r in rows
        if r.get("jurisdiction_match_status") != "mismatch"
    ]


def export_outreach(working_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Legacy helper: return outreach rows for approved working records (deprecated schema)."""
    from src.outreach_store import prepare_outreach

    prepare_outreach()
    from src.outreach_store import read_outreach_rows

    return read_outreach_rows()


def write_outreach_csv(rows: list[dict[str, str]]) -> None:
    from src.outreach_store import write_outreach_rows

    write_outreach_rows(rows)


def write_working_csv(rows: list[dict[str, str]]) -> None:
    cleaned = sort_working_rows(filter_working_rows(rows))
    write_csv(WORKING_CSV, cleaned, WORKING_COLUMNS)
    write_review_html(cleaned)


def write_rejected_csv(rows: list[dict[str, str]]) -> None:
    write_csv(REJECTED_CSV, rows, REJECTED_COLUMNS)


def write_diagnostics_csv(rows: list[dict[str, str]]) -> None:
    write_csv(DIAGNOSTICS_CSV, rows, DIAGNOSTICS_COLUMNS)


def clear_output_csvs(*, clear_outreach: bool = False) -> None:
    """Reset working, rejected, and diagnostics CSVs to empty (headers only).

    Outreach (CRM system of record) is preserved unless clear_outreach=True.
    """
    write_csv(WORKING_CSV, [], WORKING_COLUMNS)
    write_csv(REJECTED_CSV, [], REJECTED_COLUMNS)
    write_csv(DIAGNOSTICS_CSV, [], DIAGNOSTICS_COLUMNS)
    if clear_outreach:
        from src.outreach_store import write_outreach_rows

        write_outreach_rows([])
    write_review_html([])


def export_only() -> tuple[int, int]:
    """Regenerate outreach.csv and review.html from prospects_working.csv without discovery."""
    working = read_csv(WORKING_CSV, WORKING_COLUMNS)
    cleaned = sort_working_rows(filter_working_rows(working))
    write_csv(WORKING_CSV, cleaned, WORKING_COLUMNS)
    write_review_html(cleaned)
    outreach = export_outreach(cleaned)
    write_outreach_csv(outreach)
    return len(cleaned), len(outreach)


def merge_working_row(existing: list[dict[str, str]], new_row: dict[str, str]) -> list[dict[str, str]]:
    """Upsert a working row by jurisdiction key, preserving manual review fields."""
    if new_row.get("jurisdiction_match_status") == "mismatch":
        return existing
    key = (new_row["state"], new_row["jurisdiction_name"], new_row["geography_type"])
    updated: list[dict[str, str]] = []
    found = False
    for row in existing:
        rk = (row["state"], row["jurisdiction_name"], row["geography_type"])
        if rk == key:
            found = True
            merged = dict(new_row)
            if row.get("review_status") in ("approved", "rejected"):
                merged["review_status"] = row["review_status"]
            if row.get("outreach_status"):
                merged["outreach_status"] = row["outreach_status"]
            updated.append(merged)
        else:
            updated.append(row)
    if not found:
        updated.append(new_row)
    return updated
