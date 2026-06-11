"""Tests for CRM launch helpers and CLI open/serve behavior."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from src.outreach_launch import (
    CRM_URL,
    PortInUseError,
    check_port_available,
    is_crm_server_running,
    open_crm_browser,
    reset_browser_state_for_tests,
    schedule_browser_open,
)
from src.outreach_ui import create_app
from src.paths import OUTREACH_PORT


@pytest.fixture(autouse=True)
def reset_browser():
    reset_browser_state_for_tests()
    yield
    reset_browser_state_for_tests()


def test_crm_url_is_fixed_localhost_port():
    assert CRM_URL == f"http://localhost:{OUTREACH_PORT}"
    assert OUTREACH_PORT == 8765


def test_check_port_available_raises_when_in_use():
    with patch("src.outreach_launch.is_port_in_use", return_value=True):
        with pytest.raises(PortInUseError) as exc:
            check_port_available()
        assert "8765" in str(exc.value)


def test_open_crm_browser_only_once():
    with patch("src.outreach_launch.webbrowser.open") as mock_open:
        open_crm_browser()
        open_crm_browser()
        mock_open.assert_called_once_with(CRM_URL)


def test_schedule_browser_open():
    with patch("src.outreach_launch.open_crm_browser") as mock_open:
        with patch("src.outreach_launch.threading.Timer") as mock_timer:
            schedule_browser_open(delay_seconds=0.5)
            mock_timer.assert_called_once()
            callback = mock_timer.call_args[0][1]
            callback()
            mock_open.assert_called_once()


def test_is_crm_server_running_detects_flask_app():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        with patch("src.outreach_launch.is_port_in_use", return_value=True):
            with patch("src.outreach_launch.urllib.request.urlopen") as mock_urlopen:
                mock_urlopen.return_value.__enter__.return_value.status = 200
                mock_urlopen.return_value.__enter__.return_value.read.return_value = (
                    b"<title>Contacts Outreach CRM</title>"
                )
                assert is_crm_server_running() is True


def test_run_outreach_open_when_already_running():
    from src.run import run_outreach_open

    with patch("src.run.is_crm_server_running", return_value=True):
        with patch("src.run.open_crm_browser") as mock_open:
            with patch("src.run.run_outreach_server") as mock_serve:
                assert run_outreach_open() == 0
                mock_open.assert_called_once()
                mock_serve.assert_not_called()


def test_run_outreach_open_starts_server_when_not_running():
    from src.run import run_outreach_open

    with patch("src.run.is_crm_server_running", return_value=False):
        with patch("src.run.is_port_in_use", return_value=False):
            with patch("src.run.run_outreach_server") as mock_serve:
                run_outreach_open()
                mock_serve.assert_called_once_with(open_browser=True)


def test_run_outreach_serve_errors_when_port_busy():
    import argparse
    from src.run import run_outreach

    args = argparse.Namespace(
        open=False,
        prepare=False,
        serve=True,
        draft=False,
        send=False,
    )
    with patch("src.run.check_port_available", side_effect=PortInUseError()):
        assert run_outreach(args) == 1


def test_run_outreach_server_rejects_non_default_port():
    from src.outreach_ui import run_outreach_server

    with pytest.raises(ValueError, match="8765"):
        run_outreach_server(port=9999)


def test_run_outreach_server_schedules_browser():
    from src.outreach_ui import run_outreach_server

    with patch("src.outreach_ui.check_port_available"):
        with patch("src.outreach_ui.schedule_browser_open") as mock_schedule:
            with patch("src.outreach_ui.create_app") as mock_app:
                mock_app.return_value.run.side_effect = lambda **kw: None
                run_outreach_server(open_browser=True)
                mock_schedule.assert_called_once()
