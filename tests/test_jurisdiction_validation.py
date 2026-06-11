"""Tests for strict jurisdiction/domain validation."""

import pytest

from src.jurisdiction_utils import url_matches_jurisdiction
from src.jurisdiction_validation import (
    check_url_jurisdiction,
    gov_domain_implies_other_municipality,
    validate_jurisdiction_match,
)


@pytest.mark.parametrize(
    "url,jurisdiction,state",
    [
        ("https://www.addisontx.gov", "Addison County", "VT"),
        ("https://www.orleanscountyny.gov", "Orleans County", "VT"),
        ("https://www.windsor-va.gov", "Windsor County", "VT"),
        ("https://www.townofwindsor.ca.gov", "Windsor County", "VT"),
    ],
)
def test_vt_counties_reject_wrong_state_domains(url: str, jurisdiction: str, state: str) -> None:
    status, _ = check_url_jurisdiction(url, jurisdiction, state)
    assert status == "mismatch"
    assert not url_matches_jurisdiction(url, jurisdiction, state)


@pytest.mark.parametrize(
    "url,jurisdiction,state",
    [
        ("https://www.southburlingtonvt.gov", "South Burlington", "VT"),
        ("https://www.cranstonri.gov", "Cranston", "RI"),
    ],
)
def test_accept_correct_jurisdiction_domains(url: str, jurisdiction: str, state: str) -> None:
    status, _ = check_url_jurisdiction(url, jurisdiction, state)
    assert status == "matched"
    assert url_matches_jurisdiction(url, jurisdiction, state)


def test_validate_jurisdiction_match_mismatch_on_official_site() -> None:
    status, notes = validate_jurisdiction_match(
        "Addison County",
        "VT",
        official_url="https://www.addisontx.gov",
    )
    assert status == "mismatch"
    assert "addisontx" in notes.lower() or "TX" in notes


def test_validate_jurisdiction_match_matched_on_email_domain() -> None:
    status, _ = validate_jurisdiction_match(
        "South Burlington",
        "VT",
        email="planner@southburlingtonvt.gov",
        official_url="https://www.southburlingtonvt.gov",
    )
    assert status == "matched"


def test_gov_domain_implies_other_municipality_pawtucket_for_central_falls() -> None:
    assert gov_domain_implies_other_municipality(
        "pawtucketri.gov", "Central Falls", "RI"
    )


def test_gov_domain_not_other_municipality_for_target() -> None:
    assert not gov_domain_implies_other_municipality(
        "southburlingtonvt.gov", "South Burlington", "VT"
    )
    assert not gov_domain_implies_other_municipality("dover.de.us", "Dover", "DE")
