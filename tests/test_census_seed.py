"""Tests for local-government-only Census seed filtering."""

import pytest

from src.census_seed import classify_census_geography


@pytest.mark.parametrize(
    "name_part,expected_bucket",
    [
        ("Bear CDP", "CDP"),
        ("Dover CCD", "CCD"),
        ("Brandywine CCD", "CCD"),
        ("Central Kent CCD", "CCD"),
        ("Wilmington CCD", "CCD"),
    ],
)
def test_statistical_geographies_excluded(name_part: str, expected_bucket: str) -> None:
    geo_type, excluded = classify_census_geography(name_part, "place")
    assert geo_type is None
    assert excluded == expected_bucket or (expected_bucket == "CCD" and excluded == "CCD")


def test_ccd_excluded_from_county_subdivision() -> None:
    geo_type, excluded = classify_census_geography("Dover CCD", "county subdivision")
    assert geo_type is None
    assert excluded == "CCD"


@pytest.mark.parametrize(
    "name_part,expected_type",
    [
        ("Dover city", "city"),
        ("Middletown town", "town"),
        ("Newark city", "city"),
        ("Wilmington city", "city"),
    ],
)
def test_delaware_places_included(name_part: str, expected_type: str) -> None:
    geo_type, excluded = classify_census_geography(name_part, "place")
    assert excluded is None
    assert geo_type == expected_type


def test_county_subdivision_township_included() -> None:
    geo_type, excluded = classify_census_geography("Springfield township", "county subdivision")
    assert excluded is None
    assert geo_type == "township"


def test_county_subdivision_town_included() -> None:
    geo_type, excluded = classify_census_geography("Barre town", "county subdivision")
    assert excluded is None
    assert geo_type == "town"


def test_county_subdivision_ccd_excluded() -> None:
    geo_type, excluded = classify_census_geography("Newark CCD", "county subdivision")
    assert geo_type is None
    assert excluded == "CCD"


def test_county_included() -> None:
    geo_type, excluded = classify_census_geography("Kent County", "county")
    assert excluded is None
    assert geo_type == "county"


def test_unlabeled_place_excluded_as_cdp() -> None:
    """Places without city/town/village/borough suffix are CDPs in Census place data."""
    geo_type, excluded = classify_census_geography("Bear", "place")
    assert geo_type is None
    assert excluded == "CDP"


def test_ri_counties_still_classified_as_county() -> None:
    """RI counties are classified as county; run.py rejects them via no_county_government."""
    geo_type, excluded = classify_census_geography("Providence County", "county")
    assert excluded is None
    assert geo_type == "county"
