"""Extract planning staff names/titles from search snippets and page text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.extract_contacts import NAME_RE, _looks_like_name
from src.role_config import matches_allowlisted_title, title_rank


@dataclass
class PersonCandidate:
    name: str
    title: str
    candidate_source_url: str
    snippet: str = ""

    @property
    def rank(self) -> int:
        return title_rank(self.title)


def _clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name.strip())
    name = re.sub(r"[,|–\-]\s*$", "", name)
    return name.strip()


def extract_person_from_text(text: str, source_url: str = "") -> list[PersonCandidate]:
    """Extract name/title pairs from combined title+snippet/body text."""
    if not text:
        return []
    found: list[PersonCandidate] = []
    seen: set[tuple[str, str]] = set()

    title = matches_allowlisted_title(text)
    if title:
        for pattern in (
            rf"({NAME_RE.pattern})\s*[,|\-–]\s*{re.escape(title)}",
            rf"{re.escape(title)}\s*[,:\-–]\s*({NAME_RE.pattern})",
            rf"({NAME_RE.pattern})\s+{re.escape(title)}",
        ):
            for m in re.finditer(pattern, text, re.I):
                name = _clean_name(m.group(1))
                if _looks_like_name(name):
                    key = (name.lower(), title.lower())
                    if key not in seen:
                        seen.add(key)
                        found.append(PersonCandidate(name, title, source_url, text[:200]))

    lines = [ln.strip() for ln in re.split(r"[\n|•]", text) if ln.strip()]
    for i, line in enumerate(lines):
        title_match = matches_allowlisted_title(line)
        if not title_match:
            continue
        display_title = line if len(line) < 100 else title_match
        name = ""
        if i + 1 < len(lines) and _looks_like_name(lines[i + 1]):
            name = lines[i + 1]
        elif i > 0 and _looks_like_name(lines[i - 1]):
            name = lines[i - 1]
        else:
            ctx = " ".join(lines[max(0, i - 1) : i + 2])
            m = NAME_RE.search(ctx)
            if m:
                name = m.group(1)
        name = _clean_name(name)
        if name and _looks_like_name(name):
            key = (name.lower(), display_title.lower())
            if key not in seen:
                seen.add(key)
                found.append(PersonCandidate(name, display_title, source_url, text[:200]))
    return found


def extract_person_from_search_hit(hit) -> PersonCandidate | None:
    combined = f"{hit.title}. {hit.snippet}"
    people = extract_person_from_text(combined, hit.url)
    if not people:
        return None
    people.sort(key=lambda p: (p.rank, p.name))
    return people[0]


def rank_person_candidates(candidates: list[PersonCandidate]) -> list[PersonCandidate]:
    unique: dict[tuple[str, str], PersonCandidate] = {}
    for p in candidates:
        key = (p.name.lower(), p.title.lower())
        existing = unique.get(key)
        if existing is None or p.rank < existing.rank:
            unique[key] = p
    return sorted(unique.values(), key=lambda p: (p.rank, p.name))
