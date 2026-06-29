"""Harvest config persistence: local file, defaults, and git hygiene."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from src.harvest_config_store import HarvestConfigSettings, load_harvest_config, save_harvest_config
from src.paths import DEFAULT_MAX_POP, DEFAULT_MIN_POP, DEFAULT_STATES, ROOT


@pytest.fixture
def harvest_config_path(tmp_path, monkeypatch):
    import src.harvest_config_store as hcs
    import src.paths as paths

    config_path = tmp_path / "harvest_config.json"
    monkeypatch.setattr(paths, "HARVEST_CONFIG_JSON", config_path)
    monkeypatch.setattr(hcs, "HARVEST_CONFIG_JSON", config_path)
    return config_path


def test_save_harvest_config_writes_local_file(harvest_config_path):
    settings = HarvestConfigSettings(
        states=["FL", "WI"],
        min_population=25000,
        max_population=90000,
        limit=25,
        include_counties=True,
        deep_mode=True,
        selected_counties=[],
    )

    save_harvest_config(settings)

    assert harvest_config_path.is_file()
    on_disk = json.loads(harvest_config_path.read_text(encoding="utf-8"))
    assert on_disk == asdict(settings)


def test_load_after_restart_reads_saved_local_config(harvest_config_path):
    settings = HarvestConfigSettings(
        states=["OR", "WA"],
        min_population=30000,
        max_population=80000,
        limit=40,
        include_counties=False,
        deep_mode=True,
        selected_counties=[],
    )
    save_harvest_config(settings)

    loaded = load_harvest_config()

    assert loaded == settings
    assert loaded.states == ["OR", "WA"]
    assert loaded.deep_mode is True


def test_missing_config_falls_back_to_defaults(harvest_config_path):
    assert not harvest_config_path.exists()

    loaded = load_harvest_config()
    defaults = HarvestConfigSettings.defaults()

    assert loaded == defaults
    assert loaded.min_population == DEFAULT_MIN_POP
    assert loaded.max_population == DEFAULT_MAX_POP
    assert loaded.states == [s.strip() for s in DEFAULT_STATES.split(",") if s.strip()]


def test_harvest_config_json_is_gitignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    lines = [line.strip() for line in gitignore.splitlines() if line.strip() and not line.strip().startswith("#")]
    assert "data/harvest_config.json" in lines


def test_harvest_config_example_exists_and_matches_code_defaults():
    example_path = ROOT / "data" / "harvest_config.example.json"
    assert example_path.is_file()

    example = json.loads(example_path.read_text(encoding="utf-8"))
    defaults = asdict(HarvestConfigSettings.defaults())

    assert example == defaults
