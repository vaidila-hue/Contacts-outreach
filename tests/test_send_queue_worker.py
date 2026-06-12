"""Tests for send queue worker lifecycle."""

from __future__ import annotations

import time
from unittest.mock import patch

from src.send_queue_worker import get_worker_status, start_send_queue_worker, stop_send_queue_worker


def test_worker_starts_and_reports_alive():
    stop_send_queue_worker()
    with patch("src.send_queue_worker.process_send_queue", return_value=(False, "Queue empty")):
        started = start_send_queue_worker(testing=False)
        assert started
        status = get_worker_status()
        assert status.started
        assert status.thread_alive
        assert status.started_at
        time.sleep(0.05)
        stop_send_queue_worker()


def test_worker_can_restart_after_stop():
    stop_send_queue_worker()
    with patch("src.send_queue_worker.process_send_queue", return_value=(False, "Queue empty")):
        assert start_send_queue_worker(testing=False)
        stop_send_queue_worker()
        assert start_send_queue_worker(testing=False)
        assert get_worker_status().thread_alive
        stop_send_queue_worker()
