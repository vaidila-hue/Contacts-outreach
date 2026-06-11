"""Person-first discovery pass: find staff names then search for direct emails."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from src.extract_contacts import ContactCandidate, extract_contacts_from_html, select_best_contact
from src.extract_emails import (
    classify_email,
    extract_emails_from_text,
    is_generic_email,
    normalize_email,
)
from src.extract_pdf import extract_contacts_from_pdf, extract_text_from_pdf
from src.jurisdiction_validation import (
    check_email_jurisdiction,
    check_url_jurisdiction,
    gov_domain_implies_other_municipality,
)
from src.jurisdiction_utils import normalize_jurisdiction_name, official_homepage_from_url
from src.person_extract import PersonCandidate, extract_person_from_search_hit, rank_person_candidates
from src.role_config import (
    MAX_PERSON_EMAIL_QUERIES,
    MAX_PERSON_SEARCH_QUERIES,
    person_email_queries,
    person_name_queries,
)
from src.search_providers import SearchHit, search_text


@dataclass
class PersonFirstResult:
    contact_name: str
    contact_title: str
    email: str
    candidate_source_url: str
    email_source_url: str
    discovery_method: str = "person_first_search"
    jurisdiction_match_status: str = "uncertain"
    jurisdiction_match_notes: str = ""
    source_snippet: str = ""


STATE_NAMES: dict[str, str] = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas",
    "CA": "california", "CO": "colorado", "CT": "connecticut", "DE": "delaware",
    "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho",
    "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas",
    "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland",
    "MA": "massachusetts", "MI": "michigan", "MN": "minnesota", "MS": "mississippi",
    "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada",
    "NH": "new hampshire", "NJ": "new jersey", "NM": "new mexico", "NY": "new york",
    "NC": "north carolina", "ND": "north dakota", "OH": "ohio", "OK": "oklahoma",
    "OR": "oregon", "PA": "pennsylvania", "RI": "rhode island", "SC": "south carolina",
    "SD": "south dakota", "TN": "tennessee", "TX": "texas", "UT": "utah",
    "VT": "vermont", "VA": "virginia", "WA": "washington", "WV": "west virginia",
    "WI": "wisconsin", "WY": "wyoming", "DC": "district of columbia",
}


def official_domain(official_url: str | None) -> str:
    if not official_url:
        return ""
    return urlparse(official_url).netloc.lower().lstrip("www.")


def _email_domain(email: str) -> str:
    return email.split("@", 1)[1].lower()


def _domain_related_to_official(email: str, official_url: str | None) -> bool:
    if not official_url:
        return False
    oh = official_domain(official_url)
    ed = _email_domain(email).lstrip("www.")
    if not oh:
        return False
    return oh in ed or ed.endswith(oh) or ed.endswith(oh.split(".")[0] + ".org")


def _url_on_official_domain(url: str, official_url: str | None) -> bool:
    return _source_on_official(url, official_url)


def _text_has_jurisdiction_and_state(
    text: str,
    jurisdiction_name: str,
    state: str,
) -> bool:
    if not text or not text.strip():
        return False
    lower = text.lower()
    display = normalize_jurisdiction_name(jurisdiction_name).lower()
    names = {display}
    if " county" in display:
        names.add(display.replace(" county", "").strip())
    state_upper = state.upper()
    state_name = STATE_NAMES.get(state_upper, "")
    has_jurisdiction = any(len(n) >= 4 and n in lower for n in names)
    has_state = (
        f" {state.lower()} " in f" {lower} "
        or f", {state.lower()}" in lower
        or (state_name and state_name in lower)
    )
    return has_jurisdiction and has_state


def person_first_working_eligible(
    result: PersonFirstResult,
    jurisdiction_name: str,
    state: str,
    official_url: str | None,
) -> bool:
    """
    Person-first rows enter working CSV only with strong jurisdiction association.
    """
    email_status, _ = check_email_jurisdiction(result.email, jurisdiction_name, state)
    if email_status == "mismatch":
        return False
    if gov_domain_implies_other_municipality(
        _email_domain(result.email), jurisdiction_name, state
    ):
        return False
    for url in (result.candidate_source_url, result.email_source_url):
        url_status, _ = check_url_jurisdiction(url, jurisdiction_name, state)
        if url_status == "mismatch":
            return False

    if result.jurisdiction_match_status == "matched":
        return True
    if _url_on_official_domain(result.candidate_source_url, official_url):
        return True
    if _url_on_official_domain(result.email_source_url, official_url):
        return True
    if _domain_related_to_official(result.email, official_url):
        return True
    combined_text = " ".join(
        part for part in (result.source_snippet, result.jurisdiction_match_notes) if part
    )
    if _text_has_jurisdiction_and_state(combined_text, jurisdiction_name, state):
        return True
    return False


def _source_on_official(url: str, official_url: str | None) -> bool:
    if not official_url or not url:
        return False
    oh = urlparse(official_url).netloc.lower()
    uh = urlparse(url).netloc.lower()
    return oh == uh or uh.endswith(oh.replace("www.", ""))


def validate_person_first_contact(
    person: PersonCandidate,
    email: str,
    email_source_url: str,
    jurisdiction_name: str,
    state: str,
    official_url: str | None,
) -> PersonFirstResult | None:
    email = normalize_email(email)
    if is_generic_email(email):
        return None
    if classify_email(email, person.name, paired_with_name=True) != "direct":
        return None

    email_dom_status, email_dom_note = check_email_jurisdiction(
        email, jurisdiction_name, state
    )
    if email_dom_status == "mismatch" and not _domain_related_to_official(email, official_url):
        return None

    src_status, src_note = check_url_jurisdiction(
        email_source_url, jurisdiction_name, state
    )
    if src_status == "mismatch" and not _source_on_official(email_source_url, official_url):
        return None

    cand_status, cand_note = check_url_jurisdiction(
        person.candidate_source_url, jurisdiction_name, state
    )
    if cand_status == "mismatch":
        return None

    notes: list[str] = []
    if person.candidate_source_url != email_source_url:
        notes.append(f"name from {person.candidate_source_url}")
        notes.append(f"email from {email_source_url}")
    if email_dom_note:
        notes.append(email_dom_note)
    if src_note:
        notes.append(src_note)
    if cand_note:
        notes.append(cand_note)

    if (
        _domain_related_to_official(email, official_url)
        and _source_on_official(email_source_url, official_url)
    ):
        match_status = "matched"
    elif email_dom_status == "matched" or src_status == "matched":
        match_status = "matched"
    else:
        match_status = "uncertain"

    return PersonFirstResult(
        contact_name=person.name,
        contact_title=person.title,
        email=email,
        candidate_source_url=person.candidate_source_url,
        email_source_url=email_source_url,
        jurisdiction_match_status=match_status,
        jurisdiction_match_notes="; ".join(n for n in notes if n),
        source_snippet=person.snippet,
    )


def find_people_from_search(
    jurisdiction_name: str,
    state: str,
    geography_type: str,
    county_name: str,
    delay: float,
) -> list[PersonCandidate]:
    display = normalize_jurisdiction_name(jurisdiction_name)
    county = normalize_jurisdiction_name(county_name or jurisdiction_name).replace(" County", "")
    queries = person_name_queries(display, state, geography_type, county)
    candidates: list[PersonCandidate] = []

    for i, query in enumerate(queries):
        if i >= MAX_PERSON_SEARCH_QUERIES:
            break
        hits, _ = search_text(query, max_results=5, delay=delay, gov_only=False)
        for hit in hits:
            person = extract_person_from_search_hit(hit)
            if person:
                candidates.append(person)
    return rank_person_candidates(candidates)[:3]


def _extract_email_from_page(
    html: str,
    url: str,
    person: PersonCandidate,
) -> tuple[str, str] | None:
    for em in extract_emails_from_text(html):
        if is_generic_email(em):
            continue
        if classify_email(em, person.name, paired_with_name=True) == "direct":
            return em, url
    contacts = extract_contacts_from_html(html, url)
    for c in contacts:
        if c.name and person.name.split()[0].lower() not in c.name.lower():
            continue
        if classify_email(c.email, person.name, True) == "direct":
            return c.email, c.source_url
    best = select_best_contact(contacts)
    if best and classify_email(best.email, person.name, True) == "direct":
        if person.name.split()[0].lower() in best.name.lower():
            return best.email, best.source_url
    return None


def search_email_for_person(
    person: PersonCandidate,
    jurisdiction_name: str,
    state: str,
    official_url: str | None,
    fetcher,
    delay: float,
) -> PersonFirstResult | None:
    display = normalize_jurisdiction_name(jurisdiction_name)
    domain = official_domain(official_url)
    queries = person_email_queries(person.name, person.title, display, state, domain)

    for i, query in enumerate(queries):
        if i >= MAX_PERSON_EMAIL_QUERIES:
            break
        hits, _ = search_text(query, max_results=5, delay=delay, gov_only=False)
        for hit in hits:
            combined = f"{hit.title} {hit.snippet}"
            for em in extract_emails_from_text(combined):
                result = validate_person_first_contact(
                    person, em, hit.url, display, state, official_url
                )
                if result:
                    return result

            from src.jurisdiction_utils import url_matches_jurisdiction

            if not url_matches_jurisdiction(hit.url, display, state):
                continue
            html = fetcher.fetch_html(hit.url)
            if not html:
                continue
            found = _extract_email_from_page(html, hit.url, person)
            if found:
                em, src = found
                result = validate_person_first_contact(
                    person, em, src, display, state, official_url
                )
                if result:
                    return result
            if hit.url.lower().endswith(".pdf"):
                pdf_bytes = fetcher.fetch_pdf(hit.url)
                if pdf_bytes:
                    pdf_text = extract_text_from_pdf(pdf_bytes)
                    for em in extract_emails_from_text(pdf_text):
                        result = validate_person_first_contact(
                            person, em, hit.url, display, state, official_url
                        )
                        if result:
                            return result
    return None


def run_person_first_pass(
    jurisdiction_name: str,
    state: str,
    geography_type: str,
    county_name: str,
    official_url: str | None,
    fetcher,
    delay: float,
) -> PersonFirstResult | None:
    people = find_people_from_search(
        jurisdiction_name, state, geography_type, county_name, delay
    )
    for person in people:
        result = search_email_for_person(
            person, jurisdiction_name, state, official_url, fetcher, delay
        )
        if result:
            return result
    return None
