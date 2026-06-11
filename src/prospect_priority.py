"""Prospect priority for review sorting (does not control inclusion)."""

from __future__ import annotations

STALE_PLAN_CUTOFF = 2015


def compute_prospect_priority(
    plan_year: str,
    update_signal: str,
) -> tuple[str, str]:
    """
    Return (prospect_priority, prospect_priority_reason).

    Priority does not reject contacts; active-update communities stay in working CSV.
    """
    if update_signal:
        return (
            "research_only",
            f"active planning signal: {update_signal}",
        )

    if not plan_year:
        return (
            "medium",
            "no plan year found; no active update signal",
        )

    try:
        year = int(plan_year)
    except ValueError:
        return ("unknown", f"unparseable plan year: {plan_year}")

    if year <= STALE_PLAN_CUTOFF:
        return (
            "high",
            f"latest plan year {year}; no active update signal",
        )
    return (
        "low",
        f"latest plan year {year}; no active update signal",
    )
