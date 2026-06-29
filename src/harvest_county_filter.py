"""County-scoped harvest targeting helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from src.census_seed import STATE_FIPS, Jurisdiction, list_census_counties
from src.paths import CACHE_DIR, COUNTY_BOOTSTRAP_JSON


COUNTY_INDEX_CACHE = CACHE_DIR / "county_index.json"
_bootstrap_cache: dict[str, list[dict[str, str]]] | None = None


@dataclass(frozen=True)
class SelectedCounty:
    state: str
    county: str

    def to_dict(self) -> dict[str, str]:
        return {"state": self.state.upper(), "county": self.county}

    @classmethod
    def from_dict(cls, raw: dict) -> SelectedCounty | None:
        if not isinstance(raw, dict):
            return None
        state = str(raw.get("state", "")).strip().upper()
        county = str(raw.get("county", "")).strip()
        if not state or not county:
            return None
        return cls(state=state, county=county)

    @classmethod
    def from_form_value(cls, value: str) -> SelectedCounty | None:
        parts = value.split("|", 1)
        if len(parts) != 2:
            return None
        state, county = parts[0].strip().upper(), parts[1].strip()
        if not state or not county:
            return None
        return cls(state=state, county=county)

    def option_value(self) -> str:
        return f"{self.state}|{self.county}"

    def match_key(self) -> tuple[str, str]:
        return (self.state.upper(), normalize_county_name(self.county))


@dataclass
class CountyLoadResult:
    counties: list[SelectedCounty] = field(default_factory=list)
    message: str = ""
    error: str | None = None

    def to_api_payload(self) -> dict[str, object]:
        return {
            "counties": [
                {
                    "state": option.state,
                    "county": option.county,
                    "value": option.option_value(),
                }
                for option in self.counties
            ],
            "message": self.message,
            "error": self.error,
        }


def normalize_county_name(name: str) -> str:
    n = name.strip()
    n = re.sub(r"\s+county\s*$", "", n, flags=re.I)
    return n.lower()


def parse_selected_counties(raw) -> list[SelectedCounty]:
    if not raw:
        return []
    if not isinstance(raw, list):
        return []
    out: list[SelectedCounty] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        selected = (
            SelectedCounty.from_dict(item)
            if isinstance(item, dict)
            else SelectedCounty.from_form_value(str(item))
            if isinstance(item, str)
            else None
        )
        if selected is None:
            continue
        key = selected.match_key()
        if key in seen:
            continue
        seen.add(key)
        out.append(selected)
    return sorted(out, key=lambda c: (c.state, c.county.lower()))


def selected_county_keys(selected: list[SelectedCounty]) -> set[tuple[str, str]]:
    return {c.match_key() for c in selected}


def jurisdiction_county_key(j: Jurisdiction) -> tuple[str, str] | None:
    if j.geography_type == "county":
        label = j.jurisdiction_name or j.county_name
    else:
        label = j.county_name
    if not label:
        return None
    return (j.state.upper(), normalize_county_name(label))


def filter_jurisdictions_by_selected_counties(
    jurisdictions: list[Jurisdiction],
    selected: list[SelectedCounty],
) -> list[Jurisdiction]:
    if not selected:
        return jurisdictions
    keys = selected_county_keys(selected)
    return [
        j
        for j in jurisdictions
        if (key := jurisdiction_county_key(j)) is not None and key in keys
    ]


def _county_display_label(j: Jurisdiction) -> str | None:
    if j.geography_type == "county":
        name = j.jurisdiction_name.strip()
        if name:
            if name.lower().endswith(" county"):
                return name
            base = j.county_name or name
            return f"{base} County" if base else None
        return None
    if j.county_name:
        return f"{j.county_name} County"
    return None


def derive_county_options(
    jurisdictions: list[Jurisdiction],
    states: list[str],
) -> list[SelectedCounty]:
    state_set = {s.strip().upper() for s in states if s.strip()}
    seen: set[tuple[str, str]] = set()
    options: list[SelectedCounty] = []
    for j in jurisdictions:
        if j.state.upper() not in state_set:
            continue
        label = _county_display_label(j)
        if not label:
            continue
        selected = SelectedCounty(state=j.state.upper(), county=label)
        key = selected.match_key()
        if key in seen:
            continue
        seen.add(key)
        options.append(selected)
    return sorted(options, key=lambda c: (c.state, c.county.lower()))


def _load_county_cache() -> dict[str, list[dict[str, str]]]:
    if not COUNTY_INDEX_CACHE.exists():
        return {}
    try:
        raw = json.loads(COUNTY_INDEX_CACHE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_county_cache(cache: dict[str, list[dict[str, str]]]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    COUNTY_INDEX_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _load_bootstrap_index() -> dict[str, list[dict[str, str]]]:
    global _bootstrap_cache
    if _bootstrap_cache is not None:
        return _bootstrap_cache
    if not COUNTY_BOOTSTRAP_JSON.exists():
        _bootstrap_cache = {}
        return _bootstrap_cache
    try:
        raw = json.loads(COUNTY_BOOTSTRAP_JSON.read_text(encoding="utf-8"))
        _bootstrap_cache = raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        _bootstrap_cache = {}
    return _bootstrap_cache


def fetch_census_county_options(state: str) -> list[SelectedCounty]:
    """All counties for a state from Census (authoritative seed source)."""
    state = state.upper()
    return [
        SelectedCounty(state=state, county=display)
        for _, display in list_census_counties(state)
    ]


def _counties_for_state(
    state: str,
    *,
    runtime_cache: dict[str, list[dict[str, str]]],
    bootstrap: dict[str, list[dict[str, str]]],
) -> tuple[list[SelectedCounty], str | None]:
    state = state.upper()
    if state not in STATE_FIPS:
        return [], f"{state} is not a supported state code."

    cached = runtime_cache.get(state)
    if cached:
        return parse_selected_counties(cached), None

    boot_rows = bootstrap.get(state) or []
    if boot_rows:
        parsed = parse_selected_counties(boot_rows)
        runtime_cache[state] = [c.to_dict() for c in parsed]
        return parsed, None

    try:
        fetched = fetch_census_county_options(state)
    except Exception as exc:
        return [], f"Census lookup failed for {state}: {exc}"

    if not fetched:
        return [], f"No counties returned for {state}."

    runtime_cache[state] = [c.to_dict() for c in fetched]
    return fetched, None


def load_county_options_for_states_with_status(
    states: list[str],
    *,
    min_population: int,
    max_population: int,
) -> CountyLoadResult:
    del min_population, max_population
    states = [s.strip().upper() for s in states if s.strip()]
    if not states:
        return CountyLoadResult(message="Select a state to load counties.")

    runtime_cache = _load_county_cache()
    bootstrap = _load_bootstrap_index()
    cache_updated = False
    options: list[SelectedCounty] = []
    errors: list[str] = []

    for state in states:
        before = runtime_cache.get(state)
        state_options, err = _counties_for_state(
            state,
            runtime_cache=runtime_cache,
            bootstrap=bootstrap,
        )
        if runtime_cache.get(state) != before:
            cache_updated = True
        if err:
            errors.append(err)
        options.extend(state_options)

    if cache_updated:
        _save_county_cache(runtime_cache)

    options = sorted(options, key=lambda c: (c.state, c.county.lower()))
    if options:
        noun = "county" if len(options) == 1 else "counties"
        message = f"Loaded {len(options)} {noun}."
        return CountyLoadResult(counties=options, message=message, error="; ".join(errors) or None)

    if errors:
        return CountyLoadResult(
            message="County load failed.",
            error="; ".join(errors),
        )
    return CountyLoadResult(message="No counties found for selected states.")


def load_county_options_for_states(
    states: list[str],
    *,
    min_population: int,
    max_population: int,
) -> list[SelectedCounty]:
    return load_county_options_for_states_with_status(
        states,
        min_population=min_population,
        max_population=max_population,
    ).counties
