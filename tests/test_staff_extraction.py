"""Tests for staff directory extraction and link discovery."""

from src.extract_contacts import (
    extract_contacts_from_html,
    extract_profile_followups,
    count_mailto_links,
)
from src.staff_discovery import discover_internal_staff_urls, score_staff_link


def test_mailto_with_email_link_text_and_parent_name_title():
    html = """
    <div class="staff-card">
      <h3>Jane Smith</h3>
      <p>Planning Director</p>
      <a href="mailto:jane.smith@city.gov">Email</a>
    </div>
    """
    contacts = extract_contacts_from_html(html, "https://city.gov/staff", "https://city.gov")
    assert any(c.email == "jane.smith@city.gov" for c in contacts)
    assert any(c.name == "Jane Smith" for c in contacts)


def test_contact_block_profile_followup():
    html = """
    <ul>
      <li>
        <strong>John Doe</strong><br>
        Community Development Director<br>
        <a href="/staff/john-doe">View Profile</a>
      </li>
    </ul>
    """
    profiles = extract_profile_followups(html, "https://town.gov/directory", "https://town.gov")
    assert len(profiles) == 1
    assert profiles[0].name == "John Doe"
    assert "john-doe" in profiles[0].profile_url


def test_profile_page_mailto():
    html = """
    <div>
      <h1>Jane Smith</h1>
      <p>Planning Director</p>
      <a href="mailto:jsmith@town.gov">jsmith@town.gov</a>
    </div>
    """
    contacts = extract_contacts_from_html(html, "https://town.gov/staff/jane", "https://town.gov")
    assert any(c.email == "jsmith@town.gov" for c in contacts)


def test_discover_internal_staff_links():
    html = """
    <a href="/departments/planning">Planning Department</a>
    <a href="/staff-directory">Staff Directory</a>
    <a href="https://other.gov/page">Other</a>
    """
    links = discover_internal_staff_urls(html, "https://city.gov", "https://city.gov")
    urls = [u for u, _ in links]
    assert any("planning" in u for u in urls)
    assert any("staff-directory" in u for u in urls)
    assert not any("other.gov" in u for u in urls)


def test_score_staff_link_prioritizes_planning():
    assert score_staff_link("https://x.gov/planning-zoning", "Planning") > score_staff_link(
        "https://x.gov/admin", "Administration"
    )


def test_count_mailto_links():
    html = '<a href="mailto:a@b.gov">A</a><a href="/page">X</a>'
    assert count_mailto_links(html) == 1


def test_safe_soup_handles_broken_charref():
    from src.fetch_pages import safe_soup

    broken = "<p>Staff &#39Brien, Emilio</p>"
    assert safe_soup(broken) is None
    assert extract_contacts_from_html(broken, "https://example.gov/staff") == []
    assert count_mailto_links(broken) == 0
