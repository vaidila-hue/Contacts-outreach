"""Tests for prospect priority scoring."""

from src.prospect_priority import compute_prospect_priority


def test_high_priority_stale_plan_no_update() -> None:
    priority, reason = compute_prospect_priority("2012", "")
    assert priority == "high"
    assert "2012" in reason


def test_medium_priority_missing_plan_year() -> None:
    priority, reason = compute_prospect_priority("", "")
    assert priority == "medium"
    assert "no plan year" in reason


def test_low_priority_recent_plan() -> None:
    priority, reason = compute_prospect_priority("2020", "")
    assert priority == "low"
    assert "2020" in reason


def test_research_only_active_update_not_rejected() -> None:
    priority, reason = compute_prospect_priority("2024", "plan update (2026)")
    assert priority == "research_only"
    assert "active planning signal" in reason


def test_unknown_invalid_year() -> None:
    priority, _ = compute_prospect_priority("not-a-year", "")
    assert priority == "unknown"
