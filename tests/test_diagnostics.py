"""Tests for rejection diagnostics columns."""

from src.census_seed import Jurisdiction
from src.run import DiscoverDiagnostics, _reject_row


def test_reject_row_includes_search_and_manual_diagnostics():
    j = Jurisdiction(state="DE", jurisdiction_name="Dover", geography_type="city", population=39491)
    diag = DiscoverDiagnostics(
        search_urls_found=5,
        search_urls_fetched=2,
        manual_url_used="https://example.gov/staff",
        manual_url_result="staff_directory:ok",
    )
    row = _reject_row(j, "no_planning_contact_found", diag=diag)
    assert row["search_urls_found"] == "5"
    assert row["search_urls_fetched"] == "2"
    assert row["manual_url_used"] == "https://example.gov/staff"
    assert row["manual_url_result"] == "staff_directory:ok"
