"""Census API jurisdiction universe generation (local governments only)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.csv_utils import write_csv
from src.jurisdiction_utils import normalize_jurisdiction_name

STATE_FIPS: dict[str, str] = {
    "AL": "01",
    "AK": "02",
    "AZ": "04",
    "AR": "05",
    "CA": "06",
    "CO": "08",
    "CT": "09",
    "DE": "10",
    "FL": "12",
    "GA": "13",
    "HI": "15",
    "ID": "16",
    "IL": "17",
    "IN": "18",
    "IA": "19",
    "KS": "20",
    "KY": "21",
    "LA": "22",
    "ME": "23",
    "MD": "24",
    "MA": "25",
    "MI": "26",
    "MN": "27",
    "MS": "28",
    "MO": "29",
    "MT": "30",
    "NE": "31",
    "NV": "32",
    "NH": "33",
    "NJ": "34",
    "NM": "35",
    "NY": "36",
    "NC": "37",
    "ND": "38",
    "OH": "39",
    "OK": "40",
    "OR": "41",
    "PA": "42",
    "RI": "44",
    "SC": "45",
    "SD": "46",
    "TN": "47",
    "TX": "48",
    "UT": "49",
    "VT": "50",
    "VA": "51",
    "WA": "53",
    "WV": "54",
    "WI": "55",
    "WY": "56",
    "DC": "11",
}

ACS_YEAR = "2023"
POP_VARIABLE = "B01001_001E"

JURISDICTION_COLUMNS = [
    "state",
    "jurisdiction_name",
    "geography_type",
    "population",
    "county_name",
    "fips_state",
    "fips_county",
    "fips_place",
    "official_website_url",
]

# Statistical / non-local-government markers in Census NAME fields
_STATISTICAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bccd\b", "CCD"),
    (r"\bcdp\b", "CDP"),
    (r"census county division", "CCD"),
    (r"census designated place", "CDP"),
    (r"\bprecinct\b", "other"),
    (r"\bdistrict\b", "other"),
    (r"\bregion\b", "other"),
    (r"balance of", "other"),
)


@dataclass
class SeedStats:
    included: dict[str, int] = field(default_factory=dict)
    excluded: dict[str, int] = field(default_factory=dict)

    def add_included(self, geography_type: str) -> None:
        self.included[geography_type] = self.included.get(geography_type, 0) + 1

    def add_excluded(self, bucket: str) -> None:
        self.excluded[bucket] = self.excluded.get(bucket, 0) + 1


@dataclass
class Jurisdiction:
    state: str
    jurisdiction_name: str
    geography_type: str
    population: int
    county_name: str = ""
    fips_state: str = ""
    fips_county: str = ""
    fips_place: str = ""
    official_website_url: str = ""

    def key(self) -> str:
        return f"{self.state}|{self.jurisdiction_name}|{self.geography_type}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "jurisdiction_name": self.jurisdiction_name,
            "geography_type": self.geography_type,
            "population": str(self.population),
            "county_name": self.county_name,
            "fips_state": self.fips_state,
            "fips_county": self.fips_county,
            "fips_place": self.fips_place,
            "official_website_url": self.official_website_url,
        }


def _parse_pop(value: str) -> int | None:
    try:
        pop = int(value)
        return pop if pop >= 0 else None
    except (TypeError, ValueError):
        return None


def _first_name_field(census_name: str) -> str:
    """'Dover city, Delaware' -> 'Dover city'; 'X township, County, ST' -> 'X township'."""
    return census_name.split(",")[0].strip()


def _statistical_exclusion(name_part: str) -> str | None:
    lower = name_part.lower()
    for pattern, bucket in _STATISTICAL_PATTERNS:
        if re.search(pattern, lower):
            return bucket
    return None


def classify_census_geography(name_part: str, census_level: str) -> tuple[str | None, str | None]:
    """
    Classify a Census geography as a local-government type or exclude it.

    Returns (geography_type, exclusion_bucket). exclusion_bucket is set when excluded.
    """
    excluded = _statistical_exclusion(name_part)
    if excluded:
        return None, excluded

    lower = name_part.lower()

    if census_level == "county":
        return "county", None

    if census_level == "place":
        if re.search(r"\bcity\b", lower):
            return "city", None
        if "township" in lower:
            return None, "other"
        if re.search(r"\btown\b", lower):
            return "town", None
        if re.search(r"\bvillage\b", lower):
            return "village", None
        if re.search(r"\bborough\b", lower):
            return "borough", None
        return None, "CDP"

    if census_level == "county subdivision":
        if "township" in lower:
            return "township", None
        if re.search(r"\btown\b", lower):
            return "town", None
        return None, "CCD"

    return None, "other"


def print_seed_summary(stats: SeedStats, total: int) -> None:
    print(f"Found {total} local-government jurisdictions in population range.")
    print("Seeded geographies:")
    for geo_type in ("city", "town", "village", "borough", "township", "county"):
        count = stats.included.get(geo_type, 0)
        if count:
            print(f"  included {geo_type}: {count}")
    print("Excluded statistical geographies:")
    for bucket in ("CDP", "CCD", "other"):
        count = stats.excluded.get(bucket, 0)
        if count:
            print(f"  {bucket}: {count}")


def _fetch_geo(client: httpx.Client, geo_for: str, state_fips: str) -> list[list[str]]:
    key = os.environ.get("CENSUS_API_KEY", "")
    url = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"
    params: dict[str, str] = {
        "get": f"NAME,{POP_VARIABLE}",
        "for": geo_for,
        "in": f"state:{state_fips}",
    }
    if key:
        params["key"] = key
    resp = client.get(url, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _county_name_map(client: httpx.Client, state_fips: str) -> dict[str, str]:
    data = _fetch_geo(client, "county:*", state_fips)
    header, *rows = data
    name_idx = header.index("NAME")
    county_idx = header.index("county")
    return {
        row[county_idx]: row[name_idx].replace(" County", "").strip()
        for row in rows
    }


def list_census_counties(state: str) -> list[tuple[str, str]]:
    """Return (fips_county, display_name) for all counties in a state via Census API."""
    state = state.upper()
    fips = STATE_FIPS.get(state)
    if not fips:
        return []
    with httpx.Client() as client:
        data = _fetch_geo(client, "county:*", fips)
    header, *rows = data
    name_i = header.index("NAME")
    county_i = header.index("county")
    results: list[tuple[str, str]] = []
    for row in rows:
        display = normalize_jurisdiction_name(row[name_i])
        if not display.lower().endswith(" county"):
            display = f"{display} County"
        results.append((row[county_i], display))
    return sorted(results, key=lambda item: item[1].lower())


def seed_jurisdictions(
    states: list[str],
    min_pop: int,
    max_pop: int,
) -> tuple[list[Jurisdiction], SeedStats]:
    results: list[Jurisdiction] = []
    stats = SeedStats()
    seen: set[str] = set()

    with httpx.Client() as client:
        for state in states:
            state = state.upper()
            fips = STATE_FIPS.get(state)
            if not fips:
                continue
            county_map = _county_name_map(client, fips)

            county_data = _fetch_geo(client, "county:*", fips)
            header, *rows = county_data
            name_i = header.index("NAME")
            pop_i = header.index(POP_VARIABLE)
            county_i = header.index("county")
            for row in rows:
                pop = _parse_pop(row[pop_i])
                if pop is None or not (min_pop <= pop <= max_pop):
                    continue
                name_part = _first_name_field(row[name_i])
                geo_type, excluded = classify_census_geography(name_part, "county")
                if excluded:
                    stats.add_excluded(excluded)
                    continue
                display = normalize_jurisdiction_name(row[name_i])
                j = Jurisdiction(
                    state=state,
                    jurisdiction_name=display,
                    geography_type=geo_type or "county",
                    population=pop,
                    county_name=display.replace(" County", "").strip(),
                    fips_state=fips,
                    fips_county=row[county_i],
                )
                if j.key() not in seen:
                    seen.add(j.key())
                    results.append(j)
                    stats.add_included(j.geography_type)

            place_data = _fetch_geo(client, "place:*", fips)
            header, *rows = place_data
            name_i = header.index("NAME")
            pop_i = header.index(POP_VARIABLE)
            place_i = header.index("place")
            has_county = "county" in header
            county_i = header.index("county") if has_county else None
            for row in rows:
                pop = _parse_pop(row[pop_i])
                if pop is None or not (min_pop <= pop <= max_pop):
                    continue
                name_part = _first_name_field(row[name_i])
                geo_type, excluded = classify_census_geography(name_part, "place")
                if excluded or not geo_type:
                    stats.add_excluded(excluded or "other")
                    continue
                display = normalize_jurisdiction_name(name_part)
                fips_county = row[county_i] if county_i is not None else ""
                county_name = county_map.get(fips_county, "") if fips_county else ""
                j = Jurisdiction(
                    state=state,
                    jurisdiction_name=display,
                    geography_type=geo_type,
                    population=pop,
                    county_name=county_name,
                    fips_state=fips,
                    fips_county=fips_county,
                    fips_place=row[place_i],
                )
                if j.key() not in seen:
                    seen.add(j.key())
                    results.append(j)
                    stats.add_included(geo_type)

            try:
                sub_data = _fetch_geo(client, "county subdivision:*", fips)
            except httpx.HTTPStatusError:
                continue
            header, *rows = sub_data
            name_i = header.index("NAME")
            pop_i = header.index(POP_VARIABLE)
            county_i = header.index("county")
            for row in rows:
                pop = _parse_pop(row[pop_i])
                if pop is None or not (min_pop <= pop <= max_pop):
                    continue
                name_part = _first_name_field(row[name_i])
                geo_type, excluded = classify_census_geography(name_part, "county subdivision")
                if excluded or not geo_type:
                    stats.add_excluded(excluded or "other")
                    continue
                display = normalize_jurisdiction_name(name_part)
                county_name = county_map.get(row[county_i], "")
                j = Jurisdiction(
                    state=state,
                    jurisdiction_name=display,
                    geography_type=geo_type,
                    population=pop,
                    county_name=county_name,
                    fips_state=fips,
                    fips_county=row[county_i],
                )
                if j.key() not in seen:
                    seen.add(j.key())
                    results.append(j)
                    stats.add_included(geo_type)

    return results, stats


def save_jurisdictions(jurisdictions: list[Jurisdiction], path=None) -> None:
    if path is None:
        from src.paths import JURISDICTIONS_CSV

        path = JURISDICTIONS_CSV
    write_csv(path, [j.to_dict() for j in jurisdictions], JURISDICTION_COLUMNS)


def load_jurisdictions(path=None) -> list[Jurisdiction]:
    from src.csv_utils import read_csv
    if path is None:
        from src.paths import JURISDICTIONS_CSV

        path = JURISDICTIONS_CSV
    rows = read_csv(path)
    return [
        Jurisdiction(
            state=r["state"],
            jurisdiction_name=r["jurisdiction_name"],
            geography_type=r["geography_type"],
            population=int(r["population"]),
            county_name=r.get("county_name", ""),
            fips_state=r.get("fips_state", ""),
            fips_county=r.get("fips_county", ""),
            fips_place=r.get("fips_place", ""),
            official_website_url=r.get("official_website_url", ""),
        )
        for r in rows
    ]
