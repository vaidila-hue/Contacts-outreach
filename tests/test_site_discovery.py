"""Tests for official-site and planning-department discovery."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout

import pytest

from src.census_seed import Jurisdiction
from src.directory_harvest import harvest_jurisdiction
from src.fetch_pages import guess_official_urls
from src.harvest_config import HarvestConfig
from src.search_providers import SearchHit
from src.site_discovery import (
    DiscoveryReport,
    SiteResolutionResult,
    QueryTrace,
    UrlEvaluation,
    classify_search_rejection,
    diagnose_discovery,
    format_discovery_report,
    is_planning_department_url,
    matches_municipal_domain_pattern,
    official_site_search_queries,
    planning_department_search_queries,
    resolve_official_site,
)
from src.jurisdiction_utils import official_homepage_from_url


def test_guess_urls_prioritize_cityof_org():
    urls = guess_official_urls("Merced", "CA")
    assert urls[0] == "https://www.cityofmerced.org"
    assert "https://cityofmerced.org" in urls[:4]


def test_official_site_search_query_variants():
    queries = official_site_search_queries("Bloomington", "MN", "city")
    assert len(queries) >= 6
    assert any("official website" in q for q in queries)
    assert any("planning department" in q for q in queries)
    assert any("community development" in q for q in queries)


def test_county_search_query_variants():
    queries = official_site_search_queries("Santa Barbara County", "CA", "county")
    assert any("county planning department" in q for q in queries)


def test_planning_department_queries_subset():
    planning = planning_department_search_queries("Merced", "CA", "city")
    official = official_site_search_queries("Merced", "CA", "city")
    assert planning[0] in official


def test_municipal_domain_patterns():
    assert matches_municipal_domain_pattern("https://www.cityofmerced.org/", "Merced", "CA")
    assert matches_municipal_domain_pattern("https://www.bloomingtonmn.gov/", "Bloomington", "MN")
    assert matches_municipal_domain_pattern("https://sanleandro.org/", "San Leandro", "CA")


def test_planning_url_detection():
    url = "https://www.cityofmerced.org/departments/development-services/planning-division"
    assert is_planning_department_url(url)


def test_rejection_reasons_recorded():
    hit = SearchHit(
        url="https://www.facebook.com/cityofmerced",
        title="Merced CA",
        snippet="Follow us",
        provider="test",
    )
    accepted, reason = classify_search_rejection(hit, "Merced", "CA", "city")
    assert not accepted
    assert reason == "social_media"

    school = SearchHit(
        url="https://www.merced.k12.ca.us/planning",
        title="School district",
        snippet="",
        provider="test",
    )
    accepted, reason = classify_search_rejection(school, "Merced", "CA", "city")
    assert not accepted
    assert reason == "school_domain"


def test_planning_page_accepted_in_planning_context():
    hit = SearchHit(
        url="https://www.cityofmerced.org/departments/development-services/planning-division",
        title="Planning Division | City of Merced",
        snippet="Community development and planning",
        provider="test",
    )
    accepted, reason = classify_search_rejection(hit, "Merced", "CA", "city", planning_context=True)
    assert accepted
    assert reason == "accepted"


def test_planning_page_establishes_official_domain():
    planning = "https://www.cityofmerced.org/departments/development-services/planning-division"
    home = official_homepage_from_url(planning)
    assert home == "https://www.cityofmerced.org/"


def test_resolve_uses_planning_fallback_after_official_failure(monkeypatch):
    j = Jurisdiction("CA", "Merced", "city", 90000)
    planning_html = "<html><body><h1>Planning Division</h1><p>Staff directory</p></body></html>" * 30
    home_html = "<html><body><h1>City of Merced</h1></body></html>" * 50

    class StubFetcher:
        def fetch_html(self, url: str) -> str | None:
            if "planning-division" in url:
                return planning_html
            if "cityofmerced.org" in url:
                return home_html
            return None

    official_queries = official_site_search_queries(j.jurisdiction_name, j.state, j.geography_type)
    planning_queries = planning_department_search_queries(j.jurisdiction_name, j.state, j.geography_type)
    seen_official: set[str] = set()

    def fake_search(query, max_results=5, delay=0, gov_only=False):
        if query in official_queries:
            if query not in seen_official:
                seen_official.add(query)
                return [], "test"
        if query in planning_queries:
            return [
                SearchHit(
                    url="https://www.cityofmerced.org/departments/development-services/planning-division",
                    title="Planning Division | City of Merced",
                    snippet="Planning staff",
                    provider="test",
                )
            ], "test"
        return [], "test"

    monkeypatch.setattr("src.site_discovery.search_text", fake_search)
    monkeypatch.setattr("src.site_discovery._try_guess_official", lambda *a, **k: None)

    result = resolve_official_site(j, StubFetcher(), HarvestConfig(max_search_queries_per_jurisdiction=12))
    assert result.resolver_method == "planning_search_fallback"
    assert result.planning_fallback_url
    assert "cityofmerced.org" in result.official_url


def test_harvest_not_no_official_when_planning_fallback(monkeypatch):
    j = Jurisdiction("MN", "Bloomington", "city", 90000)
    html = "<html><body><h2>Planning Director</h2><a href='mailto:planning@bloomingtonmn.gov'>Email</a></body></html>" * 20

    class StubFetcher:
        def fetch_html(self, url: str) -> str | None:
            if "bloomingtonmn.gov" in url or "planning" in url:
                return html
            return None

        def begin_jurisdiction(self) -> None:
            pass

        def end_jurisdiction(self):
            from src.fetch_pages import JurisdictionFetchStats

            return JurisdictionFetchStats()

    def fake_resolve(*args, **kwargs):
        return (
            "https://www.bloomingtonmn.gov/",
            ["https://www.bloomingtonmn.gov/departments/planning"],
        )

    monkeypatch.setattr("src.directory_harvest._resolve_official_site", fake_resolve)
    working, rejected, diag = harvest_jurisdiction(j, StubFetcher())
    assert rejected is None or rejected.get("rejection_reason") != "no_official_site_found"
    assert int(diag["pages_fetched"]) > 0
    assert "bloomingtonmn.gov" in diag["official_domain"]


def test_diagnose_discovery_prints_search_reasoning(monkeypatch):
    j_name, st = "Merced", "CA"

    def fake_diagnose(*args, **kwargs):
        resolution = SiteResolutionResult(
            official_url="https://www.cityofmerced.org/",
            planning_fallback_url="https://www.cityofmerced.org/departments/development-services/planning-division",
            resolver_method="planning_search_fallback",
            search_queries_run=2,
            search_results_seen=3,
            search_results_rejected=1,
        )
        resolution.query_traces.append(
            QueryTrace(
                query=f'"{j_name}" "{st}" planning department',
                provider="test",
                raw_count=1,
                evaluations=[
                    UrlEvaluation(
                        url="https://www.cityofmerced.org/departments/development-services/planning-division",
                        title="Planning",
                        snippet="",
                        query=f'"{j_name}" "{st}" planning department',
                        accepted=True,
                        reason="accepted",
                    )
                ],
            )
        )
        return DiscoveryReport(
            jurisdiction_name=j_name,
            state=st,
            geography_type="city",
            resolution=resolution,
            official_domain="www.cityofmerced.org",
            planning_pages_found=1,
            pages_fetched=2,
            final_outcome="planning_search_fallback",
        )

    monkeypatch.setattr("src.site_discovery.diagnose_discovery", fake_diagnose)
    from src.run import run_diagnose_discovery
    import argparse

    args = argparse.Namespace(jurisdiction=j_name, state=st, geography_type="city")
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = run_diagnose_discovery(args)
    out = buf.getvalue()
    assert code == 0
    assert "planning department" in out.lower()
    assert "ACCEPT" in out
    assert "cityofmerced.org" in out


def test_format_discovery_report_includes_resolver():
    report = DiscoveryReport(
        jurisdiction_name="Merced",
        state="CA",
        geography_type="city",
        resolution=SiteResolutionResult(resolver_method="planning_search_fallback"),
        final_outcome="planning_search_fallback",
    )
    text = format_discovery_report(report)
    assert "planning_search_fallback" in text
