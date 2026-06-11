"""Shared discovery row builders and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.census_seed import Jurisdiction
from src.csv_utils import empty_row
from src.paths import WORKING_COLUMNS
from src.person_first_discovery import PersonFirstResult

RI_COUNTY_NOTE = (
    "Rhode Island counties are geographic/statistical units for this use case; "
    "no county planning government searched."
)


@dataclass
class DiscoverDiagnostics:
    official_site_found: bool = False
    planning_page_found: bool = False
    pages_fetched_count: int = 0
    pdfs_fetched_count: int = 0
    raw_emails_found_count: int = 0
    generic_emails_found_count: int = 0
    candidate_titles_found_count: int = 0
    direct_email_candidates_count: int = 0
    raw_emails: list[str] = field(default_factory=list)
    generic_emails: list[str] = field(default_factory=list)
    search_urls_found: int = 0
    search_urls_fetched: int = 0
    manual_url_used: str = ""
    manual_url_result: str = ""
    search_queries_run: int = 0


def working_row_from_jurisdiction(j: Jurisdiction) -> dict[str, str]:
    row = empty_row(WORKING_COLUMNS)
    row.update(
        {
            "state": j.state,
            "jurisdiction_name": j.jurisdiction_name,
            "geography_type": j.geography_type,
            "population": str(j.population),
            "county_name": j.county_name,
            "official_website_url": j.official_website_url,
            "review_status": "pending",
            "outreach_status": "not_started",
            "_status": "pending",
        }
    )
    return row


def working_row_from_contact(
    j: Jurisdiction,
    *,
    official: str | None,
    planning_url: str,
    contact_name: str,
    contact_title: str,
    email: str,
    email_source_url: str,
    candidate_source_url: str,
    discovery_method: str,
    plan_year: str = "",
    update_signal: str = "",
    priority: str = "",
    priority_reason: str = "",
    match_status: str = "",
    match_notes: str = "",
    notes: str = "",
) -> dict[str, str]:
    row = working_row_from_jurisdiction(j)
    row["official_website_url"] = official or ""
    row["planning_department_url"] = planning_url
    row["contact_name"] = contact_name
    row["contact_title"] = contact_title
    row["email"] = email
    row["email_source_url"] = email_source_url
    row["candidate_source_url"] = candidate_source_url
    row["discovery_method"] = discovery_method
    row["latest_plan_year_found"] = plan_year
    row["active_update_signal"] = update_signal
    row["prospect_priority"] = priority
    row["prospect_priority_reason"] = priority_reason
    row["jurisdiction_match_status"] = match_status
    row["jurisdiction_match_notes"] = match_notes
    row["notes"] = notes
    row["review_status"] = "pending"
    row["_status"] = "done"
    return row


def reject_row(
    j: Jurisdiction,
    reason: str,
    email_found: str = "",
    sources: str = "",
    notes: str = "",
    diag: DiscoverDiagnostics | None = None,
    pf: PersonFirstResult | None = None,
    *,
    discovery_method: str = "",
    email_source_url: str = "",
    jurisdiction_match_notes: str = "",
) -> dict[str, str]:
    d = diag or DiscoverDiagnostics()
    return {
        "state": j.state,
        "jurisdiction_name": j.jurisdiction_name,
        "geography_type": j.geography_type,
        "population": str(j.population),
        "rejection_reason": reason,
        "email_found": email_found or (pf.email if pf else ""),
        "source_urls": sources,
        "notes": notes,
        "official_site_found": "yes" if d.official_site_found else "no",
        "planning_page_found": "yes" if d.planning_page_found else "no",
        "pages_fetched_count": str(d.pages_fetched_count),
        "pdfs_fetched_count": str(d.pdfs_fetched_count),
        "raw_emails_found_count": str(d.raw_emails_found_count),
        "generic_emails_found_count": str(d.generic_emails_found_count),
        "candidate_titles_found_count": str(d.candidate_titles_found_count),
        "direct_email_candidates_count": str(d.direct_email_candidates_count),
        "best_rejection_reason": reason,
        "search_urls_found": str(d.search_urls_found),
        "search_urls_fetched": str(d.search_urls_fetched),
        "manual_url_used": d.manual_url_used,
        "manual_url_result": d.manual_url_result,
        "candidate_source_url": pf.candidate_source_url if pf else email_source_url,
        "email_source_url": pf.email_source_url if pf else email_source_url,
        "discovery_method": pf.discovery_method if pf else discovery_method,
        "jurisdiction_match_notes": (
            pf.jurisdiction_match_notes if pf else jurisdiction_match_notes
        ),
        "candidate_name": pf.contact_name if pf else "",
        "candidate_title": pf.contact_title if pf else "",
    }
