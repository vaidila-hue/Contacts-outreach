"""Extract planning contacts from HTML and plain text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag

from src.fetch_pages import safe_soup

from src.extract_emails import (
    classify_email,
    extract_emails_from_text,
    infer_name_from_email,
    is_generic_email,
    normalize_email,
)
from src.role_config import matches_allowlisted_title, title_rank


@dataclass
class ContactCandidate:
    name: str
    title: str
    email: str
    source_url: str
    paired_with_name: bool = False

    @property
    def rank(self) -> int:
        return title_rank(self.title)


@dataclass
class ProfileFollowUp:
    name: str
    title: str
    profile_url: str
    listing_url: str


PROFILE_LINK_TEXT = re.compile(
    r"\b(profile|view profile|contact|bio|more info|details|read more)\b",
    re.I,
)
GENERIC_LINK_TEXT = frozenset(
    {"email", "e-mail", "contact", "send email", "mail", "view", "click here"}
)


PLANNING_CONTEXT_WORDS = ("planning", "community development", "land use", "zoning", "development")

EXTRACTION_TEXT_KEYWORDS: tuple[str, ...] = (
    "planning",
    "planner",
    "zoning",
    "community development",
    "development services",
    "staff",
    "directory",
    "contact",
    "email",
    "@",
)

ALWAYS_EXTRACT_PAGE_KINDS: frozenset[str] = frozenset(
    {"planning", "directory", "homepage", "probe", "manual", "profile"}
)


def page_warrants_extraction(html: str, url: str, *, page_kind: str) -> bool:
    """Quick text scan before expensive DOM extraction."""
    if page_kind in ALWAYS_EXTRACT_PAGE_KINDS:
        return True
    sample = (html or "")[:60000].lower()
    return any(kw in sample for kw in EXTRACTION_TEXT_KEYWORDS)


def is_high_confidence_contact(candidate: ContactCandidate, official_url: str) -> bool:
    """Official-site direct email with allowlisted planning leadership title."""
    if classify_email(candidate.email, candidate.name, candidate.paired_with_name) != "direct":
        return False
    if not matches_allowlisted_title(candidate.title):
        return False
    from src.staff_discovery import is_same_official_site

    return is_same_official_site(candidate.source_url, official_url)


def _page_planning_context(html: str) -> str:
    lower = (html or "")[:8000].lower()
    return lower


def _resolve_staff_title(line: str, lines: list[str], page_context: str) -> str | None:
    """Resolve allowlisted title from a line, with planning-page context for short titles."""
    match = matches_allowlisted_title(line)
    if match:
        return line if match.lower() in line.lower() and len(line) < 100 else match
    lower = line.lower().strip()
    block_text = " ".join(lines).lower()
    ctx = page_context + " " + block_text
    if "director" in lower and any(w in ctx for w in PLANNING_CONTEXT_WORDS):
        if "assistant" in lower or "deputy" in lower:
            return "Assistant Planning Director"
        return "Planning Director"
    if "city planner" in lower or lower.strip("- ") == "planner":
        return "City Planner"
    if "zoning officer" in lower or "zoning administrator" in lower:
        return "Zoning Officer"
    return None


def _lines_before_mailto(anchor: Tag) -> list[str]:
    """Collect text lines from siblings immediately before this mailto (stop at prior mailto)."""
    lines: list[str] = []
    for sib in anchor.previous_siblings:
        if getattr(sib, "name", None) == "a":
            href = sib.get("href", "")
            if href.lower().startswith("mailto:"):
                break
        if hasattr(sib, "get_text"):
            chunk = sib.get_text("\n", strip=True)
            if chunk:
                for ln in chunk.splitlines():
                    ln = ln.strip()
                    if ln:
                        lines.insert(0, ln)
        elif isinstance(sib, NavigableString):
            text = str(sib).strip()
            if text:
                lines.insert(0, text)
    return lines


def _container_lines(container: Tag, limit: int = 12) -> list[str]:
    text = container.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[:limit]


def _name_title_from_lines(lines: list[str], page_context: str) -> tuple[str, str]:
    title = ""
    name = ""
    for line in lines:
        resolved = _resolve_staff_title(line, lines, page_context)
        if resolved and not title:
            title = resolved
    for line in lines:
        if _looks_like_name(line):
            name = line
            break
    if not name:
        for line in lines:
            m = NAME_RE.search(line)
            if m:
                name = m.group(1)
                break
    return name, title


def _extract_mailto_from_anchor(
    a: Tag, source_url: str, page_context: str
) -> ContactCandidate | None:
    href = a.get("href", "")
    if not href.lower().startswith("mailto:"):
        return None
    email = normalize_email(href.replace("mailto:", "").split("?")[0])
    if is_generic_email(email):
        return None
    link_name = a.get_text(" ", strip=True)
    prior_lines = _lines_before_mailto(a)
    parent_lines: list[str] = []
    if not prior_lines:
        parent = a.parent
        for _ in range(4):
            if parent is None or parent.name in ("body", "html", "[document]"):
                break
            parent_lines = _container_lines(parent, 10) + parent_lines
            parent = parent.parent
    # Prefer sibling lines before this mailto; shared parent containers mix staff entries.
    local_lines = prior_lines if prior_lines else parent_lines

    name = link_name if _looks_like_name(link_name) else ""
    title = ""
    for line in reversed(local_lines):
        resolved = _resolve_staff_title(line, local_lines, page_context)
        if resolved:
            title = resolved
            break
    if not name:
        for line in prior_lines:
            if _looks_like_name(line):
                name = line
                break
    if not name:
        for line in reversed(local_lines):
            if _looks_like_name(line):
                name = line
                break
    if not name:
        name = infer_name_from_email(email)
    if classify_email(email, name, paired_with_name=bool(name and title)) != "direct":
        if classify_email(email, name, paired_with_name=True) != "direct":
            return None
    if not title:
        return None
    return ContactCandidate(name, title, email, source_url, True)


def _profile_url_in_element(el: Tag, source_url: str, official_netloc: str) -> str | None:
    from urllib.parse import urljoin, urlparse

    for a in el.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            continue
        url = urljoin(source_url, href)
        if urlparse(url).netloc.lower() != official_netloc:
            continue
        text = a.get_text(" ", strip=True)
        lower = text.lower()
        if PROFILE_LINK_TEXT.search(lower):
            return url.split("#")[0]
        if _looks_like_name(text) and len(text) < 50:
            return url.split("#")[0]
        if lower in GENERIC_LINK_TEXT and len(href) > 2:
            return url.split("#")[0]
    return None


def _extract_contact_blocks(
    el: Tag,
    source_url: str,
    page_context: str,
    official_netloc: str,
) -> tuple[list[ContactCandidate], list[ProfileFollowUp]]:
    candidates: list[ContactCandidate] = []
    profiles: list[ProfileFollowUp] = []
    tag_names = ["li", "tr", "div", "article", "section", "td"]
    seen_blocks: set[int] = set()
    for tag in tag_names:
        for block in el.find_all(tag):
            bid = id(block)
            if bid in seen_blocks:
                continue
            lines = _container_lines(block, 8)
            if not lines:
                continue
            block_text = "\n".join(lines)
            title_match = matches_allowlisted_title(block_text)
            if not title_match:
                continue
            if len(block_text) > 600:
                continue
            if len(block.find_all("a", href=lambda h: h and h.lower().startswith("mailto:"))) > 1:
                continue
            seen_blocks.add(bid)
            name, title = _name_title_from_lines(lines, page_context)
            if not title:
                title = title_match
            email = ""
            for a in block.find_all("a", href=True):
                if a["href"].lower().startswith("mailto:"):
                    cand = _extract_mailto_from_anchor(a, source_url, page_context)
                    if cand:
                        candidates.append(cand)
                        email = cand.email
                    break
            if not email:
                for line in lines:
                    for em in extract_emails_from_text(line):
                        if is_generic_email(em):
                            continue
                        if classify_email(em, name, paired_with_name=True) == "direct":
                            email = em
                            break
                    if email:
                        break
            if email and name and title:
                candidates.append(
                    ContactCandidate(name, title, email, source_url, True)
                )
            elif name and title and official_netloc:
                profile = _profile_url_in_element(block, source_url, official_netloc)
                if profile and profile.rstrip("/") != source_url.rstrip("/"):
                    profiles.append(
                        ProfileFollowUp(name, title, profile, source_url)
                    )
    return candidates, profiles


def extract_profile_followups(
    html: str, source_url: str, official_url: str
) -> list[ProfileFollowUp]:
    soup = safe_soup(html)
    if soup is None:
        return []
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    from src.staff_discovery import official_netloc

    netloc = official_netloc(official_url)
    page_context = _page_planning_context(html)
    _, profiles = _extract_contact_blocks(
        soup.body or soup, source_url, page_context, netloc
    )
    seen: set[str] = set()
    unique: list[ProfileFollowUp] = []
    for p in profiles:
        key = p.profile_url.rstrip("/")
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def count_mailto_links(html: str) -> int:
    soup = safe_soup(html)
    if soup is None:
        return 0
    return len(soup.find_all("a", href=lambda h: h and h.lower().startswith("mailto:")))


NAME_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z\-']+(?:\s+[A-Z][a-z\-']+)?)\b"
)


def _looks_like_name(text: str) -> bool:
    text = text.strip()
    if len(text) < 3 or len(text) > 60:
        return False
    if any(c.isdigit() for c in text):
        return False
    words = text.split()
    if len(words) < 2:
        return False
    skip = {"department", "planning", "director", "phone", "email", "fax", "office", "contact", "information"}
    if any(w.lower() in skip for w in words):
        return False
    if "contact information" in text.lower():
        return False
    return True


def _extract_from_block(text: str, source_url: str) -> list[ContactCandidate]:
    candidates: list[ContactCandidate] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        title_match = matches_allowlisted_title(line)
        if not title_match:
            continue
        name = ""
        email = ""
        paired = False
        # Prefer email on same line, then following lines (staff-directory layout)
        for em in extract_emails_from_text(line):
            if is_generic_email(em):
                continue
            if classify_email(em, paired_with_name=True) == "direct":
                email = em
                paired = True
                break
        if not email:
            for j in range(i + 1, min(len(lines), i + 4)):
                for em in extract_emails_from_text(lines[j]):
                    if is_generic_email(em):
                        continue
                    if classify_email(em, paired_with_name=True) == "direct":
                        email = em
                        paired = True
                        break
                if email:
                    break
        context_lines = lines[max(0, i - 2) : min(len(lines), i + 4)]
        context = " ".join(context_lines)
        # Name usually on line immediately after title (not before)
        if i + 1 < len(lines) and _looks_like_name(lines[i + 1]):
            name = lines[i + 1]
        elif not name:
            for j in range(max(0, i - 2), i):
                if _looks_like_name(lines[j]):
                    name = lines[j]
                    break
        if not name:
            m = NAME_RE.search(context)
            if m:
                name = m.group(1)
        if not name and email:
            name = infer_name_from_email(email)
        display_title = line if title_match.lower() in line.lower() and len(line) < 100 else title_match
        if email:
            candidates.append(
                ContactCandidate(name, display_title, email, source_url, paired)
            )
    return candidates


def _extract_from_html_element(el: Tag, source_url: str, page_context: str = "") -> list[ContactCandidate]:
    candidates: list[ContactCandidate] = []
    candidates.extend(_extract_mailto_staff_entries(el, source_url, page_context))
    text = el.get_text("\n", strip=True)
    has_mailto = bool(el.find_all("a", href=lambda h: h and h.lower().startswith("mailto:")))

    for tr in el.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        row_text = " | ".join(cells)
        title_match = matches_allowlisted_title(row_text)
        if not title_match:
            continue
        email = ""
        name = ""
        for a in tr.find_all("a", href=True):
            if a["href"].lower().startswith("mailto:"):
                email = normalize_email(a["href"].replace("mailto:", "").split("?")[0])
                break
        for cell in cells:
            if not email:
                for em in extract_emails_from_text(cell):
                    if classify_email(em, paired_with_name=True) == "direct":
                        email = em
                        break
            if _looks_like_name(cell) and not matches_allowlisted_title(cell):
                name = cell
        if name and email:
            candidates.append(
                ContactCandidate(name, title_match, email, source_url, True)
            )

    if not has_mailto:
        candidates.extend(_extract_from_block(text, source_url))
    return candidates


def _extract_mailto_staff_entries(
    el: Tag, source_url: str, page_context: str
) -> list[ContactCandidate]:
    candidates: list[ContactCandidate] = []
    for a in el.find_all("a", href=True):
        cand = _extract_mailto_from_anchor(a, source_url, page_context)
        if cand:
            candidates.append(cand)
    return candidates


def extract_contacts_from_html(
    html: str, source_url: str, official_url: str = ""
) -> list[ContactCandidate]:
    soup = safe_soup(html)
    if soup is None:
        return []
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    page_context = _page_planning_context(html)
    candidates: list[ContactCandidate] = []
    official_netloc = ""
    if official_url:
        from src.staff_discovery import official_netloc as _netloc

        official_netloc = _netloc(official_url)
    root = soup.body or soup
    for el in root.find_all(["table", "ul", "ol", "div", "section", "article", "main"]):
        candidates.extend(_extract_from_html_element(el, source_url, page_context))
        if official_netloc:
            block_cands, _ = _extract_contact_blocks(
                el, source_url, page_context, official_netloc
            )
            candidates.extend(block_cands)
    if not candidates:
        candidates.extend(_extract_from_html_element(root, source_url, page_context))
        if official_netloc:
            block_cands, _ = _extract_contact_blocks(
                root, source_url, page_context, official_netloc
            )
            candidates.extend(block_cands)
    return _dedupe_candidates(candidates)


def extract_contacts_from_text(text: str, source_url: str) -> list[ContactCandidate]:
    return _dedupe_candidates(_extract_from_block(text, source_url))


def _title_sort_key(title: str) -> tuple[int, int]:
    """Lower sort key = higher priority."""
    rank = title_rank(title)
    lower = title.lower()
    sub = 0
    if rank == 1:
        if "assistant" in lower or "deputy" in lower:
            sub = 5
        elif "planning director" in lower or "director of planning" in lower:
            sub = 0
        elif "planning" in lower:
            sub = 1
        elif "community development" in lower:
            sub = 2
        else:
            sub = 3
    return (rank, sub)


def _candidate_quality(c: ContactCandidate) -> tuple[tuple[int, int], int, int]:
    """Lower is better."""
    name_penalty = 1 if "contact information" in c.name.lower() else 0
    return (_title_sort_key(c.title), name_penalty, len(c.name))


def _dedupe_candidates(candidates: list[ContactCandidate]) -> list[ContactCandidate]:
    by_email: dict[str, ContactCandidate] = {}
    for c in candidates:
        if classify_email(c.email, c.name, c.paired_with_name) != "direct":
            continue
        existing = by_email.get(c.email)
        if existing is None or _candidate_quality(c) < _candidate_quality(existing):
            by_email[c.email] = c
    return list(by_email.values())


def select_best_contact(candidates: list[ContactCandidate]) -> ContactCandidate | None:
    """Pick highest-ranking contact with a valid direct email."""
    valid: list[ContactCandidate] = []
    for c in candidates:
        kind = classify_email(c.email, c.name, c.paired_with_name)
        if kind == "direct":
            valid.append(c)
    if not valid:
        return None
    valid.sort(key=lambda c: (_title_sort_key(c.title), c.name))
    return valid[0]
