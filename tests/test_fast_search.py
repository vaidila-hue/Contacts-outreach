"""Tests for fast planning search."""

from unittest.mock import patch

from src.search_providers import SearchHit
from src.search_web import fast_planning_search


def test_fast_planning_search_stops_after_first_productive_query():
    hits = [
        SearchHit(
            url="https://www.southburlingtonvt.gov/staff",
            title="Planning staff",
            snippet="South Burlington VT",
            provider="test",
        )
    ]

    with patch("src.search_web.search_text", return_value=(hits, "test")) as mock_search:
        urls, all_hits, queries_run = fast_planning_search(
            "South Burlington", "VT", "city", delay=0
        )

    assert queries_run == 1
    assert mock_search.call_count == 1
    assert urls
