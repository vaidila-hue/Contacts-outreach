"""Tests for outreach.csv backup and atomic write protection."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.csv_utils import write_csv
from src.export_results import write_outreach_csv
from src.outreach_persistence import (
    backup_outreach_csv,
    list_outreach_backups,
    outreach_file_has_rows,
    prune_outreach_backups,
    restore_outreach_backup,
    write_outreach_csv_atomic,
)
from src.outreach_store import read_outreach_rows, write_outreach_rows
from src.paths import OUTREACH_COLUMNS


@pytest.fixture
def outreach_paths(tmp_path, monkeypatch):
    import src.paths as paths

    outreach = tmp_path / "outreach.csv"
    backup_dir = tmp_path / "backups" / "outreach"

    monkeypatch.setattr(paths, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(paths, "OUTREACH_BACKUP_DIR", backup_dir)

    return outreach, backup_dir


def _sample_row(email: str = "a@city.gov", notes: str = "") -> dict[str, str]:
    row = {col: "" for col in OUTREACH_COLUMNS}
    row.update(
        {
            "contact_name": "Alex Planner",
            "contact_title": "Director",
            "jurisdiction_name": "Sample City",
            "state": "DE",
            "email": email,
            "send_status": "prepared",
            "reply_status": "not_sent",
            "outreach_notes": notes,
        }
    )
    return row


def test_no_backup_when_outreach_missing(outreach_paths):
    outreach, backup_dir = outreach_paths
    assert backup_outreach_csv(outreach) is None
    write_outreach_rows([_sample_row()])
    assert not list(backup_dir.glob("*.csv"))


def test_no_backup_when_outreach_header_only(outreach_paths):
    outreach, backup_dir = outreach_paths
    write_csv(outreach, [], OUTREACH_COLUMNS)
    assert not outreach_file_has_rows(outreach)
    assert backup_outreach_csv(outreach) is None


def test_write_outreach_rows_creates_backup_before_overwrite(outreach_paths):
    outreach, backup_dir = outreach_paths
    write_outreach_rows([_sample_row(email="old@city.gov", notes="keep me")])
    write_outreach_rows([_sample_row(email="new@city.gov")])

    backups = list_outreach_backups()
    assert len(backups) == 1
    backup_rows = list(csv.DictReader(backups[0].open(encoding="utf-8")))
    assert len(backup_rows) == 1
    assert backup_rows[0]["email"] == "old@city.gov"
    assert backup_rows[0]["outreach_notes"] == "keep me"

    current = read_outreach_rows()
    assert len(current) == 1
    assert current[0]["email"] == "new@city.gov"


def test_write_outreach_csv_delegates_to_protected_write(outreach_paths):
    outreach, backup_dir = outreach_paths
    write_outreach_csv([_sample_row(email="first@city.gov")])
    write_outreach_csv([_sample_row(email="second@city.gov")])
    assert len(list_outreach_backups()) == 1
    assert read_outreach_rows()[0]["email"] == "second@city.gov"


def test_atomic_write_replaces_file_and_removes_temp(outreach_paths):
    outreach, backup_dir = outreach_paths
    write_outreach_csv_atomic([_sample_row()], outreach_path=outreach)
    assert outreach.exists()
    assert not outreach.with_name(outreach.name + ".tmp").exists()
    rows = read_outreach_rows()
    assert len(rows) == 1
    assert rows[0]["email"] == "a@city.gov"


def test_backup_retention_keeps_newest_100(outreach_paths):
    _, backup_dir = outreach_paths
    backup_dir.mkdir(parents=True, exist_ok=True)
    for i in range(105):
        name = f"outreach_20260101_{i:06d}.csv"
        (backup_dir / name).write_text("x", encoding="utf-8")
    removed = prune_outreach_backups(max_keep=100)
    assert removed == 5
    remaining = sorted(p.name for p in backup_dir.glob("outreach_*.csv"))
    assert len(remaining) == 100
    assert remaining[0] == "outreach_20260101_000005.csv"
    assert remaining[-1] == "outreach_20260101_000104.csv"


def test_restore_outreach_backup(outreach_paths):
    outreach, backup_dir = outreach_paths
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_name = "outreach_20260613_120000.csv"
    write_csv(backup_dir / backup_name, [_sample_row(email="restored@city.gov", notes="from backup")], OUTREACH_COLUMNS)
    write_outreach_rows([_sample_row(email="current@city.gov")])

    restore_outreach_backup(backup_name, outreach_path=outreach)

    rows = read_outreach_rows()
    assert len(rows) == 1
    assert rows[0]["email"] == "restored@city.gov"
    assert rows[0]["outreach_notes"] == "from backup"
    assert len(list_outreach_backups()) == 2


def test_restore_rejects_invalid_filename(outreach_paths):
    outreach, _ = outreach_paths
    with pytest.raises(ValueError):
        restore_outreach_backup("../secrets.csv", outreach_path=outreach)


def test_cli_list_and_restore(outreach_paths, capsys):
    from src.outreach_cli import run_outreach_list_backups, run_outreach_restore_backup

    outreach, backup_dir = outreach_paths
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_name = "outreach_20260613_130000.csv"
    write_csv(backup_dir / backup_name, [_sample_row(email="cli@city.gov")], OUTREACH_COLUMNS)
    write_outreach_rows([_sample_row(email="live@city.gov")])

    assert run_outreach_list_backups() == 0
    listed = capsys.readouterr().out
    assert backup_name in listed

    assert run_outreach_restore_backup(backup_name) == 0
    assert read_outreach_rows()[0]["email"] == "cli@city.gov"
