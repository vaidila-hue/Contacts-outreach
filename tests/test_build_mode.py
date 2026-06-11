"""Tests for build mode and fast search queries."""

import argparse

from src.build_mode import BuildMode, resolve_delay
from src.role_config import (
    MAX_FAST_SEARCH_QUERIES,
    fast_county_queries,
    fast_municipality_queries,
)


def test_fast_municipality_queries():
    queries = fast_municipality_queries("South Burlington", "VT")
    assert len(queries) == 3
    combined = " ".join(queries).lower()
    assert "planning director" in combined
    assert "community development director" in combined
    assert "planning staff" in combined
    assert "email" in combined
    assert '"south burlington"' in combined
    assert '"vt"' in combined


def test_fast_county_queries():
    queries = fast_county_queries("Kent County", "DE")
    assert len(queries) == 3
    combined = " ".join(queries).lower()
    assert "county planner" in combined
    assert '"de"' in combined


def test_build_mode_default_is_fast():
    mode = BuildMode.from_args(argparse.Namespace())
    assert not mode.deep
    assert not mode.include_pdfs
    assert not mode.include_plan_signals
    assert not mode.person_first


def test_build_mode_deep_enables_all():
    mode = BuildMode.from_args(argparse.Namespace(deep=True))
    assert mode.deep
    assert mode.include_pdfs
    assert mode.include_plan_signals
    assert mode.person_first


def test_build_mode_individual_flags():
    mode = BuildMode.from_args(
        argparse.Namespace(
            deep=False,
            include_pdfs=True,
            include_plan_signals=False,
            person_first=True,
        )
    )
    assert mode.include_pdfs
    assert not mode.include_plan_signals
    assert mode.person_first


def test_resolve_delay_defaults():
    assert resolve_delay(argparse.Namespace(delay=None, deep=False)) == 0.5
    assert resolve_delay(argparse.Namespace(delay=None, deep=True)) == 3.0
    assert resolve_delay(argparse.Namespace(delay=2.0, deep=False)) == 2.0


def test_max_fast_search_queries_matches_query_count():
    assert MAX_FAST_SEARCH_QUERIES == 3
    assert len(fast_municipality_queries("X", "Y")) == MAX_FAST_SEARCH_QUERIES
