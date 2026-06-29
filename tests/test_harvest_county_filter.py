"""Tests for county-scoped harvest targeting."""

from __future__ import annotations

import json

import pytest
from unittest.mock import patch

from src.census_seed import Jurisdiction
from src.directory_harvest import sort_jurisdictions_for_harvest
from src.harvest_config_store import HarvestConfigSettings, load_harvest_config, save_harvest_config
from src.harvest_county_filter import (
    SelectedCounty,
    derive_county_options,
    filter_jurisdictions_by_selected_counties,
    load_county_options_for_states,
    parse_selected_counties,
)
from src.harvest_runner import run_find_more_contacts
from src.outreach_ui import create_app


def _j(
    state: str,
    name: str,
    geo: str = "city",
    pop: int = 50000,
    county_name: str = "",
) -> Jurisdiction:
    return Jurisdiction(
        state=state,
        jurisdiction_name=name,
        geography_type=geo,
        population=pop,
        county_name=county_name,
    )


def test_config_without_county_field_loads_defaults(harvest_config_path):
    harvest_config_path.write_text(
        json.dumps(
            {
                "states": ["FL"],
                "min_population": 20000,
                "max_population": 100000,
                "limit": 50,
                "include_counties": False,
                "deep_mode": False,
            }
        ),
        encoding="utf-8",
    )
    loaded = load_harvest_config()
    assert loaded.selected_counties == []
    assert loaded.states == ["FL"]


def test_no_counties_selected_preserves_all_jurisdictions():
    jurisdictions = [
        _j("NC", "Asheville", county_name="Buncombe"),
        _j("NC", "Charlotte", county_name="Mecklenburg"),
        _j("FL", "Orlando", county_name="Orange"),
    ]
    filtered = filter_jurisdictions_by_selected_counties(jurisdictions, [])
    assert filtered == jurisdictions


def test_single_county_restricts_to_that_county():
    jurisdictions = [
        _j("NC", "Asheville", county_name="Buncombe"),
        _j("NC", "Charlotte", county_name="Mecklenburg"),
        _j("NC", "Buncombe County", geo="county", county_name="Buncombe"),
    ]
    selected = [SelectedCounty(state="NC", county="Buncombe County")]
    filtered = filter_jurisdictions_by_selected_counties(jurisdictions, selected)
    names = {j.jurisdiction_name for j in filtered}
    assert names == {"Asheville", "Buncombe County"}


def test_multiple_counties_across_states():
    jurisdictions = [
        _j("NC", "Asheville", county_name="Buncombe"),
        _j("FL", "Orlando", county_name="Orange"),
        _j("FL", "Miami", county_name="Miami-Dade"),
    ]
    selected = [
        SelectedCounty(state="NC", county="Buncombe County"),
        SelectedCounty(state="FL", county="Orange County"),
    ]
    filtered = filter_jurisdictions_by_selected_counties(jurisdictions, selected)
    assert {j.jurisdiction_name for j in filtered} == {"Asheville", "Orlando"}


def test_include_counties_checked_keeps_matching_county_government():
    jurisdictions = [
        _j("NC", "Asheville", county_name="Buncombe"),
        _j("NC", "Buncombe County", geo="county", county_name="Buncombe"),
    ]
    selected = [SelectedCounty(state="NC", county="Buncombe County")]
    filtered = filter_jurisdictions_by_selected_counties(jurisdictions, selected)
    ordered = sort_jurisdictions_for_harvest(filtered, include_counties=True)
    assert {j.jurisdiction_name for j in ordered} == {"Asheville", "Buncombe County"}


def test_include_counties_unchecked_excludes_county_government():
    jurisdictions = [
        _j("NC", "Asheville", county_name="Buncombe"),
        _j("NC", "Buncombe County", geo="county", county_name="Buncombe"),
    ]
    selected = [SelectedCounty(state="NC", county="Buncombe County")]
    filtered = filter_jurisdictions_by_selected_counties(jurisdictions, selected)
    ordered = sort_jurisdictions_for_harvest(filtered, include_counties=False)
    assert [j.jurisdiction_name for j in ordered] == ["Asheville"]


def test_saved_config_persists_county_selection(harvest_config_path):
    settings = HarvestConfigSettings(
        states=["NC", "FL"],
        min_population=20000,
        max_population=100000,
        limit=50,
        include_counties=False,
        deep_mode=False,
        selected_counties=[
            SelectedCounty(state="NC", county="Buncombe County"),
            SelectedCounty(state="FL", county="Orange County"),
        ],
    )
    save_harvest_config(settings)
    loaded = load_harvest_config()
    assert {c.option_value() for c in loaded.selected_counties} == {
        c.option_value() for c in settings.selected_counties
    }
    on_disk = json.loads(harvest_config_path.read_text(encoding="utf-8"))
    assert on_disk["selected_counties"] == [
        {"state": "NC", "county": "Buncombe County"},
        {"state": "FL", "county": "Orange County"},
    ]


def test_derive_county_options_from_jurisdiction_dataset():
    jurisdictions = [
        _j("NC", "Asheville", county_name="Buncombe"),
        _j("NC", "Buncombe County", geo="county", county_name="Buncombe"),
        _j("FL", "Orlando", county_name="Orange"),
    ]
    options = derive_county_options(jurisdictions, ["NC", "FL"])
    values = {o.option_value() for o in options}
    assert "NC|Buncombe County" in values
    assert "FL|Orange County" in values


def test_parse_selected_counties_from_form_values():
    parsed = parse_selected_counties(["NC|Buncombe County", "FL|Orange County"])
    assert len(parsed) == 2
    assert {c.option_value() for c in parsed} == {
        "NC|Buncombe County",
        "FL|Orange County",
    }


@pytest.fixture
def harvest_config_path(tmp_path, monkeypatch):
    import src.harvest_config_store as hcs
    import src.paths as paths

    config_path = tmp_path / "harvest_config.json"
    monkeypatch.setattr(paths, "HARVEST_CONFIG_JSON", config_path)
    monkeypatch.setattr(hcs, "HARVEST_CONFIG_JSON", config_path)
    return config_path


@pytest.fixture
def harvest_paths(tmp_path, monkeypatch):
    import src.export_results as er
    import src.harvest_config_store as hcs
    import src.harvest_runner as hr
    import src.harvest_summary as hs
    import src.outreach_store as store
    import src.paths as paths

    working = tmp_path / "prospects_working.csv"
    outreach = tmp_path / "outreach.csv"
    rejected = tmp_path / "prospects_rejected.csv"
    diagnostics = tmp_path / "harvest_diagnostics.csv"
    harvest_cfg = tmp_path / "harvest_config.json"
    summary = tmp_path / "last_harvest_summary.json"
    jurisdictions = tmp_path / "jurisdictions.csv"

    monkeypatch.setattr(paths, "WORKING_CSV", working)
    monkeypatch.setattr(paths, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(paths, "REJECTED_CSV", rejected)
    monkeypatch.setattr(paths, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(paths, "HARVEST_CONFIG_JSON", harvest_cfg)
    monkeypatch.setattr(paths, "LAST_HARVEST_SUMMARY_JSON", summary)
    monkeypatch.setattr(paths, "JURISDICTIONS_CSV", jurisdictions)
    monkeypatch.setattr(store, "WORKING_CSV", working)
    monkeypatch.setattr(store, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(store, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(hcs, "HARVEST_CONFIG_JSON", harvest_cfg)
    monkeypatch.setattr(hs, "LAST_HARVEST_SUMMARY_JSON", summary)
    monkeypatch.setattr(hr, "WORKING_CSV", working)
    monkeypatch.setattr(hr, "REJECTED_CSV", rejected)
    monkeypatch.setattr(er, "WORKING_CSV", working)
    monkeypatch.setattr(er, "REJECTED_CSV", rejected)
    monkeypatch.setattr(er, "DIAGNOSTICS_CSV", diagnostics)
    return harvest_cfg, jurisdictions


def test_harvest_runner_applies_county_filter(harvest_paths):
    harvest_cfg, jurisdictions_path = harvest_paths
    config = HarvestConfigSettings(
        states=["NC"],
        min_population=20000,
        max_population=100000,
        limit=10,
        include_counties=False,
        deep_mode=False,
        selected_counties=[SelectedCounty(state="NC", county="Buncombe County")],
    )
    save_harvest_config(config)

    seeded = [
        _j("NC", "Asheville", county_name="Buncombe"),
        _j("NC", "Charlotte", county_name="Mecklenburg"),
        _j("NC", "Buncombe County", geo="county", county_name="Buncombe"),
    ]
    harvested: list[str] = []

    def fake_harvest(j, *args, **kwargs):
        harvested.append(j.jurisdiction_name)
        return None, None, {
            "state": j.state,
            "jurisdiction_name": j.jurisdiction_name,
            "geography_type": j.geography_type,
            "population": str(j.population),
            "official_domain": "",
            "planning_pages_found": "0",
            "directory_pages_found": "0",
            "staff_links_found": "0",
            "profile_links_followed": "0",
            "mailto_links_found": "0",
            "emails_found": "0",
            "candidate_titles_found": "0",
            "pages_fetched": "0",
            "search_queries_run": "0",
            "found_contact": "no",
            "final_rejection_reason": "no_official_site_found",
            "elapsed_seconds": "1",
            "cache_hits": "0",
            "cache_misses": "0",
            "profile_pages_followed": "0",
            "early_stop": "no",
            "max_page_limit_hit": "no",
            "timeout_count": "0",
            "fetch_error_count": "0",
        }

    with patch("src.harvest_runner.seed_jurisdictions", return_value=(seeded, None)):
        with patch("src.harvest_runner.harvest_jurisdiction", side_effect=fake_harvest):
            with patch("src.harvest_runner.PageFetcher") as mock_fetcher:
                mock_fetcher.return_value.__enter__.return_value = object()
                run_find_more_contacts()

    assert harvested == ["Asheville"]
    assert "Charlotte" not in harvested
    assert jurisdictions_path.exists()
    saved = jurisdictions_path.read_text(encoding="utf-8")
    assert "Asheville" in saved
    assert "Charlotte" not in saved


def test_load_county_options_uses_bootstrap_before_census(tmp_path, monkeypatch):
    import src.harvest_county_filter as hcf

    bootstrap_path = tmp_path / "county_bootstrap.json"
    cache_path = tmp_path / "county_index.json"
    bootstrap_path.write_text(
        json.dumps({"CO": [{"state": "CO", "county": "Denver County"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(hcf, "COUNTY_BOOTSTRAP_JSON", bootstrap_path)
    monkeypatch.setattr(hcf, "COUNTY_INDEX_CACHE", cache_path)
    monkeypatch.setattr(hcf, "_bootstrap_cache", None)

    def fail_census(state):
        raise RuntimeError("should not call census when bootstrap exists")

    monkeypatch.setattr("src.harvest_county_filter.list_census_counties", fail_census)

    options = load_county_options_for_states(["CO"], min_population=0, max_population=0)
    assert len(options) == 1
    assert options[0].county == "Denver County"


def test_load_county_options_uses_census_not_harvest_csv(tmp_path, monkeypatch):
    import src.harvest_county_filter as hcf

    cache_path = tmp_path / "county_index.json"
    bootstrap_path = tmp_path / "county_bootstrap.json"
    bootstrap_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(hcf, "COUNTY_INDEX_CACHE", cache_path)
    monkeypatch.setattr(hcf, "COUNTY_BOOTSTRAP_JSON", bootstrap_path)
    monkeypatch.setattr(hcf, "_bootstrap_cache", None)

    def fake_list(state: str):
        if state == "FL":
            return [("095", "Orange County"), ("011", "Broward County")]
        if state == "OR":
            return [("039", "Lane County")]
        return []

    monkeypatch.setattr("src.harvest_county_filter.list_census_counties", fake_list)

    options = load_county_options_for_states(["FL", "OR"], min_population=0, max_population=0)
    values = {o.option_value() for o in options}
    assert values == {
        "FL|Broward County",
        "FL|Orange County",
        "OR|Lane County",
    }
    assert cache_path.is_file()


def test_county_options_available_before_harvest_output(tmp_path, monkeypatch):
    import src.harvest_county_filter as hcf

    cache_path = tmp_path / "county_index.json"
    bootstrap_path = tmp_path / "county_bootstrap.json"
    bootstrap_path.write_text(
        json.dumps({"FL": [{"state": "FL", "county": "Alachua County"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(hcf, "COUNTY_INDEX_CACHE", cache_path)
    monkeypatch.setattr(hcf, "COUNTY_BOOTSTRAP_JSON", bootstrap_path)
    monkeypatch.setattr(hcf, "_bootstrap_cache", None)

    options = load_county_options_for_states(["FL"], min_population=20000, max_population=100000)
    assert len(options) == 1
    assert options[0].county == "Alachua County"


def test_bootstrap_index_includes_colorado_counties():
    from src.paths import COUNTY_BOOTSTRAP_JSON

    data = json.loads(COUNTY_BOOTSTRAP_JSON.read_text(encoding="utf-8"))
    assert len(data["CO"]) == 64
    assert any(row["county"] == "Denver County" for row in data["CO"])


def test_counties_api_single_state(crm_paths, monkeypatch):
    from src.harvest_county_filter import CountyLoadResult, SelectedCounty

    monkeypatch.setattr(
        "src.outreach_ui.load_county_options_for_states_with_status",
        lambda states, **kwargs: CountyLoadResult(
            counties=[
                SelectedCounty(state="FL", county="Orange County"),
                SelectedCounty(state="FL", county="Broward County"),
            ],
            message="Loaded 2 counties.",
        ),
    )
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/harvest-config/counties?states=FL")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["counties"]) == 2
        assert data["counties"][0]["state"] == "FL"
        assert data["message"] == "Loaded 2 counties."


def test_counties_api_colorado_from_bootstrap(tmp_path, monkeypatch):
    import src.harvest_county_filter as hcf

    bootstrap = {
        "CO": [
            {"state": "CO", "county": "Denver County"},
            {"state": "CO", "county": "Boulder County"},
        ]
    }
    bootstrap_path = tmp_path / "county_bootstrap.json"
    bootstrap_path.write_text(json.dumps(bootstrap), encoding="utf-8")
    cache_path = tmp_path / "county_index.json"
    monkeypatch.setattr(hcf, "COUNTY_BOOTSTRAP_JSON", bootstrap_path)
    monkeypatch.setattr(hcf, "COUNTY_INDEX_CACHE", cache_path)
    monkeypatch.setattr(hcf, "_bootstrap_cache", None)

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/harvest-config/counties?states=CO")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["counties"]) == 2
        assert data["counties"][0]["state"] == "CO"
        assert "Loaded 2 counties" in data["message"]


def test_counties_api_multiple_states(crm_paths, monkeypatch):
    from src.harvest_county_filter import CountyLoadResult, SelectedCounty

    def loader(states, **kwargs):
        counties = [SelectedCounty(state=s, county=f"{s} Test County") for s in states]
        return CountyLoadResult(counties=counties, message=f"Loaded {len(counties)} counties.")

    monkeypatch.setattr("src.outreach_ui.load_county_options_for_states_with_status", loader)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/harvest-config/counties?states=FL,OR")
        assert resp.status_code == 200
        data = resp.get_json()
        assert {item["state"] for item in data["counties"]} == {"FL", "OR"}


def test_counties_api_empty_when_no_states(crm_paths):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/harvest-config/counties")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["counties"] == []
        assert "Select a state" in data["message"]


def test_counties_api_reports_error(crm_paths, monkeypatch):
    from src.harvest_county_filter import CountyLoadResult

    monkeypatch.setattr(
        "src.outreach_ui.load_county_options_for_states_with_status",
        lambda states, **kwargs: CountyLoadResult(
            message="County load failed.",
            error="Census lookup failed for ZZ: boom",
        ),
    )
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/harvest-config/counties?states=ZZ")
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["counties"] == []
        assert data["error"]


def test_harvest_modal_includes_county_refresh_script(crm_paths):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/")
        html = resp.data.decode("utf-8")
        assert 'id="harvest-states"' in html
        assert 'id="harvest-counties"' in html
        assert 'id="harvest-county-status"' in html
        assert "refreshHarvestCountyOptions" in html
        assert "setHarvestCountyStatus" in html
        assert "/harvest-config/counties" in html
        assert "harvest-county-v2" in html
        assert "harvestSavedCountyValues" in html


def test_harvest_modal_renders_county_selector(crm_paths):
    _, _, _, harvest_cfg = crm_paths
    save_harvest_config(
        HarvestConfigSettings(
            states=["NC"],
            min_population=20000,
            max_population=100000,
            limit=50,
            include_counties=False,
            deep_mode=False,
            selected_counties=[SelectedCounty(state="NC", county="Buncombe County")],
        )
    )
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/")
        html = resp.data.decode("utf-8")
        assert 'id="harvest-counties"' in html
        assert "NC|Buncombe County" in html
        assert "Optional: restrict harvest to jurisdictions within selected counties." in html


def test_harvest_modal_save_counties_route(crm_paths):
    _, _, _, harvest_cfg = crm_paths
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.post(
            "/harvest-config/save",
            data={
                "states": ["NC", "FL"],
                "counties": ["NC|Buncombe County", "FL|Orange County"],
                "min_population": "20000",
                "max_population": "100000",
                "limit": "50",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
    data = json.loads(harvest_cfg.read_text(encoding="utf-8"))
    assert {tuple(d.items()) for d in data["selected_counties"]} == {
        tuple({"state": "NC", "county": "Buncombe County"}.items()),
        tuple({"state": "FL", "county": "Orange County"}.items()),
    }


def test_example_config_includes_selected_counties():
    from pathlib import Path

    example = json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "harvest_config.example.json").read_text(
            encoding="utf-8"
        )
    )
    defaults = HarvestConfigSettings.defaults()
    assert example["selected_counties"] == []
    assert defaults.selected_counties == []


def test_gitignore_excludes_runtime_harvest_config():
    from pathlib import Path

    gitignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8")
    assert "data/harvest_config.json" in gitignore


@pytest.fixture
def crm_paths(tmp_path, monkeypatch):
    import src.harvest_config_store as hcs
    import src.outreach_store as store
    import src.paths as paths

    working = tmp_path / "prospects_working.csv"
    outreach = tmp_path / "outreach.csv"
    diagnostics = tmp_path / "harvest_diagnostics.csv"
    harvest_cfg = tmp_path / "harvest_config.json"

    monkeypatch.setattr(paths, "WORKING_CSV", working)
    monkeypatch.setattr(paths, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(paths, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(paths, "HARVEST_CONFIG_JSON", harvest_cfg)
    monkeypatch.setattr(store, "WORKING_CSV", working)
    monkeypatch.setattr(store, "OUTREACH_CSV", outreach)
    monkeypatch.setattr(store, "DIAGNOSTICS_CSV", diagnostics)
    monkeypatch.setattr(hcs, "HARVEST_CONFIG_JSON", harvest_cfg)
    return working, outreach, diagnostics, harvest_cfg
