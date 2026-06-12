"""Tests for fetch retry, profiles, and failure diagnostics."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.fetch_pages import FetchFailureRecord, PageFetcher, format_fetch_failures


def test_fetch_retries_timeout_then_succeeds(monkeypatch):
    monkeypatch.setattr("src.fetch_pages.time.sleep", lambda _: None)
    fetcher = PageFetcher(delay=0, force_refresh=True, use_fetch_cache=False, max_retries=2, planning_max_retries=2)
    responses = [
        httpx.TimeoutException("timeout"),
        httpx.Response(200, text="<html><body>ok</body></html>", headers={"content-type": "text/html"}),
    ]
    call_count = 0

    def fake_get(url, timeout=None):
        nonlocal call_count
        call_count += 1
        item = responses[call_count - 1]
        if isinstance(item, Exception):
            raise item
        return item

    fetcher.client.get = fake_get  # type: ignore[method-assign]
    html = fetcher.fetch_html("https://retry-timeout-test.example.gov/planning", profile="planning")
    assert html is not None
    assert "ok" in html
    assert call_count == 2
    fetcher.close()


def test_fetch_records_failure_diagnostics(monkeypatch):
    monkeypatch.setattr("src.fetch_pages.time.sleep", lambda _: None)
    fetcher = PageFetcher(delay=0, use_fetch_cache=False, max_retries=0)
    fetcher.client.get = MagicMock(side_effect=httpx.ConnectError("connection refused"))
    html = fetcher.fetch_html("https://example.gov/staff")
    assert html is None
    failures = fetcher.fetch_failures()
    assert len(failures) == 1
    rec = failures[0]
    assert rec.url == "https://example.gov/staff"
    assert rec.error_type == "connection_error"
    assert rec.attempts == 1
    fetcher.close()


def test_fetch_retries_rate_limit(monkeypatch):
    monkeypatch.setattr("src.fetch_pages.time.sleep", lambda _: None)
    fetcher = PageFetcher(delay=0, force_refresh=True, use_fetch_cache=False, planning_max_retries=2)
    call_count = 0

    def fake_get(url, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, text="slow down", headers={"content-type": "text/plain"})
        return httpx.Response(
            200,
            text="<html><body>staff</body></html>",
            headers={"content-type": "text/html"},
        )

    fetcher.client.get = fake_get  # type: ignore[method-assign]
    html = fetcher.fetch_html("https://retry-ratelimit-test.example.gov/directory", profile="planning")
    assert html is not None
    assert call_count == 2
    fetcher.close()


def test_failed_fetch_not_cached_for_retry(monkeypatch):
    monkeypatch.setattr("src.fetch_pages.time.sleep", lambda _: None)
    fetcher = PageFetcher(delay=0, force_refresh=True, use_fetch_cache=False, max_retries=0)
    calls = {"n": 0}

    def fake_get(url, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.TimeoutException("timeout")
        return httpx.Response(
            200,
            text="<html><body>second</body></html>",
            headers={"content-type": "text/html"},
        )

    fetcher.client.get = fake_get  # type: ignore[method-assign]
    url = "https://retry-profile-test.example.gov/planning"
    assert fetcher.fetch_html(url, profile="default") is None
    html = fetcher.fetch_html(url, profile="planning")
    assert html is not None
    assert calls["n"] == 2
    fetcher.close()


def test_format_fetch_failures_compact():
    text = format_fetch_failures(
        [
            FetchFailureRecord(
                url="https://a.gov/p",
                http_status=503,
                error_type="transient_http",
                rejection_reason="retryable_http_503",
                attempts=3,
            )
        ]
    )
    assert "https://a.gov/p" in text
    assert "503" in text
    assert "transient_http" in text
