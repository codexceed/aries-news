"""URL normalization used as the idempotency key for articles.

Normalizing before storage means the same article reached via different
tracking links collapses to one row, so we never pay for a duplicate AI
analysis. The function is pure and idempotent:
``normalize_url(normalize_url(x)) == normalize_url(x)``.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "gclsrc",
        "dclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "igshid",
        "ref",
        "ref_src",
        "spm",
    }
)
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _is_tracking_param(key: str) -> bool:
    """Return whether a query-parameter name is a known tracking marker."""
    lowered = key.lower()
    return lowered.startswith(_TRACKING_PREFIXES) or lowered in _TRACKING_KEYS


def normalize_url(url: str) -> str:
    """Return a canonical form of ``url`` for use as a stable identity key.

    Lower-cases the scheme and host, drops a leading ``www.``, removes default
    ports, strips tracking query parameters, sorts the remaining ones, drops the
    fragment, and trims a trailing slash.

    Args:
        url: The raw article URL.

    Returns:
        The normalized URL. Returns the stripped input unchanged if it cannot
        be parsed into a host-bearing URL.
    """
    stripped = url.strip()
    parts = urlsplit(stripped)
    # Without a host there is nothing to canonicalize; return the input
    # unchanged so the function stays idempotent on non-URL text.
    if not parts.netloc:
        return stripped

    scheme = (parts.scheme or "https").lower()

    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]

    netloc = host
    port = parts.port
    if port is not None and _DEFAULT_PORTS.get(scheme) != port:
        netloc = f"{host}:{port}"

    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(key)
    ]
    kept.sort()
    query = urlencode(kept)

    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"

    return urlunsplit((scheme, netloc, path, query, ""))
