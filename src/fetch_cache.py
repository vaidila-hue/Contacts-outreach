"""Disk-backed HTTP response cache keyed by normalized URL."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.paths import FETCH_CACHE_DIR


@dataclass
class CachedFetch:
    status_code: int
    final_url: str
    content_type: str
    html: str
    fetched_at: str


def _cache_path(normalized_url: str) -> Path:
    key = hashlib.sha256(normalized_url.encode()).hexdigest()[:20]
    return FETCH_CACHE_DIR / f"{key}.json"


def get_cached_fetch(normalized_url: str, ttl_days: int) -> CachedFetch | None:
    if not normalized_url:
        return None
    path = _cache_path(normalized_url)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        if datetime.now(timezone.utc) - fetched_at > timedelta(days=ttl_days):
            return None
        return CachedFetch(
            status_code=int(data.get("status_code", 0)),
            final_url=data.get("final_url", normalized_url),
            content_type=data.get("content_type", ""),
            html=data.get("html", ""),
            fetched_at=data.get("fetched_at", ""),
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


def put_cached_fetch(
    normalized_url: str,
    *,
    status_code: int,
    final_url: str,
    content_type: str,
    html: str,
) -> None:
    if not normalized_url:
        return
    FETCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "normalized_url": normalized_url,
        "status_code": status_code,
        "final_url": final_url,
        "content_type": content_type,
        "html": html,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache_path(normalized_url).write_text(json.dumps(payload), encoding="utf-8")
