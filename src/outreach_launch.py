"""CRM startup helpers: fixed URL, port checks, browser open."""

from __future__ import annotations

import socket
import threading
import urllib.error
import urllib.request
import webbrowser

from src.paths import OUTREACH_PORT

CRM_HOST = "127.0.0.1"
CRM_PUBLIC_HOST = "localhost"
CRM_URL = f"http://{CRM_PUBLIC_HOST}:{OUTREACH_PORT}"
CRM_TITLE_MARKER = b"Contacts Outreach CRM"


class PortInUseError(RuntimeError):
    def __init__(self, port: int = OUTREACH_PORT) -> None:
        self.port = port
        super().__init__(
            f"Port {port} is already in use. "
            f"The Contacts CRM must run at http://localhost:{port}. "
            f"Stop the other process or run: python src/run.py outreach --open"
        )


def is_port_in_use(host: str = CRM_HOST, port: int = OUTREACH_PORT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def is_crm_server_running(host: str = CRM_HOST, port: int = OUTREACH_PORT) -> bool:
    if not is_port_in_use(host, port):
        return False
    try:
        req = urllib.request.Request(
            f"http://{CRM_PUBLIC_HOST}:{port}/",
            headers={"User-Agent": "Contacts-CRM-Launcher/1.0"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            body = resp.read(8192)
            return resp.status == 200 and CRM_TITLE_MARKER in body
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def check_port_available(host: str = CRM_HOST, port: int = OUTREACH_PORT) -> None:
    if is_port_in_use(host, port):
        raise PortInUseError(port)


_browser_opened = False
_browser_lock = threading.Lock()


def open_crm_browser(url: str = CRM_URL) -> None:
    """Open CRM URL in the default browser once per process."""
    global _browser_opened
    with _browser_lock:
        if _browser_opened:
            return
        webbrowser.open(url)
        _browser_opened = True


def schedule_browser_open(delay_seconds: float = 1.0, url: str = CRM_URL) -> None:
    threading.Timer(delay_seconds, lambda: open_crm_browser(url)).start()


def reset_browser_state_for_tests() -> None:
    global _browser_opened
    with _browser_lock:
        _browser_opened = False
