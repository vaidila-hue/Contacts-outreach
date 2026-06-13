"""Regression tests: production CRM paths must not be touched by pytest."""

from __future__ import annotations

import pytest

from src.crm_path_guard import (
    ProductionCrmPathError,
    assert_crm_write_path_allowed,
    is_production_outreach_backup_path,
    is_production_outreach_csv,
)
from src.export_results import write_outreach_csv
from src.outreach_persistence import backup_outreach_csv, write_outreach_csv_atomic
from src.outreach_store import read_outreach_rows, write_outreach_rows
from src.paths import OUTREACH_COLUMNS, PRODUCTION_OUTREACH_BACKUP_DIR, PRODUCTION_OUTREACH_CSV
from src import paths


def _sample_row(email: str = "isolated@city.gov") -> dict[str, str]:
    row = {col: "" for col in OUTREACH_COLUMNS}
    row.update(
        {
            "contact_name": "Test Planner",
            "contact_title": "Director",
            "jurisdiction_name": "Test City",
            "state": "FL",
            "email": email,
            "send_status": "prepared",
            "reply_status": "not_sent",
        }
    )
    return row


def test_autouse_redirects_outreach_paths_away_from_production():
    assert paths.OUTREACH_CSV != PRODUCTION_OUTREACH_CSV
    assert paths.OUTREACH_BACKUP_DIR != PRODUCTION_OUTREACH_BACKUP_DIR
    assert is_production_outreach_csv(PRODUCTION_OUTREACH_CSV)
    assert not is_production_outreach_csv(paths.OUTREACH_CSV)


def test_guard_rejects_production_outreach_csv():
    with pytest.raises(ProductionCrmPathError, match="outreach.csv"):
        assert_crm_write_path_allowed(PRODUCTION_OUTREACH_CSV)


def test_guard_rejects_production_backup_paths():
    with pytest.raises(ProductionCrmPathError, match="backup"):
        assert_crm_write_path_allowed(PRODUCTION_OUTREACH_BACKUP_DIR)
    with pytest.raises(ProductionCrmPathError, match="backup"):
        assert_crm_write_path_allowed(
            PRODUCTION_OUTREACH_BACKUP_DIR / "outreach_20260101_120000.csv"
        )


def test_guard_allows_isolated_paths():
    assert_crm_write_path_allowed(paths.OUTREACH_CSV)
    assert_crm_write_path_allowed(paths.OUTREACH_BACKUP_DIR)
    assert_crm_write_path_allowed(
        paths.OUTREACH_BACKUP_DIR / "outreach_20260101_120000.csv"
    )


def test_production_outreach_untouched_during_writes(tmp_path):
    PRODUCTION_OUTREACH_CSV.parent.mkdir(parents=True, exist_ok=True)
    if not PRODUCTION_OUTREACH_CSV.exists():
        PRODUCTION_OUTREACH_CSV.write_text("approved,email\n", encoding="utf-8")
    before_mtime = PRODUCTION_OUTREACH_CSV.stat().st_mtime
    before_size = PRODUCTION_OUTREACH_CSV.stat().st_size

    write_outreach_rows([_sample_row("a@city.gov")])
    write_outreach_rows([_sample_row("b@city.gov"), _sample_row("c@city.gov")])
    write_outreach_csv([_sample_row("d@city.gov")])
    backup_outreach_csv()
    write_outreach_csv_atomic([_sample_row("e@city.gov")])

    assert len(read_outreach_rows()) == 1
    assert read_outreach_rows()[0]["email"] == "e@city.gov"
    assert PRODUCTION_OUTREACH_CSV.stat().st_mtime == before_mtime
    assert PRODUCTION_OUTREACH_CSV.stat().st_size == before_size


def test_production_backup_dir_untouched_during_writes():
    PRODUCTION_OUTREACH_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    before = {
        p.name: p.stat().st_mtime
        for p in PRODUCTION_OUTREACH_BACKUP_DIR.glob("*.csv")
    }

    write_outreach_rows([_sample_row("user0@test.gov")])
    write_outreach_rows(
        [
            _sample_row("user0@test.gov"),
            _sample_row("user1@test.gov"),
            _sample_row("user2@test.gov"),
            _sample_row("user3@test.gov"),
        ]
    )

    after = {
        p.name: p.stat().st_mtime
        for p in PRODUCTION_OUTREACH_BACKUP_DIR.glob("*.csv")
    }
    assert after == before


def test_direct_production_write_blocked_by_guard(monkeypatch):
    monkeypatch.setattr(paths, "OUTREACH_CSV", PRODUCTION_OUTREACH_CSV)
    with pytest.raises(ProductionCrmPathError, match="outreach.csv"):
        write_outreach_rows([_sample_row()])


def test_send_queue_style_writes_stay_isolated():
    """Regression for City0/user0@test.gov fixture pattern leaking to data/."""
    PRODUCTION_OUTREACH_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    prod_before = {p.name for p in PRODUCTION_OUTREACH_BACKUP_DIR.glob("outreach_*.csv")}

    working_rows = [_sample_row(f"user{i}@test.gov") for i in range(4)]
    for i, row in enumerate(working_rows):
        row["jurisdiction_name"] = f"City{i}"
        row["contact_name"] = f"Planner {i}"

    write_outreach_rows(working_rows)
    write_outreach_rows(working_rows[:1])

    prod_after = {p.name for p in PRODUCTION_OUTREACH_BACKUP_DIR.glob("outreach_*.csv")}
    assert prod_after == prod_before
    assert len(list(paths.OUTREACH_BACKUP_DIR.glob("outreach_*.csv"))) >= 1
    assert not is_production_outreach_csv(paths.OUTREACH_CSV)
