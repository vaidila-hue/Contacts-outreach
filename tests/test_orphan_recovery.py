"""Tests for conservative orphan email recovery."""

from pathlib import Path

from src.census_seed import Jurisdiction
from src.directory_harvest import harvest_jurisdiction
from src.extract_contacts import (
    extract_contacts_from_html,
    recover_orphan_email_candidates,
    select_best_contact,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_georgetown_orphan_fixture_recovers_direct_email():
    html = (FIXTURES / "sample_georgetown_orphan.html").read_text(encoding="utf-8")
    url = "https://georgetowntexas.gov/development_services/planning/index.php"
    official = "https://georgetowntexas.gov"
    normal = extract_contacts_from_html(html, url, official_url=official)
    assert select_best_contact(normal) is None

    orphan_cands, found, promoted, pairing_failures = recover_orphan_email_candidates(
        [(url, html, "planning")],
        official,
        normal,
    )
    assert found >= 1
    assert promoted >= 1
    assert pairing_failures >= 1
    best = select_best_contact(normal + orphan_cands)
    assert best is not None
    assert best.email == "david.munk@georgetowntexas.gov"
    assert best.orphan_recovered is True
    assert "Director" in best.title or "Planning" in best.title


def test_newport_orphan_fixture_recovers_staff_email():
    html = (FIXTURES / "sample_newport_orphan.html").read_text(encoding="utf-8")
    url = "https://www.newportbeachca.gov/government/departments/community-development/planning-division"
    official = "https://www.newportbeachca.gov"
    normal = extract_contacts_from_html(html, url, official_url=official)
    assert select_best_contact(normal) is None

    orphan_cands, found, promoted, _ = recover_orphan_email_candidates(
        [(url, html, "planning")],
        official,
        normal,
    )
    assert found >= 2
    assert promoted >= 1
    emails = {c.email for c in orphan_cands}
    assert "cwilson@newportbeachca.gov" in emails
    assert "planning@newportbeachca.gov" not in emails


def test_orphan_recovery_skips_non_official_domain():
    html = """
    <html><body>
    <p>Planning Director</p>
    <p>Jane Doe jane.doe@othercity.gov</p>
    </body></html>
    """
    orphan_cands, found, promoted, _ = recover_orphan_email_candidates(
        [("https://example.gov/planning", html, "planning")],
        "https://example.gov",
        [],
    )
    assert found == 0
    assert promoted == 0
    assert orphan_cands == []


def test_harvest_marks_orphan_contact_uncertain(monkeypatch):
    j = Jurisdiction(state="TX", jurisdiction_name="Georgetown", geography_type="city", population=78803)
    html = (FIXTURES / "sample_georgetown_orphan.html").read_text(encoding="utf-8")
    planning_url = "https://georgetowntexas.gov/development_services/planning/index.php"

    class StubFetcher:
        def fetch_html(self, url: str, **kwargs) -> str | None:
            if url == planning_url:
                return html
            if "georgetowntexas.gov" in url:
                return "<html><body>Planning</body></html>"
            return None

        def begin_jurisdiction(self) -> None:
            pass

        def end_jurisdiction(self):
            from src.fetch_pages import JurisdictionFetchStats

            return JurisdictionFetchStats()

    monkeypatch.setattr(
        "src.directory_harvest._resolve_official_site",
        lambda *a, **k: ("https://georgetowntexas.gov", [planning_url]),
    )

    working, rejected, diag_row = harvest_jurisdiction(j, StubFetcher())
    assert working is not None
    assert working["email"] == "david.munk@georgetowntexas.gov"
    assert working["jurisdiction_match_status"] == "uncertain"
    assert "orphan" in working["jurisdiction_match_notes"].lower()
    assert int(diag_row["orphan_emails_promoted"]) >= 1
