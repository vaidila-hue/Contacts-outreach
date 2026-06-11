"""Tests for person-first discovery and tightened working eligibility."""

import pytest

from src.extract_emails import classify_email
from src.jurisdiction_validation import check_url_jurisdiction
from src.person_extract import PersonCandidate, extract_person_from_text
from src.person_first_discovery import (
    PersonFirstResult,
    person_first_working_eligible,
    validate_person_first_contact,
)
from src.search_providers import SearchHit


def test_extract_person_from_search_snippet():
    text = "Jane Smith, Planning Director - South Burlington, VT official site"
    people = extract_person_from_text(text, "https://www.southburlingtonvt.gov/staff")
    assert len(people) >= 1
    assert any(p.name == "Jane Smith" for p in people)


def test_south_burlington_person_first_accepts_official_domain():
    person = PersonCandidate(
        name="Paul Conner",
        title="Planning Director",
        candidate_source_url="https://www.southburlingtonvt.gov/directory",
        snippet="Paul Conner, Planning Director, South Burlington, VT",
    )
    result = validate_person_first_contact(
        person,
        "pconner@southburlingtonvt.gov",
        "https://www.southburlingtonvt.gov/directory",
        "South Burlington",
        "VT",
        "https://www.southburlingtonvt.gov",
    )
    assert result is not None
    assert person_first_working_eligible(
        result, "South Burlington", "VT", "https://www.southburlingtonvt.gov"
    )


def test_dover_person_first_accepts_official_email_domain():
    person = PersonCandidate(
        name="Amber Blizinski",
        title="Community Development Director",
        candidate_source_url="https://www.cityofdover.gov/departments/",
        snippet="Amber Blizinski, Community Development Director, Dover, Delaware",
    )
    result = validate_person_first_contact(
        person,
        "pw@dover.de.us",
        "https://www.cityofdover.gov/departments/",
        "Dover",
        "DE",
        "https://www.cityofdover.gov",
    )
    assert result is not None
    assert person_first_working_eligible(
        result, "Dover", "DE", "https://www.cityofdover.gov"
    )


def test_newark_de_rejects_newark_nj_person_first():
    person = PersonCandidate(
        name="Deirdre Smith",
        title="Director of Planning",
        candidate_source_url="https://www.artesianwater.com/news",
        snippet="Artesian announces hiring of planning director for Newark",
    )
    result = validate_person_first_contact(
        person,
        "hisseinea@ci.newark.nj.us",
        "https://www.documenters.org/meetings/central-planning-board-112772/",
        "Newark",
        "DE",
        "https://www.newarkde.gov",
    )
    assert result is None or not person_first_working_eligible(
        result, "Newark", "DE", "https://www.newarkde.gov"
    )


def test_central_falls_rejects_pawtucket_person_first():
    uncertain = PersonFirstResult(
        contact_name="Central Falls",
        contact_title="Planning Director",
        email="cbennett@pawtucketri.gov",
        candidate_source_url="https://www.providencejournal.com/story/central-falls",
        email_source_url="https://pawtucketri.gov/hazard-plan/",
        jurisdiction_match_status="uncertain",
        jurisdiction_match_notes="name from news; email from pawtucketri.gov",
        source_snippet="Central Falls, Rhode Island planning update",
    )
    assert not person_first_working_eligible(
        uncertain, "Central Falls", "RI", "https://www.centralfallsri.gov/"
    )


def test_person_first_uncertain_without_strong_tie_rejected():
    uncertain = PersonFirstResult(
        contact_name="Jane Doe",
        contact_title="Planning Director",
        email="jane@gmail.com",
        candidate_source_url="https://www.linkedin.com/in/jane",
        email_source_url="https://example.com/contact",
        jurisdiction_match_status="uncertain",
    )
    assert not person_first_working_eligible(
        uncertain, "Burlington", "VT", "https://www.burlingtonvt.gov"
    )


def test_page_extraction_uncertain_may_remain_pending():
    from src.census_seed import Jurisdiction
    from src.run import _working_row_from_contact

    j = Jurisdiction(state="VT", jurisdiction_name="Bennington County", geography_type="county", population=37312)
    row = _working_row_from_contact(
        j,
        official="https://benningtonvt.org/",
        planning_url="https://benningtonvt.org/services/planning___permitting/",
        contact_name="David Conwill",
        contact_title="Planning Director",
        email="dconwill@benningtonvt.org",
        email_source_url="https://benningtonvt.org/services/planning___permitting/",
        candidate_source_url="https://benningtonvt.org/services/planning___permitting/",
        discovery_method="page_extraction",
        plan_year="",
        update_signal="",
        priority="medium",
        priority_reason="no plan year found",
        match_status="uncertain",
        match_notes="",
    )
    assert row["review_status"] == "pending"
    assert row["discovery_method"] == "page_extraction"
    assert row["jurisdiction_match_status"] == "uncertain"


def test_cranston_official_domain_matched():
    person = PersonCandidate(
        name="Jonas Bruggemann",
        title="Assistant City Planning Director",
        candidate_source_url="https://www.cranstonri.gov/planning-directory/",
    )
    result = validate_person_first_contact(
        person,
        "jbruggemann@cranstonri.org",
        "https://www.cranstonri.gov/planning-directory/",
        "Cranston",
        "RI",
        "https://www.cranstonri.gov",
    )
    assert result is not None
    assert result.jurisdiction_match_status == "matched"
    assert person_first_working_eligible(result, "Cranston", "RI", "https://www.cranstonri.gov")
