"""Background worker for throttled send queue."""

from __future__ import annotations

import threading
import time

from src.send_queue import process_send_queue

POLL_SECONDS = 30
_worker_started = False
_stop_event = threading.Event()


def _worker_loop() -> None:
    while not _stop_event.is_set():
        try:
            process_send_queue()
        except Exception:
            from src.send_queue import pause_queue

            pause_queue("worker error")
        _stop_event.wait(POLL_SECONDS)


def start_send_queue_worker(*, testing: bool = False) -> None:
    global _worker_started
    if testing or _worker_started:
        return
    _worker_started = True
    thread = threading.Thread(target=_worker_loop, name="send-queue-worker", daemon=True)
    thread.start()


def stop_send_queue_worker() -> None:
    _stop_event.set()
