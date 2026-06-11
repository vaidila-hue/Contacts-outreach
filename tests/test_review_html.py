"""Tests for review HTML generation."""

from src.review_html import write_review_html


def test_write_review_html_excludes_mismatch(tmp_path) -> None:
    path = tmp_path / "review.html"
    rows = [
        {
            "state": "VT",
            "jurisdiction_name": "Addison County",
            "geography_type": "county",
            "population": "37497",
            "county_name": "",
            "official_website_url": "",
            "planning_department_url": "",
            "contact_name": "Bad",
            "contact_title": "",
            "email": "x@addisontx.gov",
            "email_source_url": "",
            "latest_plan_year_found": "",
            "active_update_signal": "",
            "prospect_priority": "high",
            "prospect_priority_reason": "",
            "jurisdiction_match_status": "mismatch",
            "jurisdiction_match_notes": "wrong",
            "review_status": "pending",
            "outreach_status": "not_started",
            "_status": "done",
        },
        {
            "state": "RI",
            "jurisdiction_name": "Cranston",
            "geography_type": "city",
            "population": "82632",
            "county_name": "",
            "official_website_url": "https://www.cranstonri.gov",
            "planning_department_url": "",
            "contact_name": "Jonas Bruggemann",
            "contact_title": "Assistant City Planning Director",
            "email": "jbruggemann@cranstonri.org",
            "email_source_url": "https://www.cranstonri.gov/planning",
            "candidate_source_url": "https://www.cranstonri.gov/planning",
            "discovery_method": "page_extraction",
            "latest_plan_year_found": "2019",
            "active_update_signal": "",
            "prospect_priority": "low",
            "prospect_priority_reason": "latest plan year 2019",
            "jurisdiction_match_status": "matched",
            "jurisdiction_match_notes": "",
            "review_status": "pending",
            "outreach_status": "not_started",
            "_status": "done",
        },
    ]
    write_review_html(rows, path)
    html = path.read_text(encoding="utf-8")
    assert "Open this file after each build" in html
    assert "Cranston" in html
    assert "Addison County" not in html
