"""Tests for role-family configuration."""

from src.role_config import (
    TITLE_ALLOWLIST,
    county_queries,
    municipality_queries,
    title_rank,
)


def test_municipality_queries_include_department_not_only_director():
    queries = municipality_queries("Springfield", "MA")
    combined = " ".join(queries).lower()
    assert "planning department" in combined
    assert "planning staff" in combined
    assert "community development" in combined


def test_county_queries_include_county_planner():
    queries = county_queries("Fairfield County")
    combined = " ".join(queries).lower()
    assert "county planner" in combined
    assert "county planning department" in combined


def test_allowlist_has_twenty_two_titles():
    assert len(TITLE_ALLOWLIST) == 22


def test_director_rank_better_than_planner():
    assert title_rank("Planning Director") < title_rank("County Planner")
