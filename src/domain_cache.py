"""Cache successful official-site resolutions."""

from __future__ import annotations

from datetime import datetime, timezone

from src.census_seed import Jurisdiction
from src.csv_utils import read_csv, write_csv
from src.paths import DOMAIN_CACHE_CSV
from src.url_utils import normalize_url

DOMAIN_CACHE_COLUMNS = [
    "state",
    "jurisdiction_name",
    "geography_type",
    "official_domain",
    "official_url",
    "resolved_at",
    "resolver_method",
]


def _jurisdiction_key(j: Jurisdiction) -> tuple[str, str, str]:
    return (j.state.upper(), j.jurisdiction_name.strip(), j.geography_type.strip())


def load_domain_cache() -> dict[tuple[str, str, str], dict[str, str]]:
    rows = read_csv(DOMAIN_CACHE_CSV, DOMAIN_CACHE_COLUMNS)
    out: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        key = (row["state"], row["jurisdiction_name"], row["geography_type"])
        if row.get("official_url"):
            out[key] = row
    return out


def lookup_domain_cache(
    j: Jurisdiction,
    cache: dict[tuple[str, str, str], dict[str, str]] | None = None,
) -> str | None:
    data = cache if cache is not None else load_domain_cache()
    row = data.get(_jurisdiction_key(j))
    if not row:
        return None
    url = row.get("official_url", "").strip()
    return normalize_url(url) or None


def save_domain_cache_entry(
    j: Jurisdiction,
    official_url: str,
    resolver_method: str,
    cache: dict[tuple[str, str, str], dict[str, str]] | None = None,
) -> None:
    official_url = normalize_url(official_url)
    if not official_url:
        return
    from urllib.parse import urlparse

    row = {
        "state": j.state,
        "jurisdiction_name": j.jurisdiction_name,
        "geography_type": j.geography_type,
        "official_domain": urlparse(official_url).netloc.lower(),
        "official_url": official_url,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "resolver_method": resolver_method,
    }
    data = dict(cache) if cache is not None else load_domain_cache()
    data[_jurisdiction_key(j)] = row
    write_csv(DOMAIN_CACHE_CSV, list(data.values()), DOMAIN_CACHE_COLUMNS)
