"""Staff directory link discovery and crawl helpers for directory harvest."""

from __future__ import annotations

from urllib.parse import urlparse

from src.fetch_pages import extract_links, same_domain
from src.url_utils import normalize_url

HIGH_PRIORITY_PATH_KEYWORDS: tuple[str, ...] = (
    "planning",
    "community-development",
    "communitydevelopment",
    "development-services",
    "developmentservices",
    "planning-zoning",
    "planning_and_zoning",
    "building-planning",
    "planning-and-zoning",
)

STAFF_PATH_KEYWORDS: tuple[str, ...] = (
    "staff",
    "directory",
    "contact",
    "employee",
    "department",
    "zoning",
)

LOW_PRIORITY_PATH_KEYWORDS: tuple[str, ...] = (
    "administration",
    "building",
    "contact-us",
    "contactus",
)

PLANNING_POSITIVE_FRAGMENTS: tuple[str, ...] = (
    "planning",
    "community-development",
    "communitydevelopment",
    "development-services",
    "zoning",
    "land-use",
    "landuse",
)

SKIP_CRAWL_FRAGMENTS: tuple[str, ...] = (
    ".pdf",
    ".doc",
    ".xls",
    "/agenda",
    "/minutes",
    "/calendar",
    "/parks",
    "/police",
    "/fire",
    "/utilities",
    "/jobs",
    "/employment",
    "/procurement",
    "/rfp",
    "/news",
    "/events",
    "/facebook",
    "/twitter",
    "/instagram",
    "/youtube",
    "/social",
    "javascript:",
    "mailto:",
)

DEPRIORITIZE_FRAGMENTS: tuple[str, ...] = (
    "/admin",
    "/administration",
    "/building",
    "/permits",
    "/contact",
    "/homepage",
)


def official_netloc(official_url: str) -> str:
    return urlparse(official_url).netloc.lower()


def is_same_official_site(url: str, official_url: str) -> bool:
    if not url or not official_url:
        return False
    return same_domain(url, official_url)


def should_skip_crawl_url(url: str) -> bool:
    lower = url.lower()
    if any(pos in lower for pos in PLANNING_POSITIVE_FRAGMENTS):
        return False
    if any(skip in lower for skip in SKIP_CRAWL_FRAGMENTS):
        return True
    return False


def score_staff_link(url: str, link_text: str) -> int:
    combined = f"{url} {link_text}".lower()
    if should_skip_crawl_url(url):
        return 0
    score = 0
    for kw in HIGH_PRIORITY_PATH_KEYWORDS:
        if kw in combined:
            score += 80
    for kw in STAFF_PATH_KEYWORDS:
        if kw in combined:
            score += 25
    if "directory.aspx" in combined or "staff-directory" in combined:
        score += 50
    if any(kw in combined for kw in HIGH_PRIORITY_PATH_KEYWORDS) and "staff" in combined:
        score += 30
    for kw in LOW_PRIORITY_PATH_KEYWORDS:
        if kw in combined:
            score += 8
    for frag in DEPRIORITIZE_FRAGMENTS:
        if frag in combined and score < 40:
            score = max(5, score - 15)
    return score


def discover_internal_staff_urls(
    html: str,
    page_url: str,
    official_url: str,
) -> list[tuple[str, int]]:
    """Return same-domain links scored for staff/planning relevance."""
    if not html or not official_url:
        return []
    results: list[tuple[str, int]] = []
    seen: set[str] = set()
    for url, text in extract_links(html, page_url):
        if should_skip_crawl_url(url):
            continue
        if not is_same_official_site(url, official_url):
            continue
        normalized = normalize_url(url)
        if not normalized or normalized in seen:
            continue
        score = score_staff_link(normalized, text)
        if score <= 0:
            continue
        seen.add(normalized)
        results.append((normalized, score))
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:15]


def classify_page_url(url: str) -> str:
    lower = url.lower()
    if any(kw in lower for kw in ("directory", "staff", "employee")):
        return "directory"
    if any(kw in lower for kw in HIGH_PRIORITY_PATH_KEYWORDS):
        return "planning"
    return "other"


def url_crawl_kind(url: str, official_url: str) -> str:
    kind = classify_page_url(url)
    if kind == "directory":
        return "directory"
    if kind == "planning":
        return "planning"
    lower = url.lower()
    if any(
        frag in lower
        for frag in ("/staff/", "/people/", "/employee/", "/profile", "/bio/", "/team/")
    ):
        return "profile"
    if official_url and normalize_url(url) == normalize_url(official_url):
        return "homepage"
    return "other"


def crawl_priority(url: str, link_text: str, official_url: str, *, kind: str) -> int:
    score = score_staff_link(url, link_text)
    if kind == "planning":
        return max(score, 120)
    if kind == "directory":
        return max(score, 100)
    if kind == "profile":
        return max(score, 280)
    if kind == "homepage":
        return 60
    if score > 0:
        return score
    if kind == "other":
        return 10
    return 0
