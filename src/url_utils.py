"""URL normalization and deduplication helpers."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

TRACKING_QUERY_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
        "_ga",
        "ref",
    }
)


def normalize_url(url: str, base: str | None = None) -> str:
    """Normalize URL for dedupe/cache keys: scheme, host, path, filtered query, no fragment."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if base:
        raw = urljoin(base, raw)
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if not netloc:
        return ""
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in TRACKING_QUERY_PARAMS
    ]
    query = urlencode(query_pairs, doseq=True) if query_pairs else ""
    return urlunparse((scheme, netloc, path, "", query, ""))
