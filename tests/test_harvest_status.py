"""Tests for harvest running status indicator."""

from src.harvest_status import clear_harvest_running, is_harvest_running, set_harvest_running


def test_harvest_running_lock(tmp_path, monkeypatch):
    monkeypatch.setattr("src.harvest_status.HARVEST_RUNNING_LOCK", tmp_path / "harvest_running.lock")
    assert not is_harvest_running()
    set_harvest_running()
    assert is_harvest_running()
    clear_harvest_running()
    assert not is_harvest_running()
