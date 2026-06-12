"""Tests for send queue config persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
import random

import pytest

from src.send_queue import compute_next_send_at, rate_limits_exceeded
from src.send_queue_config_store import (
    DEFAULT_MAX_PER_DAY,
    DEFAULT_MAX_PER_HOUR,
    SendQueueConfigSettings,
    load_send_queue_config,
    save_send_queue_config,
)
from src.paths import OUTREACH_COLUMNS


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    import src.paths as paths
    import src.send_queue_config_store as sqcs

    cfg = tmp_path / "send_queue_config.json"
    monkeypatch.setattr(paths, "SEND_QUEUE_CONFIG_JSON", cfg)
    monkeypatch.setattr(sqcs, "SEND_QUEUE_CONFIG_JSON", cfg)
    return cfg


def test_default_config_created_if_missing(config_path):
    assert not config_path.exists()
    settings = load_send_queue_config()
    assert config_path.exists()
    assert settings.interval_minutes == 5
    assert settings.jitter_seconds == 90
    assert settings.max_per_hour == DEFAULT_MAX_PER_HOUR
    assert settings.max_per_day == DEFAULT_MAX_PER_DAY
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["max_per_day"] == 75
    assert raw["max_per_hour"] == 12


def test_save_and_load_custom_config(config_path):
    save_send_queue_config(
        SendQueueConfigSettings(
            interval_minutes=7,
            jitter_seconds=60,
            max_per_hour=8,
            max_per_day=100,
        )
    )
    loaded = load_send_queue_config(create_if_missing=False)
    assert loaded.interval_minutes == 7
    assert loaded.jitter_seconds == 60
    assert loaded.max_per_hour == 8
    assert loaded.max_per_day == 100


def test_custom_interval_controls_next_send_at(config_path):
    save_send_queue_config(SendQueueConfigSettings(interval_minutes=10, jitter_seconds=0))
    config = load_send_queue_config(create_if_missing=False)
    now = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)
    rng = random.Random(0)
    nxt = compute_next_send_at(now=now, rng=rng, config=config)
    delta = (datetime.fromisoformat(nxt) - now).total_seconds()
    assert delta == 600


def test_daily_limit_uses_config_not_hardcoded_25(config_path):
    save_send_queue_config(SendQueueConfigSettings(max_per_day=30, max_per_hour=100))
    now = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(30):
        row = {col: "" for col in OUTREACH_COLUMNS}
        row.update(
            {
                "email": f"u{i}@test.gov",
                "state": "FL",
                "jurisdiction_name": f"C{i}",
                "send_status": "sent",
                "sent_at": now.isoformat(),
            }
        )
        rows.append(row)
    limited, reason = rate_limits_exceeded(rows, now=now)
    assert limited
    assert "daily" in reason


def test_thirty_four_sent_does_not_block_under_75_day_cap(config_path):
    save_send_queue_config(SendQueueConfigSettings(max_per_day=75, max_per_hour=75))
    now = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(34):
        row = {col: "" for col in OUTREACH_COLUMNS}
        row.update(
            {
                "email": f"u{i}@test.gov",
                "state": "FL",
                "jurisdiction_name": f"C{i}",
                "send_status": "sent",
                "sent_at": now.isoformat(),
            }
        )
        rows.append(row)
    limited, reason = rate_limits_exceeded(rows, now=now)
    assert not limited
    assert reason == ""


def test_cadence_and_limits_display():
    settings = SendQueueConfigSettings.defaults()
    assert settings.cadence_display() == "5 min ±90s"
    assert settings.limits_display() == "12/hr · 75/day"


def test_ui_save_queue_settings_persists(tmp_path, monkeypatch):
    import src.paths as paths
    import src.send_queue_config_store as sqcs
    from src.outreach_ui import create_app

    cfg = tmp_path / "send_queue_config.json"
    monkeypatch.setattr(paths, "SEND_QUEUE_CONFIG_JSON", cfg)
    monkeypatch.setattr(sqcs, "SEND_QUEUE_CONFIG_JSON", cfg)

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.post(
            "/send-queue/settings",
            data={
                "interval_minutes": "6",
                "jitter_seconds": "45",
                "max_per_hour": "15",
                "max_per_day": "80",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Queue Settings" in html

    raw = json.loads(cfg.read_text(encoding="utf-8"))
    assert raw["interval_minutes"] == 6
    assert raw["max_per_day"] == 80

