"""Tests for manual URL overrides."""

from pathlib import Path

import pytest

from src.census_seed import Jurisdiction
from src.csv_utils import write_csv
from src.manual_urls import (
    MANUAL_URL_COLUMNS,
    load_manual_urls,
    manual_urls_for_jurisdiction,
)
from src.build_mode import BuildMode
from src.run import _collect_pages, _discover_jurisdiction


@pytest.fixture
def manual_csv(tmp_path, monkeypatch):
    import src.manual_urls as manual_mod

    path = tmp_path / "manual_urls.csv"
    monkeypatch.setattr(manual_mod, "MANUAL_URLS_CSV", path)
    return path


def test_load_manual_urls_skips_invalid_rows(manual_csv):
    write_csv(
        manual_csv,
        [
            {
                "state": "DE",
                "jurisdiction_name": "Dover",
                "url": "https://www.cityofdover.gov",
                "url_type": "official_site",
                "notes": "",
            },
            {
                "state": "DE",
                "jurisdiction_name": "Dover",
                "url": "https://example.com/staff",
                "url_type": "bad_type",
                "notes": "",
            },
        ],
        MANUAL_URL_COLUMNS,
    )
    entries = load_manual_urls(manual_csv)
    assert len(entries) == 1
    assert entries[0].url_type == "official_site"


def test_manual_urls_for_jurisdiction_matches_normalized_name(manual_csv):
    write_csv(
        manual_csv,
        [
            {
                "state": "DE",
                "jurisdiction_name": "Dover city",
                "url": "https://www.cityofdover.gov/planning",
                "url_type": "planning_page",
                "notes": "",
            },
        ],
        MANUAL_URL_COLUMNS,
    )
    entries = load_manual_urls(manual_csv)
    matched = manual_urls_for_jurisdiction(entries, "DE", "Dover")
    assert len(matched) == 1
    assert matched[0].url.endswith("/planning")


def test_collect_pages_prioritizes_manual_direct_urls():
    class StubFetcher:
        def probe_domain(self, official_url: str) -> list[str]:
            return [f"{official_url}/directory"]

    pages = _collect_pages(
        StubFetcher(),
        "https://town.gov",
        ["https://town.gov/search-page"],
        manual_direct_urls=["https://town.gov/manual-staff"],
    )
    assert pages[0] == "https://town.gov/manual-staff"


def test_discover_uses_manual_official_site_before_search(monkeypatch):
    j = Jurisdiction(
        state="DE",
        jurisdiction_name="Dover",
        geography_type="city",
        population=39491,
    )

    class StubFetcher:
        def fetch_html(self, url: str) -> str | None:
            if url == "https://manual.example.gov":
                return "<html>Planning Director Jane Doe jane.doe@manual.example.gov</html>"
            return None

        def fetch_pdf(self, url: str) -> bytes | None:
            return None

        def probe_domain(self, official_url: str) -> list[str]:
            return []

    discover_called = {"value": False}

    def fake_discover(*args, **kwargs):
        discover_called["value"] = True
        return "https://wrong.example.gov"

    monkeypatch.setattr("src.run.discover_official_site", fake_discover)

    from src.manual_urls import ManualUrlEntry

    overrides = [
        ManualUrlEntry("DE", "Dover", "https://manual.example.gov", "official_site"),
    ]
    working, rejected, _, _ = _discover_jurisdiction(
        j, StubFetcher(), 0, overrides, mode=BuildMode(deep=True)
    )
    assert not discover_called["value"]
    assert working is not None
    assert "manual.example.gov" in working["official_website_url"]
