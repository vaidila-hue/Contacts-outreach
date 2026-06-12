"""Send queue throttling configuration (interval and rate limits)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from src.paths import DATA_DIR, SEND_QUEUE_CONFIG_JSON

DEFAULT_INTERVAL_MINUTES = 5
DEFAULT_JITTER_SECONDS = 90
DEFAULT_MAX_PER_HOUR = 12
DEFAULT_MAX_PER_DAY = 75


@dataclass
class SendQueueConfigSettings:
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES
    jitter_seconds: int = DEFAULT_JITTER_SECONDS
    max_per_hour: int = DEFAULT_MAX_PER_HOUR
    max_per_day: int = DEFAULT_MAX_PER_DAY

    @classmethod
    def defaults(cls) -> SendQueueConfigSettings:
        return cls()

    @property
    def interval_seconds(self) -> int:
        return self.interval_minutes * 60

    def cadence_display(self) -> str:
        return f"{self.interval_minutes} min ±{self.jitter_seconds}s"

    def limits_display(self) -> str:
        return f"{self.max_per_hour}/hr · {self.max_per_day}/day"


def load_send_queue_config(*, create_if_missing: bool = True) -> SendQueueConfigSettings:
    if not SEND_QUEUE_CONFIG_JSON.exists():
        defaults = SendQueueConfigSettings.defaults()
        if create_if_missing:
            save_send_queue_config(defaults)
        return defaults
    try:
        raw = json.loads(SEND_QUEUE_CONFIG_JSON.read_text(encoding="utf-8"))
        defaults = SendQueueConfigSettings.defaults()
        return SendQueueConfigSettings(
            interval_minutes=max(1, int(raw.get("interval_minutes", defaults.interval_minutes))),
            jitter_seconds=max(0, int(raw.get("jitter_seconds", defaults.jitter_seconds))),
            max_per_hour=max(1, int(raw.get("max_per_hour", defaults.max_per_hour))),
            max_per_day=max(1, int(raw.get("max_per_day", defaults.max_per_day))),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return SendQueueConfigSettings.defaults()


def save_send_queue_config(settings: SendQueueConfigSettings) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SEND_QUEUE_CONFIG_JSON.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
