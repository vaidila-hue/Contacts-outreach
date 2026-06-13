"""Shared pytest fixtures and production CRM path isolation.

Every test redirects outreach.csv and backup storage to a per-test temp
directory. Runtime guards in src/crm_path_guard.py refuse writes to
production paths when PYTEST_CURRENT_TEST is set.

See tests/CRM_TEST_ISOLATION.md for details.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_production_crm_paths(tmp_path, monkeypatch):
    """Redirect CRM outreach paths away from data/ for every test."""
    import src.paths as paths

    crm_root = tmp_path / "crm_isolated"
    crm_root.mkdir()
    outreach = crm_root / "outreach.csv"
    backup_dir = crm_root / "backups" / "outreach"
    backup_dir.mkdir(parents=True)

    monkeypatch.setattr(paths, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(paths, "OUTREACH_BACKUP_DIR", backup_dir)

    return outreach, backup_dir
