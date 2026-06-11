"""Tests for Newport-style staff directory extraction."""

from pathlib import Path

from src.extract_contacts import extract_contacts_from_html, select_best_contact

FIXTURES = Path(__file__).parent / "fixtures"


def test_newport_staff_directory_extracts_planning_director():
    html = (FIXTURES / "sample_newport_staff.html").read_text(encoding="utf-8")
    url = "https://www.newportri.gov/city-hall/departments/planning"
    candidates = extract_contacts_from_html(html, url)
    best = select_best_contact(candidates)
    assert best is not None
    assert best.email == "preynolds@cityofnewport.com"
    assert "Director" in best.title
    assert "Patricia" in best.name


def test_newport_staff_directory_extracts_city_planner():
    html = (FIXTURES / "sample_newport_staff.html").read_text(encoding="utf-8")
    candidates = extract_contacts_from_html(html, "https://example.gov/planning")
    emails = {c.email for c in candidates}
    assert "rtrefethen@cityofnewport.com" in emails


def test_newport_does_not_cross_pair_blocks():
    html = (FIXTURES / "sample_newport_staff.html").read_text(encoding="utf-8")
    candidates = extract_contacts_from_html(html, "https://example.gov/planning")
    for c in candidates:
        if c.email == "narmour@cityofnewport.com":
            assert "Zoning" in c.title or "Officer" in c.title
            assert "Nicholas" in c.name
