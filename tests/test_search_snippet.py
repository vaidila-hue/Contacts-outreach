"""Tests for search-snippet working eligibility gate."""

from src.census_seed import Jurisdiction
from src.jurisdiction_validation import search_snippet_working_eligible
from src.run import _finalize_discover, DiscoverDiagnostics
from src.build_mode import BuildMode
from src.extract_contacts import ContactCandidate


def test_reject_search_snippet_uvmhealth():
    ok, note = search_snippet_working_eligible(
        "pat.mckittrick@uvmhealth.org",
        "https://www.uvmhealth.org/staff.pdf",
        "Franklin County",
        "VT",
        "",
    )
    assert not ok
    assert note


def test_reject_search_snippet_sba_gov():
    ok, note = search_snippet_working_eligible(
        "darcy.carter@sba.gov",
        "https://www.vtrural.org/sites/default/files/ParticipantList2.pdf",
        "Windsor County",
        "VT",
        "",
    )
    assert not ok
    assert "non-official" in note.lower() or "third-party" in note.lower() or "federal" in note.lower()


def test_accept_search_snippet_benningtonvt_org():
    ok, _ = search_snippet_working_eligible(
        "dconwill@benningtonvt.org",
        "https://benningtonvt.org/services/planning___permitting/",
        "Bennington County",
        "VT",
        "https://benningtonvt.org/",
    )
    assert ok


def test_accept_search_snippet_southburlingtonvt_gov():
    ok, _ = search_snippet_working_eligible(
        "pconner@southburlingtonvt.gov",
        "https://www.southburlingtonvt.gov/Directory.aspx?did=8",
        "South Burlington",
        "VT",
        "https://www.southburlingtonvt.gov",
    )
    assert ok


def test_page_extraction_not_blocked_by_snippet_gate():
    j = Jurisdiction(
        state="VT",
        jurisdiction_name="Bennington County",
        geography_type="county",
        population=37312,
    )
    candidate = ContactCandidate(
        name="David Conwill",
        title="Planning Director",
        email="dconwill@benningtonvt.org",
        source_url="https://benningtonvt.org/services/planning/",
        paired_with_name=True,
    )
    working, rejected, _ = _finalize_discover(
        j,
        official="https://benningtonvt.org/",
        planning_url="https://benningtonvt.org/services/planning/",
        diag=DiscoverDiagnostics(),
        all_candidates=[candidate],
        combined_text="",
        source_urls=[candidate.source_url],
        manual_direct=[],
        manual_pdfs=[],
        mode=BuildMode(),
        search_hit_urls=set(),
        fetched_page_urls={candidate.source_url},
    )
    assert working is not None
    assert rejected is None
    assert working["discovery_method"] == "page_extraction"
