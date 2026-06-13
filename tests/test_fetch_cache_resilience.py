"""Regression tests: harvest must survive HTML/fetch cache read/write failures."""

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from src import fetch_pages
from src.fetch_cache import put_cached_fetch
from src.fetch_pages import PageFetcher


@pytest.fixture
def isolated_html_cache(tmp_path, monkeypatch):
    cache_root = tmp_path / "nested" / "cache" / "html"
    monkeypatch.setattr(fetch_pages, "HTML_CACHE", cache_root)
    return cache_root


def test_html_cache_write_creates_parent_directory(isolated_html_cache, monkeypatch):
    monkeypatch.setattr("src.fetch_pages.time.sleep", lambda _: None)
    fetcher = PageFetcher(delay=0, force_refresh=True, use_fetch_cache=False)
    url = "https://cache-mkdir-test.example.gov/planning"

    fetcher.client.get = MagicMock(  # type: ignore[method-assign]
        return_value=httpx.Response(
            200,
            text="<html><body>cached</body></html>",
            headers={"content-type": "text/html"},
        )
    )

    html = fetcher.fetch_html(url)
    fetcher.close()

    assert html is not None
    assert "cached" in html
    cache_file = isolated_html_cache / f"{fetch_pages._safe_cache_stem(url)}.html"
    assert cache_file.is_file()
    assert "cached" in cache_file.read_text(encoding="utf-8")


def test_unreadable_html_cache_does_not_crash_harvest(isolated_html_cache, monkeypatch):
    monkeypatch.setattr("src.fetch_pages.time.sleep", lambda _: None)
    url = "https://cache-read-fail-test.example.gov/staff"
    cache_file = isolated_html_cache / f"{fetch_pages._safe_cache_stem(url)}.html"
    isolated_html_cache.mkdir(parents=True, exist_ok=True)
    cache_file.mkdir()

    fetcher = PageFetcher(delay=0, force_refresh=False, use_fetch_cache=False)
    fetcher.client.get = MagicMock(  # type: ignore[method-assign]
        return_value=httpx.Response(
            200,
            text="<html><body>from network</body></html>",
            headers={"content-type": "text/html"},
        )
    )

    html = fetcher.fetch_html(url)
    fetcher.close()

    assert html is not None
    assert "from network" in html
    fetcher.client.get.assert_called_once()


def test_html_cache_write_failure_does_not_crash_harvest(isolated_html_cache, monkeypatch):
    monkeypatch.setattr("src.fetch_pages.time.sleep", lambda _: None)
    url = "https://cache-write-fail-test.example.gov/page"

    fetcher = PageFetcher(delay=0, force_refresh=True, use_fetch_cache=False)
    fetcher.client.get = MagicMock(  # type: ignore[method-assign]
        return_value=httpx.Response(
            200,
            text="<html><body>live</body></html>",
            headers={"content-type": "text/html"},
        )
    )

    def fail_write(self, data, *args, **kwargs):
        raise OSError(22, "Invalid argument", str(self))

    monkeypatch.setattr(Path, "write_text", fail_write)

    html = fetcher.fetch_html(url)
    fetcher.close()

    assert html is not None
    assert "live" in html


def test_fetch_cache_write_failure_is_non_fatal(tmp_path, monkeypatch, caplog):
    import logging

    cache_dir = tmp_path / "fetch_responses"
    monkeypatch.setattr("src.fetch_cache.FETCH_CACHE_DIR", cache_dir)
    url = "https://fetch-cache-write-fail.example.gov/planning"

    def fail_write(self, data, *args, **kwargs):
        raise OSError(22, "Invalid argument", str(self))

    monkeypatch.setattr(Path, "write_text", fail_write)

    with caplog.at_level(logging.WARNING, logger="contacts.fetch_cache"):
        put_cached_fetch(
            url,
            status_code=200,
            final_url=url,
            content_type="text/html",
            html="<html></html>",
        )

    assert any("Fetch cache write failed" in rec.message for rec in caplog.records)
    assert url in caplog.text


def test_windows_style_cache_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("src.fetch_pages.time.sleep", lambda _: None)
    cache_root = Path(str(tmp_path / "win-style" / "cache" / "html"))
    monkeypatch.setattr(fetch_pages, "HTML_CACHE", cache_root)
    url = "https://windows-path-test.example.gov/planning"

    fetcher = PageFetcher(delay=0, force_refresh=True, use_fetch_cache=False)
    fetcher.client.get = MagicMock(  # type: ignore[method-assign]
        return_value=httpx.Response(
            200,
            text="<html><body>win</body></html>",
            headers={"content-type": "text/html"},
        )
    )

    html = fetcher.fetch_html(url)
    fetcher.close()

    assert html is not None
    cache_file = fetch_pages._legacy_html_cache_path(url)
    assert cache_file.is_file()
