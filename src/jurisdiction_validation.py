"""Strict jurisdiction/domain validation to prevent cross-state contamination."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from src.jurisdiction_utils import jurisdiction_slug, normalize_jurisdiction_name

US_STATE_ABBREVS = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC",
    }
)

# (jurisdiction keyword, target state) -> host/url fragments that indicate wrong entity
KNOWN_WRONG_DOMAIN_FRAGMENTS: tuple[tuple[tuple[str, str], tuple[str, ...]], ...] = (
    (("addison", "VT"), ("addisontx", "addison-tx", "addison.tx")),
    (("orleans", "VT"), ("orleanscountyny", "orleansny", "orleans-nyny", "orleanscounty.ny")),
    (("windsor", "VT"), ("windsor-va", "windsorva.gov", "townofwindsor.ca", "windsorca.gov")),
)


def _host_compact(host: str) -> str:
    return re.sub(r"[^a-z0-9]", "", host.lower())


def _target_state_in_host(host: str, target_state: str) -> bool:
    host = host.lower()
    target = target_state.lower()
    if target == "de":
        return ".de.us" in host or host.endswith(".de.us") or ".de.gov" in host
    compact = _host_compact(host)
    return (
        f".{target}." in host
        or host.endswith(f"{target}.gov")
        or compact.endswith(f"{target}gov")
        or f"{target}gov" in compact
    )


def host_implies_wrong_state(host: str, target_state: str) -> str | None:
    """Return another state's abbrev if the host clearly belongs elsewhere."""
    if not host:
        return None
    host_lower = host.lower()
    compact = _host_compact(host_lower)
    target = target_state.upper()

    if target != "CA" and (host_lower.endswith(".ca.gov") or ".ca.gov" in host_lower):
        return "CA"

    for abbrev in US_STATE_ABBREVS:
        if abbrev == target:
            continue
        ab = abbrev.lower()
        if _target_state_in_host(host_lower, target):
            continue
        if f".{ab}.gov" in host_lower or host_lower.endswith(f"{ab}.gov"):
            return abbrev
        if compact.endswith(f"{ab}gov"):
            return abbrev
        if f"{ab}county" in compact or f"county{ab}" in compact:
            return abbrev
    return None


def _known_wrong_domain(url: str, jurisdiction_name: str, state: str) -> str | None:
    slug = jurisdiction_slug(jurisdiction_name)
    host = urlparse(url).netloc.lower()
    combined = f"{host} {url.lower()}"
    for (keyword, st), fragments in KNOWN_WRONG_DOMAIN_FRAGMENTS:
        if st != state.upper() or keyword not in slug:
            continue
        for fragment in fragments:
            if fragment in combined:
                return fragment
    return None


def check_url_jurisdiction(url: str, jurisdiction_name: str, state: str) -> tuple[str, str]:
    """
    Return (status, note) for a single URL.
    status: matched | uncertain | mismatch
    """
    if not url or not url.strip():
        return "uncertain", ""
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if not host:
        return "uncertain", ""

    wrong_state = host_implies_wrong_state(host, state)
    if wrong_state:
        return "mismatch", f"domain implies {wrong_state}, not {state}: {url}"

    known = _known_wrong_domain(url, jurisdiction_name, state)
    if known:
        return "mismatch", f"known wrong-jurisdiction pattern ({known}): {url}"

    slug = jurisdiction_slug(jurisdiction_name)
    compact_host = _host_compact(host)
    state_lower = state.lower()

    if slug and len(slug) >= 4:
        if slug in compact_host and _target_state_in_host(host, state):
            return "matched", f"domain matches {jurisdiction_name}, {state}: {url}"
        if slug in compact_host:
            return "uncertain", ""
        if f"cityof{slug}" in compact_host and _target_state_in_host(host, state):
            return "matched", f"domain matches {jurisdiction_name}, {state}: {url}"
        if f"{slug}county" in compact_host and _target_state_in_host(host, state):
            return "matched", f"domain matches {jurisdiction_name}, {state}: {url}"

    if _target_state_in_host(host, state) and slug and slug[:5] in compact_host:
        return "matched", f"domain matches {jurisdiction_name}, {state}: {url}"

    if _target_state_in_host(host, state):
        return "uncertain", ""

    return "uncertain", ""


def check_email_jurisdiction(email: str, jurisdiction_name: str, state: str) -> tuple[str, str]:
    if not email or "@" not in email:
        return "uncertain", ""
    domain = email.split("@", 1)[1].strip()
    return check_url_jurisdiction(f"https://{domain}", jurisdiction_name, state)


def gov_domain_implies_other_municipality(
    domain: str,
    jurisdiction_name: str,
    state: str,
) -> bool:
    """
    True when a .gov/.us domain clearly belongs to another municipality in the target state.
    Used to block person-first rows tied to the wrong city's official email domain.
    """
    if not domain:
        return False
    host = domain.lower().lstrip("www.")
    if not _target_state_in_host(host, state):
        return False

    slug = jurisdiction_slug(jurisdiction_name)
    compact = _host_compact(host)
    if slug and len(slug) >= 4 and slug in compact:
        return False

    display = normalize_jurisdiction_name(jurisdiction_name).lower()
    name_parts = [
        p
        for p in re.split(r"[\s-]+", display)
        if len(p) >= 4 and p not in ("city", "town", "county", "borough", "village")
    ]
    if any(re.sub(r"[^a-z0-9]", "", p) in compact for p in name_parts):
        return False

    if "gov" not in compact and not host.endswith(".us"):
        return False

    stripped = compact
    for token in ("gov", "org", "us", state.lower(), "cityof", "townof", "www", "ci"):
        stripped = stripped.replace(token, "")
    if len(stripped) >= 5 and slug and stripped != slug and slug not in stripped:
        return True
    return False


def validate_jurisdiction_match(
    jurisdiction_name: str,
    state: str,
    official_url: str = "",
    planning_url: str = "",
    email: str = "",
    source_urls: list[str] | None = None,
) -> tuple[str, str]:
    """Aggregate URL/email checks into matched, uncertain, or mismatch."""
    checks: list[tuple[str, str]] = []

    if official_url:
        checks.append(check_url_jurisdiction(official_url, jurisdiction_name, state))
    if planning_url and planning_url != official_url:
        checks.append(check_url_jurisdiction(planning_url, jurisdiction_name, state))
    if email:
        checks.append(check_email_jurisdiction(email, jurisdiction_name, state))
    for url in source_urls or []:
        if url and url not in (official_url, planning_url):
            checks.append(check_url_jurisdiction(url, jurisdiction_name, state))

    mismatches = [note for status, note in checks if status == "mismatch" and note]
    if mismatches:
        return "mismatch", "; ".join(mismatches)

    matches = [note for status, note in checks if status == "matched" and note]
    if matches:
        return "matched", "; ".join(matches[:3])

    return "uncertain", ""


def url_is_valid_for_jurisdiction(url: str, jurisdiction_name: str, state: str) -> bool:
    """Used by search/filter: reject obvious mismatches before fetch."""
    status, _ = check_url_jurisdiction(url, jurisdiction_name, state)
    return status != "mismatch"


def _official_netloc(official_url: str | None) -> str:
    if not official_url:
        return ""
    return urlparse(official_url).netloc.lower().lstrip("www.")


def _url_on_official_domain(url: str, official_url: str | None) -> bool:
    oh = _official_netloc(official_url)
    uh = urlparse(url).netloc.lower().lstrip("www.")
    if not oh or not uh:
        return False
    return uh == oh or uh.endswith(oh.replace("www.", ""))


def _email_domain_related_to_official(email: str, official_url: str | None) -> bool:
    oh = _official_netloc(official_url)
    if not oh:
        return False
    ed = email.split("@", 1)[1].lower().lstrip("www.")
    base = oh.split(".")[0]
    return oh in ed or ed.endswith(oh) or ed.endswith(f"{base}.org")


SNIPPET_BLOCKED_HOST_FRAGMENTS: tuple[str, ...] = (
    ".edu",
    "uvmhealth",
    "chamber",
    "vtrural",
    "cdfi.org",
    "issuu.com",
    "facebook.com",
    "linkedin.com",
    "propublica",
    "newspaper",
    "journal.com",
)


def _snippet_source_is_blocked_third_party(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    combined = f"{host} {url.lower()}"
    return any(fragment in combined for fragment in SNIPPET_BLOCKED_HOST_FRAGMENTS)


def search_snippet_working_eligible(
    email: str,
    email_source_url: str,
    jurisdiction_name: str,
    state: str,
    official_url: str | None = "",
) -> tuple[bool, str]:
    """
    Search-snippet rows enter working CSV only with official/local-government association.
    """
    if not email or not email_source_url:
        return False, "missing email or source url"

    src_status, src_note = check_url_jurisdiction(
        email_source_url, jurisdiction_name, state
    )
    email_status, email_note = check_email_jurisdiction(
        email, jurisdiction_name, state
    )

    if src_status == "mismatch":
        return False, src_note
    if email_status == "mismatch":
        return False, email_note

    email_dom = email.split("@", 1)[1].lower()
    if gov_domain_implies_other_municipality(email_dom, jurisdiction_name, state):
        return False, f"email domain is another municipality: {email_dom}"

    if _url_on_official_domain(email_source_url, official_url):
        return True, src_note or "source on official domain"

    if src_status == "matched":
        return True, src_note

    if email_status == "matched":
        return True, email_note

    if _email_domain_related_to_official(email, official_url):
        return True, "email domain matches official site"

    slug = jurisdiction_slug(jurisdiction_name)
    src_host = urlparse(email_source_url).netloc.lower()
    email_compact = _host_compact(email_dom)
    src_compact = _host_compact(src_host)
    if (
        slug
        and len(slug) >= 4
        and slug in src_compact
        and _target_state_in_host(src_host, state)
    ):
        return True, "source domain matches jurisdiction"

    if (
        slug
        and len(slug) >= 4
        and slug in email_compact
        and _target_state_in_host(email_dom, state)
    ):
        return True, "email domain matches jurisdiction"

    if _snippet_source_is_blocked_third_party(email_source_url):
        return False, f"third-party snippet source: {email_source_url}"

    if (".gov" in src_host or src_host.endswith(".us")) and src_status != "matched":
        if not slug or slug not in src_compact:
            return False, f"federal or non-local snippet source: {email_source_url}"

    if (email_dom.endswith(".gov") or email_dom.endswith(".us")) and email_status != "matched":
        if not slug or slug not in email_compact:
            return False, f"federal or non-local email domain: {email}"

    return False, f"non-official snippet source: {email_source_url}"
