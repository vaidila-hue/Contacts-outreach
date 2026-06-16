"""Tests for manual contact creation in the Outreach CRM."""

from __future__ import annotations

import pytest

from src.outreach_crm import is_ready
from src.outreach_store import add_manual_contact, prepare_outreach, read_outreach_rows, write_outreach_rows
from src.outreach_ui import create_app
from src.paths import CONTACT_SOURCE_HARVESTED, OUTREACH_COLUMNS, WORKING_COLUMNS
from src.csv_utils import write_csv


@pytest.fixture
def crm_paths(tmp_path, monkeypatch):
    import src.paths as paths
    import src.outreach_store as store
    import src.outreach_template as ot

    working = tmp_path / "prospects_working.csv"
    outreach = tmp_path / "outreach.csv"
    diagnostics = tmp_path / "harvest_diagnostics.csv"
    default_msg = tmp_path / "default_message.json"

    monkeypatch.setattr(paths, "WORKING_CSV", working)
    monkeypatch.setattr(paths, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(paths, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(paths, "DEFAULT_MESSAGE_JSON", default_msg)
    monkeypatch.setattr(store, "WORKING_CSV", working)
    monkeypatch.setattr(store, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(store, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(ot, "DEFAULT_MESSAGE_JSON", default_msg)
    return working, outreach


def _working_row(**overrides):
    row = {
        "state": "FL",
        "jurisdiction_name": "Fort Myers",
        "geography_type": "city",
        "population": "91730",
        "county_name": "",
        "official_website_url": "https://www.fortmyers.gov",
        "planning_department_url": "https://www.fortmyers.gov/planning",
        "contact_name": "Nicole DeVaughn",
        "contact_title": "Planning Manager",
        "email": "ndevaughn@fortmyers.gov",
        "email_source_url": "https://www.fortmyers.gov/planning",
        "candidate_source_url": "https://www.fortmyers.gov/planning",
        "discovery_method": "directory_harvest",
        "latest_plan_year_found": "",
        "active_update_signal": "",
        "prospect_priority": "",
        "prospect_priority_reason": "",
        "jurisdiction_match_status": "matched",
        "jurisdiction_match_notes": "",
        "notes": "",
        "review_status": "pending",
        "outreach_status": "not_started",
        "_status": "done",
    }
    row.update(overrides)
    return row


def _main_toolbar_html(html: str) -> str:
    start = html.find('<div class="actions">')
    end = html.find("</div>", start)
    return html[start:end]


def test_add_contact_button_renders(crm_paths):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        html = client.get("/").data.decode("utf-8")
    toolbar = _main_toolbar_html(html)
    assert "Add Contact" in toolbar
    assert 'id="add-contact-modal"' in html


def test_add_contact_modal_renders_fields(crm_paths):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        html = client.get("/").data.decode("utf-8")
    assert 'name="jurisdiction_name"' in html
    assert 'name="state"' in html
    assert 'name="contact_name"' in html
    assert 'name="contact_title"' in html
    assert 'name="email"' in html
    assert 'name="contact_source"' in html
    assert 'name="outreach_notes"' in html
    assert ">Manual</option>" in html
    assert ">Referral</option>" in html
    assert ">Conference</option>" in html
    assert ">LinkedIn</option>" in html
    assert ">Other</option>" in html
    assert 'action="/contacts/add"' in html


def test_saving_manual_contact_creates_row(crm_paths):
    ok, msg = add_manual_contact(
        jurisdiction_name="Sarasota",
        state="FL",
        contact_name="Pat Lee",
        contact_title="Planning Director",
        email="pat.lee@sarasota.gov",
        outreach_notes="Met at conference booth",
    )
    assert ok is True
    assert "Sarasota" in msg
    rows = read_outreach_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["jurisdiction_name"] == "Sarasota"
    assert row["state"] == "FL"
    assert row["contact_name"] == "Pat Lee"
    assert row["contact_title"] == "Planning Director"
    assert row["email"] == "pat.lee@sarasota.gov"
    assert row["outreach_notes"] == "Met at conference booth"
    assert row["send_status"] == "prepared"
    assert row["reply_status"] == "not_sent"


def test_manual_contact_defaults_source_to_manual(crm_paths):
    add_manual_contact(
        jurisdiction_name="Tampa",
        state="FL",
        email="planner@tampa.gov",
    )
    row = read_outreach_rows()[0]
    assert row["contact_source"] == "Manual"


def test_harvested_contact_defaults_source_to_harvested(crm_paths):
    working, _ = crm_paths
    write_csv(working, [_working_row()], WORKING_COLUMNS)
    prepare_outreach()
    row = read_outreach_rows()[0]
    assert row["contact_source"] == CONTACT_SOURCE_HARVESTED


def test_duplicate_manual_contact_rejected(crm_paths):
    add_manual_contact(
        jurisdiction_name="Orlando",
        state="FL",
        email="same@orlando.gov",
        contact_name="First",
    )
    ok, msg = add_manual_contact(
        jurisdiction_name="Orlando",
        state="FL",
        email="same@orlando.gov",
        contact_name="Second",
    )
    assert ok is False
    assert "already exists" in msg.lower()
    assert len(read_outreach_rows()) == 1


def test_required_fields_enforced(crm_paths):
    ok, msg = add_manual_contact(
        jurisdiction_name="",
        state="FL",
        email="x@y.gov",
    )
    assert ok is False
    assert "Jurisdiction" in msg

    ok, msg = add_manual_contact(
        jurisdiction_name="Gainesville",
        state="",
        email="x@y.gov",
    )
    assert ok is False
    assert "State" in msg

    ok, msg = add_manual_contact(
        jurisdiction_name="Gainesville",
        state="FL",
        email="",
    )
    assert ok is False
    assert "Email" in msg

    ok, msg = add_manual_contact(
        jurisdiction_name="Gainesville",
        state="FL",
        email="not-an-email",
    )
    assert ok is False
    assert "valid email" in msg.lower()


def test_manual_contact_can_be_marked_ready(crm_paths):
    add_manual_contact(
        jurisdiction_name="Naples",
        state="FL",
        contact_name="Chris Planner",
        email="chris@naples.gov",
    )
    rows = read_outreach_rows()
    assert len(rows) == 1
    assert not is_ready(rows[0])

    rows[0]["approved"] = "yes"
    write_outreach_rows(rows)
    loaded = read_outreach_rows()
    assert is_ready(loaded[0])

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        html = client.get("/?filter=ready").data.decode("utf-8")
    assert "chris@naples.gov" in html
    assert "Naples" in html


def test_add_contact_route_persists(crm_paths):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.post(
            "/contacts/add",
            data={
                "jurisdiction_name": "Boca Raton",
                "state": "FL",
                "contact_name": "Sam Rivera",
                "contact_title": "AICP",
                "email": "sam@bocaraton.gov",
                "contact_source": "Referral",
                "outreach_notes": "Intro from colleague",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Added contact" in resp.data
    row = read_outreach_rows()[0]
    assert row["contact_source"] == "Referral"
    assert row["contact_name"] == "Sam Rivera"


def test_add_contact_uses_protected_persistence(crm_paths, monkeypatch):
    calls: list[list] = []

    def spy(rows, **kwargs):
        calls.append(rows)

    monkeypatch.setattr("src.outreach_persistence.write_outreach_csv_atomic", spy)
    add_manual_contact(
        jurisdiction_name="Delray Beach",
        state="FL",
        email="planner@delray.gov",
    )
    assert len(calls) == 1
    assert len(calls[0]) == 1
    assert calls[0][0]["email"] == "planner@delray.gov"


def test_legacy_csv_without_contact_source_column_loads(tmp_path, monkeypatch):
    import src.paths as paths
    import src.outreach_store as store
    from src.csv_utils import read_csv

    outreach = tmp_path / "legacy_outreach.csv"
    legacy_cols = [c for c in OUTREACH_COLUMNS if c != "contact_source"]
    write_csv(
        outreach,
        [
            {
                "jurisdiction_name": "Legacy City",
                "state": "DE",
                "email": "legacy@city.gov",
                "contact_name": "Legacy Planner",
                "send_status": "prepared",
                "reply_status": "not_sent",
            }
        ],
        legacy_cols,
    )
    monkeypatch.setattr(paths, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(store, "OUTREACH_CSV", outreach)

    loaded = read_outreach_rows()
    assert len(loaded) == 1
    assert loaded[0]["email"] == "legacy@city.gov"
    assert loaded[0]["contact_source"] == CONTACT_SOURCE_HARVESTED

    raw = read_csv(outreach, OUTREACH_COLUMNS)
    assert raw[0].get("contact_source", "") == ""
