#!/usr/bin/env python3
"""
Standalone DDGS diagnostic — no jurisdiction or .gov filtering.

Compare raw DDGS output vs the application's search layer.

Usage (from Contacts project root):
    python tests/manual_ddgs_check.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QUERIES = [
    ("South Burlington VT Planning Director", "South Burlington", "VT"),
    ("Dover DE Planning Department", "Dover", "DE"),
    ("Newark DE Planning Director", "Newark", "DE"),
    ("Cranston RI Planning Directory", "Cranston", "RI"),
]

MAX_RESULTS = 10


def raw_ddgs_search(query: str, max_results: int = MAX_RESULTS) -> tuple[list[dict], str | None]:
    """Call DDGS directly; return raw result dicts and any error message."""
    try:
        from ddgs import DDGS

        results = list(DDGS().text(query, max_results=max_results))
        return results, None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def print_raw_ddgs(query: str) -> tuple[int, list[dict], str | None]:
    print("=" * 72)
    print(f"QUERY: {query}")
    print("-" * 72)
    print("RAW DDGS (no app filtering)")
    results, err = raw_ddgs_search(query, MAX_RESULTS)
    if err:
        print(f"  ERROR: {err}")
        traceback.print_exc()
    print(f"  raw result count: {len(results)}")
    if not results:
        print("  (no results)")
        return 0, [], err
    for i, r in enumerate(results[:MAX_RESULTS], 1):
        url = r.get("href") or r.get("link") or r.get("url") or ""
        title = r.get("title") or ""
        snippet = r.get("body") or r.get("snippet") or r.get("description") or ""
        print(f"  [{i}] {url}")
        print(f"       title:   {title[:120]}")
        print(f"       snippet: {snippet[:160]}")
    return len(results), results, err


def print_app_layer(query: str, jurisdiction: str, state: str) -> None:
    from src.search_providers import _ddgs_search, diagnose_search, search_text
    from src.search_web import _search_query_urls

    print("-" * 72)
    print("APP: search_providers._ddgs_search()")
    hits = _ddgs_search(query, max_results=MAX_RESULTS)
    print(f"  hit count: {len(hits)}")
    for i, h in enumerate(hits[:MAX_RESULTS], 1):
        print(f"  [{i}] {h.url}")
        print(f"       title:   {h.title[:120]}")
        print(f"       snippet: {h.snippet[:160]}")

    print("-" * 72)
    print("APP: search_text(gov_only=False)")
    hits2, provider = search_text(query, max_results=MAX_RESULTS, gov_only=False)
    print(f"  provider: {provider}")
    print(f"  hit count: {len(hits2)}")

    print("-" * 72)
    print("APP: search_text(gov_only=True)")
    hits3, _ = search_text(query, max_results=MAX_RESULTS, gov_only=True)
    print(f"  hit count after .gov/.org/.us filter: {len(hits3)}")
    dropped = len(hits2) - len(hits3)
    if dropped:
        print(f"  dropped by gov_only: {dropped}")

    print("-" * 72)
    print("APP: search_web._search_query_urls(gov_only=True)")
    urls = _search_query_urls(query, max_results=MAX_RESULTS, gov_only=True)
    print(f"  url count after gov filter: {len(urls)}")
    for u in urls[:MAX_RESULTS]:
        print(f"    - {u}")

    print("-" * 72)
    print(f"APP: diagnose_search + jurisdiction filter ({jurisdiction}, {state})")
    diag = diagnose_search(query, jurisdiction, state, max_results=MAX_RESULTS, gov_only=False)
    accepted = [fr for fr in diag.filtered if fr.accepted]
    rejected = [fr for fr in diag.filtered if not fr.accepted]
    print(f"  raw from search_text: {diag.raw_count}")
    print(f"  accepted after jurisdiction filter: {len(accepted)}")
    print(f"  rejected: {len(rejected)}")
    for fr in rejected[:5]:
        print(f"    REJECT ({fr.reason}): {fr.hit.url}")

    print("-" * 72)
    print(f"APP: diagnose_search + jurisdiction + gov_only ({jurisdiction}, {state})")
    diag2 = diagnose_search(query, jurisdiction, state, max_results=MAX_RESULTS, gov_only=True)
    accepted2 = [fr for fr in diag2.filtered if fr.accepted]
    print(f"  accepted: {len(accepted2)}")


def main() -> int:
    print("DDGS standalone diagnostic")
    print(f"Project root: {ROOT}")
    try:
        import ddgs  # noqa: F401

        print(f"ddgs package: {getattr(ddgs, '__version__', 'unknown')}")
    except ImportError:
        print("ddgs package: NOT INSTALLED")
        return 1

    summary: list[tuple[str, int, str | None]] = []

    for query, jurisdiction, state in QUERIES:
        count, _, err = print_raw_ddgs(query)
        summary.append((query, count, err))
        print_app_layer(query, jurisdiction, state)
        print()

    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    all_zero = True
    any_error = False
    for query, count, err in summary:
        status = "OK" if count > 0 else ("ERROR" if err else "ZERO")
        if count > 0:
            all_zero = False
        if err:
            any_error = True
        print(f"  [{status:5}] {count:2} raw  |  {query}")
        if err:
            print(f"         error: {err}")

    print()
    if any_error:
        print("Verdict: DDGS raised exceptions — likely broken, misconfigured, or blocked.")
    elif all_zero:
        print("Verdict: DDGS returned zero for all queries — likely rate-limited, blocked, or broken upstream.")
        print("         Compare app-layer counts above; if app also shows 0 everywhere, filtering is NOT the cause.")
    else:
        print("Verdict: DDGS returns results. Check app-layer sections for where results are dropped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
