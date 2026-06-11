"""Tests for PDF contact extraction."""

from unittest.mock import patch

from src.extract_contacts import extract_contacts_from_text, select_best_contact
from src.extract_pdf import extract_contacts_from_pdf

PDF_TEXT = """
Planning Department Staff Directory
Robert Chen, Planning Director, robert.chen@county.gov
Susan Lee, County Planner, planning@county.gov
James Walsh, Community Development Director, james.walsh@county.gov
"""


def test_pdf_text_extraction_finds_director():
    candidates = extract_contacts_from_text(PDF_TEXT, "https://county.gov/staff.pdf")
    best = select_best_contact(candidates)
    assert best is not None
    assert "Director" in best.title
    assert best.email == "robert.chen@county.gov"


@patch("src.extract_pdf.extract_text_from_pdf")
def test_extract_contacts_from_pdf(mock_text):
    mock_text.return_value = PDF_TEXT
    candidates = extract_contacts_from_pdf(b"fake-pdf", "https://county.gov/dir.pdf")
    best = select_best_contact(candidates)
    assert best is not None
    assert best.email == "robert.chen@county.gov"
