"""Role-family titles, query pools, and page-ranking keywords."""

from __future__ import annotations

import re
# Valid target titles (case-insensitive substring match)
TITLE_ALLOWLIST: tuple[str, ...] = (
    "Director of Planning",
    "Planning Director",
    "Community Development Director",
    "Director of Community Development",
    "Development Services Director",
    "Planning Manager",
    "Long Range Planning Manager",
    "Planning & Zoning Director",
    "Planning and Zoning Director",
    "Growth Management Director",
    "Director of Land Use",
    "Land Use Director",
    "County Planning Director",
    "County Planner",
    "Town Planner",
    "City Planner",
    "Planning Administrator",
    "Zoning Administrator",
    "Principal Planner",
    "Senior Planner",
    "Community Development Manager",
    "Development Review Manager",
)

# Rank tiers: lower number = higher priority
TITLE_RANK_TIER: dict[str, int] = {
    "director": 1,
    "manager": 2,
    "administrator": 3,
    "planner": 3,
}

PAGE_RELEVANCE_KEYWORDS: tuple[str, ...] = (
    "planning",
    "community development",
    "land use",
    "growth management",
    "development services",
    "planning & zoning",
    "planning and zoning",
    "zoning",
)

URL_RANK_KEYWORDS: tuple[str, ...] = (
    "staff",
    "directory",
    "department",
    "planning",
    "community",
    "development",
    "land-use",
    "landuse",
    "zoning",
)

DOMAIN_PROBE_PATHS: tuple[str, ...] = (
    "/planning",
    "/community-development",
    "/communitydevelopment",
    "/land-use",
    "/growth-management",
    "/development-services",
    "/planning-zoning",
    "/zoning",
    "/staff",
    "/directory",
    "/departments",
)

PDF_LINK_KEYWORDS: tuple[str, ...] = (
    "staff",
    "directory",
    "organizational",
    "org chart",
    "planning commission",
    "agenda",
    "packet",
    "department",
)

MUNICIPALITY_TIER1_QUERIES: tuple[str, ...] = (
    '"{j}" "{s}" planning department site:.gov',
    '"{j}" "{s}" planning staff site:.gov',
)

MUNICIPALITY_TIER2_QUERIES: tuple[str, ...] = (
    '"{j}" "{s}" community development department site:.gov',
    '"{j}" "{s}" planning director site:.gov',
    '"{j}" "{s}" director of planning site:.gov',
    '"{j}" "{s}" community development director site:.gov',
    '"{j}" "{s}" planning manager site:.gov',
    '"{j}" "{s}" development services director site:.gov',
    '"{j}" "{s}" planning and zoning director site:.gov',
    '"{j}" "{s}" land use director site:.gov',
    '"{j}" "{s}" growth management director site:.gov',
    '"{j}" "{s}" planning administrator site:.gov',
)

COUNTY_TIER1_QUERIES: tuple[str, ...] = (
    '"{c}" county planning department site:.gov',
    '"{c}" county planning staff site:.gov',
)

COUNTY_TIER2_QUERIES: tuple[str, ...] = (
    '"{c}" county planning director site:.gov',
    '"{c}" county planner site:.gov',
    '"{c}" county community development director site:.gov',
    '"{c}" county land use director site:.gov',
    '"{c}" county growth management director site:.gov',
    '"{c}" county planning and zoning director site:.gov',
)

MAX_SEARCH_QUERIES = 5
MAX_FAST_SEARCH_QUERIES = 3
MAX_FAST_PAGES = 1
MAX_PERSON_SEARCH_QUERIES = 6
MAX_PERSON_EMAIL_QUERIES = 5

FAST_MUNICIPALITY_QUERIES: tuple[str, ...] = (
    '"{j}" "{s}" "planning director" email',
    '"{j}" "{s}" "community development director" email',
    '"{j}" "{s}" "planning staff" email',
)

FAST_COUNTY_QUERIES: tuple[str, ...] = (
    '"{c}" "{s}" "planning director" email',
    '"{c}" "{s}" "county planner" email',
    '"{c}" "{s}" "planning staff" email',
)

PERSON_MUNICIPALITY_QUERIES: tuple[str, ...] = (
    '"{j}" "{s}" "Planning Director"',
    '"{j}" "{s}" "Director of Planning"',
    '"{j}" "{s}" "Community Development Director"',
    '"{j}" "{s}" "Development Services Director"',
    '"{j}" "{s}" "Planning Manager"',
    '"{j}" "{s}" "Town Planner"',
    '"{j}" "{s}" "Planning Administrator"',
)

PERSON_COUNTY_QUERIES: tuple[str, ...] = (
    '"{c}" "{s}" "County Planning Director"',
    '"{c}" "{s}" "Planning Director"',
    '"{c}" "{s}" "Community Development Director"',
    '"{c}" "{s}" "Land Use Director"',
    '"{c}" "{s}" "County Planner"',
    '"{c}" "{s}" "Planning and Zoning Director"',
)


def title_rank(title: str) -> int:
    """Return rank tier for a title (1=director, 2=manager, 3=admin/planner)."""
    lower = title.lower()
    if "director" in lower:
        return TITLE_RANK_TIER["director"]
    if "manager" in lower:
        return TITLE_RANK_TIER["manager"]
    if "administrator" in lower or "planner" in lower:
        return TITLE_RANK_TIER["administrator"]
    return 99


def matches_allowlisted_title(text: str) -> str | None:
    """Return the first matching allowlisted title substring, or None."""
    lower = text.lower()
    # Prefer longer/more specific titles first
    for title in sorted(TITLE_ALLOWLIST, key=len, reverse=True):
        if title.lower() in lower:
            return title
    return None


def municipality_queries(jurisdiction: str, state: str) -> list[str]:
    """Build tiered search query list for municipalities."""
    j, s = jurisdiction, state
    queries = [q.format(j=j, s=s) for q in MUNICIPALITY_TIER1_QUERIES]
    queries.extend(q.format(j=j, s=s) for q in MUNICIPALITY_TIER2_QUERIES)
    return queries


def county_queries(county_name: str) -> list[str]:
    """Build tiered search query list for counties."""
    from src.jurisdiction_utils import normalize_jurisdiction_name

    display = normalize_jurisdiction_name(county_name)
    c = display.replace(" County", "").replace(" county", "").strip()
    queries = [q.format(c=c) for q in COUNTY_TIER1_QUERIES]
    queries.extend(q.format(c=c) for q in COUNTY_TIER2_QUERIES)
    return queries


def fast_municipality_queries(jurisdiction: str, state: str) -> list[str]:
    j, s = jurisdiction, state
    return [q.format(j=j, s=s) for q in FAST_MUNICIPALITY_QUERIES]


def fast_county_queries(county_name: str, state: str) -> list[str]:
    from src.jurisdiction_utils import normalize_jurisdiction_name

    display = normalize_jurisdiction_name(county_name)
    c = display.replace(" County", "").replace(" county", "").strip()
    return [q.format(c=c, s=state) for q in FAST_COUNTY_QUERIES]


def person_name_queries(
    jurisdiction: str,
    state: str,
    geography_type: str,
    county: str,
) -> list[str]:
    if geography_type == "county":
        c = jurisdiction.replace(" County", "").strip()
        return [q.format(c=c, s=state) for q in PERSON_COUNTY_QUERIES]
    return [q.format(j=jurisdiction, s=state) for q in PERSON_MUNICIPALITY_QUERIES]


def person_email_queries(
    name: str,
    title: str,
    jurisdiction: str,
    state: str,
    official_domain: str,
) -> list[str]:
    domain_guess = ""
    if official_domain:
        lp = re.sub(r"[^a-z]", "", name.lower().split()[0] if name.split() else "")
        domain_guess = f"{lp}@{official_domain}"
    queries = []
    if official_domain:
        queries.append(f'"{name}" site:{official_domain}')
    queries.extend(
        [
            f'"{name}" "{jurisdiction}" email',
            f'"{name}" "{jurisdiction}" "{title}" email',
            f'"{name}" "{state}" "{title}" contact',
        ]
    )
    if official_domain:
        queries.append(f'"{name}" "{official_domain}"')
    if domain_guess:
        queries.append(f'"{name}" "{domain_guess}"')
    return queries
