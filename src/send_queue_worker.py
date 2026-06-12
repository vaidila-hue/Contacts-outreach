"""Background worker for throttled send queue."""

from __future__ import annotations

import logging
import threading
import time
import traceback
from dataclasses import dataclass

from src.send_queue import process_send_queue, queued_rows
from src.harvest_report import _fmt_ts_et

POLL_SECONDS = 30
_log = logging.getLogger("contacts.send_queue.worker")

_worker_thread: threading.Thread | None = None
_stop_event = threading.Event()
_started_at: str = ""
_last_tick_at: str = ""
_last_tick_ok: bool = False
_last_tick_detail: str = ""


@dataclass(frozen=True)
class WorkerStatus:
    started: bool
    thread_alive: bool
    started_at: str
    last_tick_at: str
    last_tick_ok: bool
    last_tick_detail: str

    def last_tick_display(self) -> str:
        if not self.last_tick_at:
            return "—"
        return _fmt_ts_et(self.last_tick_at)


def get_worker_status() -> WorkerStatus:
    return WorkerStatus(
        started=_worker_thread is not None,
        thread_alive=bool(_worker_thread and _worker_thread.is_alive()),
        started_at=_started_at,
        last_tick_at=_last_tick_at,
        last_tick_ok=_last_tick_ok,
        last_tick_detail=_last_tick_detail,
    )


def _record_tick(*, ok: bool, detail: str) -> None:
    global _last_tick_at, _last_tick_ok, _last_tick_detail
    from src.send_queue import _now_iso

    _last_tick_at = _now_iso()
    _last_tick_ok = ok
    _last_tick_detail = detail[:300]


def _worker_loop() -> None:
    _log.info("Send queue worker loop started (poll=%ss)", POLL_SECONDS)
    while not _stop_event.is_set():
        try:
            ok, detail = process_send_queue()
            _record_tick(ok=ok, detail=detail)
            if ok:
                _log.info("Worker tick sent: %s", detail)
            else:
                _log.info("Worker tick skipped: %s", detail)
        except Exception:
            _record_tick(ok=False, detail="worker exception")
            _log.exception("Send queue worker tick failed")
            try:
                from src.send_queue import pause_queue

                pause_queue("worker error")
            except Exception:
                _log.exception("Failed to pause queue after worker error")
        _stop_event.wait(POLL_SECONDS)
    _log.info("Send queue worker loop stopped")


def start_send_queue_worker(*, testing: bool = False) -> bool:
    """Start the daemon worker thread. Returns True if a new thread was started."""
    global _worker_thread, _started_at

    if testing:
        return False

    if _worker_thread is not None and _worker_thread.is_alive():
        _log.debug("Send queue worker already running")
        return False

    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    _stop_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, name="send-queue-worker", daemon=True)
    _worker_thread.start()
    from src.send_queue import SendQueueState, _now_iso

    state = SendQueueState.load()
    pending = queued_rows()
    _started_at = _now_iso()
    _log.info(
        "Send queue worker started (thread=%s, queued=%s, next_send_at=%s, paused=%s)",
        _worker_thread.name,
        len(pending),
        state.next_send_at or "—",
        state.paused,
    )
    print(
        f"Send queue worker started ({len(pending)} queued; "
        f"poll every {POLL_SECONDS}s). See console for tick logs."
    )
    return True


def stop_send_queue_worker() -> None:
    global _worker_thread
    _stop_event.set()
    if _worker_thread is not None:
        _worker_thread.join(timeout=POLL_SECONDS + 5)
        _worker_thread = None
