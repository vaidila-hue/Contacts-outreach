"""Jurisdiction name normalization and official-site validation."""

from __future__ import annotations

import re
from urllib.parse import urlparse

BLOCKED_OFFICIAL_HOST_FRAGMENTS: tuple[str, ...] = (
    "ri.gov/towns",
    "ri.gov/links",
    "//www.ri.gov/",
    "dot.ri.gov",
    "catalog.sos.ri.gov",
    "opengov.sos.ri.gov",
    "npgallery.nps.gov",
    "rilegislature.gov",
)


def is_parking_or_error_page(html: str) -> bool:
    """Reject placeholder/parking/WAF/error pages mistaken for official sites."""
    if not html or len(html) < 500:
        return True
    lower = html.lower()
    if "403 - forbidden" in lower and len(html) < 2000:
        return True
    if "just a moment" in lower and "enable javascript" in lower:
        return True
    return False


def official_homepage_from_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"


def normalize_jurisdiction_name(name: str) -> str:
    """Census 'Bristol County, Rhode Island' -> 'Bristol County'; 'Cranston city' -> 'Cranston'."""
    if "," in name:
        name = name.split(",")[0].strip()
    name = re.sub(
        r"\s+(city|town|village|borough|township)$",
        "",
        name,
        flags=re.I,
    )
    return name.strip()


def jurisdiction_slug(name: str) -> str:
    base = normalize_jurisdiction_name(name)
    base = re.sub(r"\s+county$", "", base, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", base.lower())


def is_blocked_official_url(url: str) -> bool:
    lower = url.lower()
    return any(fragment in lower for fragment in BLOCKED_OFFICIAL_HOST_FRAGMENTS)


def url_matches_state(url: str, state: str) -> bool:
    """Reject obvious out-of-state domains (e.g. bristolva.gov when seeding RI)."""
    from src.jurisdiction_validation import host_implies_wrong_state

    host = urlparse(url).netloc.lower()
    if host_implies_wrong_state(host, state):
        return False
    sl = state.lower()
    wrong_by_state: dict[str, tuple[str, ...]] = {
        "ri": ("bristolva", "newportbeach", ".va.gov", "ca.gov", "virginia.gov"),
        "de": (".ri.gov", "bristolva"),
        "vt": ("addisontx", "orleanscountyny", "windsor-va", "townofwindsor.ca"),
    }
    for bad in wrong_by_state.get(sl, ()):
        if bad in host:
            return False
    if f".{sl}." in host or host.endswith(f"{sl}.gov") or f"{sl}.gov" in host:
        return True
    if sl in host and (host.endswith(".gov") or host.endswith(".org") or host.endswith(".us")):
        return True
    if host.endswith(".gov") or host.endswith(".org"):
        return True
    return False


def url_matches_jurisdiction(url: str, jurisdiction_name: str, state: str) -> bool:
    """Heuristic: domain or path should relate to the jurisdiction slug and state."""
    from src.jurisdiction_validation import url_is_valid_for_jurisdiction

    if not url_is_valid_for_jurisdiction(url, jurisdiction_name, state):
        return False
    if not url_matches_state(url, state):
        return False
    slug = jurisdiction_slug(jurisdiction_name)
    if not slug or len(slug) < 3:
        return True
    lower = url.lower()
    state_lower = state.lower()
    if slug in lower:
        return True
    if f"{slug}{state_lower}" in lower:
        return True
    if f"{slug}county" in lower:
        return True
    if f"cityof{slug}" in lower.replace(".", ""):
        return True
    # Require state marker for ambiguous county/city names on generic .gov hosts
    if "county" in normalize_jurisdiction_name(jurisdiction_name).lower():
        from src.jurisdiction_validation import _target_state_in_host

        host = urlparse(url).netloc
        if not _target_state_in_host(host, state) and len(slug) <= 8:
            return False
    return False


def filter_urls_for_jurisdiction(
    urls: list[str], jurisdiction_name: str, state: str
) -> list[str]:
    return [
        u
        for u in urls
        if url_matches_jurisdiction(u, jurisdiction_name, state)
    ]
