"""Tests for official-site URL generation and validation."""

import pytest

from src.fetch_pages import guess_official_urls
from src.jurisdiction_utils import (
    is_blocked_official_url,
    normalize_jurisdiction_name,
    url_matches_jurisdiction,
)


def test_east_providence_candidate_generation():
    urls = guess_official_urls("East Providence", "RI")
    combined = " ".join(urls).lower()
    assert "eastprovidenceri.gov" in combined
    assert "cityofeastprovidence" in combined or "east-providence" in combined
    assert any("eastprovidence" in u and ".gov" in u for u in urls)


def test_central_falls_candidate_generation():
    urls = guess_official_urls("Central Falls", "RI")
    combined = " ".join(urls).lower()
    assert "centralfallsri.gov" in combined
    assert "centralfallsri.us" in combined or "centralfallsri.com" in combined


def test_reject_ri_gov_hub_pages():
    assert is_blocked_official_url("https://www.ri.gov/towns/view/bristol/")
    assert is_blocked_official_url("https://www.ri.gov/links/?tags=cities+and+towns")


def test_reject_dot_ri_gov():
    assert is_blocked_official_url("https://www.dot.ri.gov/projects/projects_newport.php")


def test_east_providence_url_matches_jurisdiction():
    assert url_matches_jurisdiction(
        "https://eastprovidenceri.gov/departments/planning-economic-development",
        "East Providence",
        "RI",
    )


def test_reject_wrong_state_domain_for_ri():
    assert not url_matches_jurisdiction(
        "https://www.bristolva.gov/127/Community-Development-and-Planning",
        "Bristol County",
        "RI",
    )
