"""Tests for email classification."""

import pytest

from src.extract_emails import (
    classify_email,
    is_direct_email,
    is_generic_email,
)


@pytest.mark.parametrize(
    "email",
    [
        "planning@city.gov",
        "info@town.gov",
        "zoning@county.gov",
        "communitydevelopment@city.gov",
        "admin@city.gov",
        "clerk@town.gov",
        "office@city.gov",
        "department@city.gov",
    ],
)
def test_generic_emails_rejected(email):
    assert is_generic_email(email)
    assert classify_email(email) == "generic"


def test_direct_email_with_name_pattern():
    assert is_direct_email("jane.smith@city.gov", "Jane Smith")
    assert classify_email("jane.smith@city.gov", "Jane Smith") == "direct"


def test_paired_with_name_counts_as_direct():
    assert classify_email("jsmith@city.gov", "John Smith", paired_with_name=True) == "direct"


def test_unclear_email():
    assert classify_email("contact123@city.gov") == "unclear"
