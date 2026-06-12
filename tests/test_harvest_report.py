"""Tests for harvest report analysis."""

from src.harvest_summary import HarvestRunSummary
from src.harvest_report import (
    analyze_harvest_run,
    discovery_implementation_label,
    format_harvest_dashboard,
    render_harvest_report_md,
)


def test_discovery_implementation_label_is_site_discovery():
    assert discovery_implementation_label() == "site_discovery_v1"


def test_analyze_last_run_rejection_breakdown():
    summary = HarvestRunSummary(
        jurisdictions_processed_count=60,
        processed_jurisdictions=[
            {"state": "CA", "jurisdiction_name": "Merced", "geography_type": "city", "population": "89000"},
            {"state": "MN", "jurisdiction_name": "Bloomington", "geography_type": "city", "population": "88000"},
        ],
        candidates_found_count=5,
        candidates_added_count=6,
    )
    rejected = [
        {
            "state": "CA",
            "jurisdiction_name": "Merced",
            "rejection_reason": "no_official_site_found",
            "notes": "Could not resolve official website (guess + one search)",
        },
        {
            "state": "MN",
            "jurisdiction_name": "Bloomington",
            "rejection_reason": "no_official_site_found",
            "notes": "Could not resolve official website (guess + one search)",
        },
    ]
    analysis = analyze_harvest_run(summary, diagnostics_rows=[], rejected_rows=rejected, working_rows=[])
    assert analysis.rejection_breakdown["no_official_site_found"] == 2
    assert analysis.recommendation_code == "B"
    assert analysis.discovery_implementation.startswith("legacy")


def test_format_harvest_dashboard():
    summary = HarvestRunSummary(
        run_completed_at="2026-06-11T23:17:42+00:00",
        jurisdictions_processed_count=60,
        jurisdictions_skipped_existing_count=25,
        candidates_added_count=6,
        duplicates_skipped_count=38,
        no_official_site_count=35,
        no_planning_contact_count=7,
        discovery_implementation="legacy",
    )
    dash = format_harvest_dashboard(summary)
    assert dash["jurisdictions_processed"] == "60"
    assert dash["new_contacts"] == "6"
    assert dash["discovery_impl"] == "legacy"


def test_render_report_includes_recommendation():
    summary = HarvestRunSummary(jurisdictions_processed_count=10)
    from src.harvest_report import RunAnalysis

    analysis = RunAnalysis(recommendation_code="B", recommendation="Re-run harvest.")
    md = render_harvest_report_md(summary, analysis)
    assert "**B)**" in md
    assert "Recommendation" in md
