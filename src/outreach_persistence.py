"""Backup and atomic write protection for outreach.csv (CRM system of record)."""

from __future__ import annotations

import csv
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from src import paths
from src.paths import OUTREACH_COLUMNS


MAX_OUTREACH_BACKUPS = 100
_BACKUP_NAME_RE = re.compile(r"^outreach_\d{8}_\d{6}\.csv$")


def _outreach_csv() -> Path:
    return paths.OUTREACH_CSV


def _backup_dir() -> Path:
    return paths.OUTREACH_BACKUP_DIR


def outreach_file_has_rows(outreach_path: Path | None = None) -> bool:
    """True when the file exists and contains at least one data row."""
    path = outreach_path or _outreach_csv()
    if not path.exists():
        return False
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            next(reader)
        except StopIteration:
            return False
        return any(row for row in reader)


def backup_outreach_csv(outreach_path: Path | None = None) -> Path | None:
    """Copy existing outreach.csv to a timestamped backup. Returns backup path or None."""
    path = outreach_path or _outreach_csv()
    if not outreach_file_has_rows(path):
        return None
    backup_dir = _backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"outreach_{stamp}.csv"
    shutil.copy2(path, dest)
    prune_outreach_backups()
    return dest


def prune_outreach_backups(*, max_keep: int = MAX_OUTREACH_BACKUPS) -> int:
    """Delete oldest backups beyond max_keep. Returns number deleted."""
    backup_dir = _backup_dir()
    if not backup_dir.exists():
        return 0
    backups = sorted(
        backup_dir.glob("outreach_*.csv"),
        key=lambda p: p.name,
        reverse=True,
    )
    removed = 0
    for old in backups[max_keep:]:
        old.unlink(missing_ok=True)
        removed += 1
    return removed


def list_outreach_backups() -> list[Path]:
    """Newest-first list of outreach backup files."""
    backup_dir = _backup_dir()
    if not backup_dir.exists():
        return []
    return sorted(
        backup_dir.glob("outreach_*.csv"),
        key=lambda p: p.name,
        reverse=True,
    )


def _validate_backup_filename(filename: str) -> str:
    name = filename.strip()
    if not name or not _BACKUP_NAME_RE.match(name):
        raise ValueError(f"Invalid backup filename: {filename!r}")
    return name


def restore_outreach_backup(filename: str, *, outreach_path: Path | None = None) -> Path:
    """Restore outreach.csv from a named backup (backs up current file first)."""
    name = _validate_backup_filename(filename)
    backup = _backup_dir() / name
    if not backup.is_file():
        raise FileNotFoundError(f"Backup not found: {name}")

    from src.csv_utils import read_csv

    rows = read_csv(backup, OUTREACH_COLUMNS)
    write_outreach_csv_atomic(rows, outreach_path=outreach_path or _outreach_csv())
    return backup


def write_outreach_csv_atomic(
    rows: list[dict[str, Any]],
    *,
    outreach_path: Path | None = None,
    columns: list[str] | None = None,
) -> None:
    """Backup existing outreach.csv, then replace it atomically via a temp file."""
    columns = columns or OUTREACH_COLUMNS
    target = outreach_path or _outreach_csv()
    backup_outreach_csv(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(target.name + ".tmp")
    try:
        with tmp_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({col: row.get(col, "") for col in columns})
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
