"""Tests for harvest report analysis."""

from src.harvest_summary import HarvestRunSummary
from src.harvest_report import (
    _fmt_ts_et,
    analyze_harvest_run,
    discovery_implementation_label,
    format_harvest_dashboard,
    harvest_dashboard_stale_note,
    render_harvest_report_md,
)
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def test_discovery_implementation_label_is_site_discovery():
    assert discovery_implementation_label() == "site_discovery_v1"


def test_harvest_dashboard_stale_note_when_diagnostics_newer(tmp_path, monkeypatch):
    import src.harvest_report as hr
    import src.paths as paths

    diagnostics = tmp_path / "harvest_diagnostics.csv"
    monkeypatch.setattr(paths, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(hr, "DIAGNOSTICS_CSV", diagnostics)

    from src.csv_utils import write_csv
    from src.paths import DIAGNOSTICS_COLUMNS

    write_csv(
        diagnostics,
        [{"final_rejection_reason": "no_official_site_found"} for _ in range(73)],
        DIAGNOSTICS_COLUMNS,
    )

    summary = HarvestRunSummary(
        run_completed_at="2026-06-11T23:17:42+00:00",
        jurisdictions_processed_count=60,
        candidates_added_count=2,
        diagnostics_row_count=60,
        run_source="cli_build",
    )
    note = harvest_dashboard_stale_note(summary)
    assert "older run" in note
    assert "73" in note

    dash = format_harvest_dashboard(summary, stale_note=note)
    assert dash["stale_note"] == note


def test_analyze_last_run_rejection_breakdown():
    summary = HarvestRunSummary(
        jurisdictions_processed_count=60,
        processed_jurisdictions=[
            {"state": "CA", "jurisdiction_name": "Merced", "geography_type": "city", "population": "89000"},
            {"state": "MN", "jurisdiction_name": "Bloomington", "geography_type": "city", "population": "88000"},
        ],
        candidates_found_count=5,
        candidates_added_count=6,
    )
    rejected = [
        {
            "state": "CA",
            "jurisdiction_name": "Merced",
            "rejection_reason": "no_official_site_found",
            "notes": "Could not resolve official website (guess + one search)",
        },
        {
            "state": "MN",
            "jurisdiction_name": "Bloomington",
            "rejection_reason": "no_official_site_found",
            "notes": "Could not resolve official website (guess + one search)",
        },
    ]
    analysis = analyze_harvest_run(summary, diagnostics_rows=[], rejected_rows=rejected, working_rows=[])
    assert analysis.rejection_breakdown["no_official_site_found"] == 2
    assert analysis.recommendation_code == "B"
    assert analysis.discovery_implementation.startswith("legacy")


def test_format_harvest_dashboard():
    summary = HarvestRunSummary(
        run_completed_at="2026-06-11T23:17:42+00:00",
        jurisdictions_processed_count=60,
        jurisdictions_skipped_existing_count=25,
        candidates_added_count=6,
        duplicates_skipped_count=38,
        no_official_site_count=35,
        no_planning_contact_count=7,
        discovery_implementation="legacy",
    )
    dash = format_harvest_dashboard(summary)
    assert dash["jurisdictions_processed"] == "60"
    assert dash["new_contacts"] == "6"
    assert dash["last_run"] == "06/11/26 7:17 PM ET"


def test_fmt_ts_et_fallback_when_zoneinfo_missing(monkeypatch):
    import src.harvest_report as hr

    real_zoneinfo = ZoneInfo

    def fake_zoneinfo(key):
        if key == "America/New_York":
            raise ZoneInfoNotFoundError("No time zone found with key America/New_York")
        return real_zoneinfo(key)

    monkeypatch.setattr(hr, "ZoneInfo", fake_zoneinfo)
    assert _fmt_ts_et("2026-06-11T23:17:42+00:00") == "06/11/26 6:17 PM ET"


def test_crm_index_loads_when_zoneinfo_missing(tmp_path, monkeypatch):
    import json
    import src.harvest_report as hr
    import src.harvest_summary as hs
    import src.paths as paths
    from src.outreach_ui import create_app

    summary_path = tmp_path / "last_harvest_summary.json"
    monkeypatch.setattr(paths, "LAST_HARVEST_SUMMARY_JSON", summary_path)
    monkeypatch.setattr(hs, "LAST_HARVEST_SUMMARY_JSON", summary_path)

    summary = HarvestRunSummary(
        run_completed_at="2026-06-11T23:17:42+00:00",
        jurisdictions_processed_count=10,
        candidates_added_count=2,
    )
    summary_path.write_text(json.dumps(summary.__dict__, indent=2), encoding="utf-8")

    def fake_zoneinfo(key):
        if key == "America/New_York":
            raise ZoneInfoNotFoundError("No time zone found with key America/New_York")
        return ZoneInfo(key)

    monkeypatch.setattr(hr, "ZoneInfo", fake_zoneinfo)
    monkeypatch.setattr("src.harvest_status.is_harvest_running", lambda: False)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Planzookie Outreach CRM" in html
        assert "6:17 PM ET" in html


def test_render_report_includes_recommendation():
    summary = HarvestRunSummary(jurisdictions_processed_count=10)
    from src.harvest_report import RunAnalysis

    analysis = RunAnalysis(recommendation_code="B", recommendation="Re-run harvest.")
    md = render_harvest_report_md(summary, analysis)
    assert "**B)**" in md
    assert "Recommendation" in md
