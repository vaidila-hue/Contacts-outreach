"""Guardrails: pytest must not read/write production CRM outreach files."""

from __future__ import annotations

import os
from pathlib import Path

from src.paths import PRODUCTION_OUTREACH_BACKUP_DIR, PRODUCTION_OUTREACH_CSV


class ProductionCrmPathError(RuntimeError):
    """Raised when a test attempts to touch production CRM paths."""


def pytest_active() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _resolved(path: Path) -> Path:
    return path.resolve()


def is_production_outreach_csv(path: Path) -> bool:
    return _resolved(path) == _resolved(PRODUCTION_OUTREACH_CSV)


def is_production_outreach_backup_path(path: Path) -> bool:
    resolved = _resolved(path)
    backup_root = _resolved(PRODUCTION_OUTREACH_BACKUP_DIR)
    if resolved == backup_root:
        return True
    try:
        resolved.relative_to(backup_root)
        return True
    except ValueError:
        return False


def assert_crm_write_path_allowed(path: Path) -> None:
    """Fail fast during pytest if a write targets production CRM storage."""
    if not pytest_active():
        return
    if is_production_outreach_csv(path):
        raise ProductionCrmPathError(
            "Refusing to write production outreach.csv during tests "
            f"({path}). Use tmp_path and monkeypatch paths.OUTREACH_CSV."
        )
    if is_production_outreach_backup_path(path):
        raise ProductionCrmPathError(
            "Refusing to write production outreach backups during tests "
            f"({path}). Use tmp_path and monkeypatch paths.OUTREACH_BACKUP_DIR."
        )
