"""Harvest running indicator for CRM UI."""

from __future__ import annotations

from src.harvest_summary import now_iso
from src.paths import HARVEST_RUNNING_LOCK


def set_harvest_running() -> None:
    HARVEST_RUNNING_LOCK.parent.mkdir(parents=True, exist_ok=True)
    HARVEST_RUNNING_LOCK.write_text(now_iso(), encoding="utf-8")


def clear_harvest_running() -> None:
    try:
        HARVEST_RUNNING_LOCK.unlink(missing_ok=True)
    except OSError:
        pass


def is_harvest_running() -> bool:
    return HARVEST_RUNNING_LOCK.exists()
