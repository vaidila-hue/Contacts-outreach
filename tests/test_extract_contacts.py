"""Tests for contact extraction and rank selection."""

from pathlib import Path

import pytest

from src.extract_contacts import (
    extract_contacts_from_html,
    select_best_contact,
)
from src.role_config import matches_allowlisted_title, title_rank

FIXTURES = Path(__file__).parent / "fixtures"


def test_title_allowlist_community_development():
    assert matches_allowlisted_title("Community Development Director") == "Community Development Director"


def test_title_allowlist_county_planner():
    assert matches_allowlisted_title("County Planner") == "County Planner"


def test_director_outranks_manager():
    assert title_rank("Planning Director") < title_rank("Planning Manager")


def test_extract_planning_director_from_html():
    html = (FIXTURES / "sample_staff.html").read_text(encoding="utf-8")
    candidates = extract_contacts_from_html(html, "https://example.gov/staff")
    best = select_best_contact(candidates)
    assert best is not None
    assert best.name == "Robert Chen"
    assert "Director" in best.title
    assert best.email == "robert.chen@examplecity.gov"


def test_extract_community_development_director():
    html = (FIXTURES / "sample_comm_dev_director.html").read_text(encoding="utf-8")
    candidates = extract_contacts_from_html(html, "https://sampletown.gov/cd")
    best = select_best_contact(candidates)
    assert best is not None
    assert best.name == "Maria Santos"
    assert best.title == "Community Development Director"
    assert best.email == "maria.santos@sampletown.gov"
