"""Harvest configuration persistence for UI-driven runs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from src.paths import DATA_DIR, DEFAULT_MAX_POP, DEFAULT_MIN_POP, DEFAULT_STATES, HARVEST_CONFIG_JSON


@dataclass
class HarvestConfigSettings:
    states: list[str]
    min_population: int
    max_population: int
    limit: int
    include_counties: bool
    deep_mode: bool

    @classmethod
    def defaults(cls) -> HarvestConfigSettings:
        return cls(
            states=[s.strip() for s in DEFAULT_STATES.split(",") if s.strip()],
            min_population=DEFAULT_MIN_POP,
            max_population=DEFAULT_MAX_POP,
            limit=50,
            include_counties=False,
            deep_mode=False,
        )

    def states_csv(self) -> str:
        return ",".join(self.states)


def load_harvest_config() -> HarvestConfigSettings:
    if not HARVEST_CONFIG_JSON.exists():
        return HarvestConfigSettings.defaults()
    try:
        raw = json.loads(HARVEST_CONFIG_JSON.read_text(encoding="utf-8"))
        defaults = HarvestConfigSettings.defaults()
        states = raw.get("states", defaults.states)
        if isinstance(states, str):
            states = [s.strip().upper() for s in states.split(",") if s.strip()]
        return HarvestConfigSettings(
            states=[s.upper() for s in states],
            min_population=int(raw.get("min_population", defaults.min_population)),
            max_population=int(raw.get("max_population", defaults.max_population)),
            limit=int(raw.get("limit", defaults.limit)),
            include_counties=bool(raw.get("include_counties", defaults.include_counties)),
            deep_mode=bool(raw.get("deep_mode", defaults.deep_mode)),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return HarvestConfigSettings.defaults()


def save_harvest_config(settings: HarvestConfigSettings) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = asdict(settings)
    HARVEST_CONFIG_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
