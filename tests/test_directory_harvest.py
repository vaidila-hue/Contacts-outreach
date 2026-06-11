"""Tests for directory harvest (default discovery)."""

import pytest

from src.census_seed import Jurisdiction
from src.directory_harvest import (
    sort_jurisdictions_for_harvest,
    harvest_jurisdiction,
    _probe_urls,
)
from src.manual_urls import ManualUrlEntry


def test_sort_jurisdictions_cities_before_counties():
    jurisdictions = [
        Jurisdiction("FL", "Baker County", "county", 28000),
        Jurisdiction("FL", "Miami", "city", 450000),
        Jurisdiction("FL", "Niceville", "town", 16000),
    ]
    ordered = sort_jurisdictions_for_harvest(jurisdictions, include_counties=True)
    assert ordered[0].geography_type == "city"
    assert ordered[-1].geography_type == "county"


def test_sort_excludes_counties_by_default():
    jurisdictions = [
        Jurisdiction("FL", "Baker County", "county", 28000),
        Jurisdiction("FL", "Miami", "city", 450000),
    ]
    ordered = sort_jurisdictions_for_harvest(jurisdictions)
    assert len(ordered) == 1
    assert ordered[0].jurisdiction_name == "Miami"


def test_probe_urls_includes_planning_and_staff():
    urls = _probe_urls("https://www.example.gov")
    paths = " ".join(u for u, _ in urls).lower()
    assert "/planning" in paths
    assert "/staff" in paths or "/directory" in paths


def test_harvest_finds_contact_on_official_directory(monkeypatch):
    j = Jurisdiction(state="VT", jurisdiction_name="South Burlington", geography_type="city", population=20488)

    html = """
    <html><body>
    <h2>Planning Director</h2>
    <p>Paul Conner</p>
    <a href="mailto:pconner@southburlingtonvt.gov">Email</a>
    </body></html>
    """

    class StubFetcher:
        def fetch_html(self, url: str) -> str | None:
            if "southburlingtonvt.gov" in url:
                return html
            return None

        def begin_jurisdiction(self) -> None:
            pass

        def end_jurisdiction(self):
            from src.fetch_pages import JurisdictionFetchStats

            return JurisdictionFetchStats()

    monkeypatch.setattr(
        "src.directory_harvest._try_guess_official",
        lambda *a, **k: "https://www.southburlingtonvt.gov",
    )

    working, rejected, diag_row = harvest_jurisdiction(j, StubFetcher())
    assert working is not None
    assert working["email"] == "pconner@southburlingtonvt.gov"
    assert working["discovery_method"] == "directory_harvest"


def test_harvest_manual_official_site():
    j = Jurisdiction(state="DE", jurisdiction_name="Dover", geography_type="city", population=39491)

    class StubFetcher:
        def fetch_html(self, url: str) -> str | None:
            if "manual.example.gov" in url:
                return "<html>Planning Director Jane Doe jane.doe@manual.example.gov</html>"
            return None

        def begin_jurisdiction(self) -> None:
            pass

        def end_jurisdiction(self):
            from src.fetch_pages import JurisdictionFetchStats

            return JurisdictionFetchStats()

    overrides = [
        ManualUrlEntry("DE", "Dover", "https://manual.example.gov", "official_site"),
    ]
    working, rejected, diag_row = harvest_jurisdiction(j, StubFetcher(), overrides)
    assert working is not None
    assert "manual.example.gov" in working["email"]
