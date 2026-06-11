"""Tests for URL normalization and performance helpers."""

from src.directory_harvest import _high_confidence_found
from src.extract_contacts import ContactCandidate, is_high_confidence_contact, page_warrants_extraction
from src.url_utils import normalize_url


def test_normalize_url_strips_fragment_and_tracking():
    url = normalize_url("https://WWW.Example.GOV/planning/?utm_source=x#staff")
    assert url == "https://www.example.gov/planning"


def test_normalize_url_trailing_slash():
    assert normalize_url("https://city.gov/planning/") == "https://city.gov/planning"


def test_page_warrants_extraction_skips_irrelevant():
    html = "<html><body><h1>Parks and Recreation</h1><p>Join our team.</p></body></html>"
    assert not page_warrants_extraction(html, "https://city.gov/parks", page_kind="other")


def test_page_warrants_extraction_allows_planning_probe():
    html = "<html><body><h1>Parks</h1></body></html>"
    assert page_warrants_extraction(html, "https://city.gov/planning", page_kind="planning")


def test_high_confidence_contact():
    c = ContactCandidate(
        "Jane Doe",
        "Planning Director",
        "jane.doe@city.gov",
        "https://www.city.gov/planning",
        True,
    )
    assert is_high_confidence_contact(c, "https://www.city.gov")


def test_high_confidence_found_in_list():
    candidates = [
        ContactCandidate(
            "Jane Doe",
            "Planning Director",
            "jane.doe@city.gov",
            "https://www.city.gov/planning",
            True,
        )
    ]
    assert _high_confidence_found(candidates, "https://www.city.gov") is not None
