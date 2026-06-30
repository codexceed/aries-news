"""Property-based tests for URL normalization (the article idempotency key)."""

from __future__ import annotations

from urllib.parse import urlencode

from hypothesis import given
from hypothesis import strategies as st

from app.core.url import normalize_url

_printable = st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=80)
_schemes = st.sampled_from(["http", "https", "HTTP", "HTTPS"])
_hosts = st.sampled_from(["example.com", "www.example.com", "News.Example.COM", "sub.example.org"])
_paths = st.sampled_from(["", "/", "/a", "/a/", "/a/b/", "/A/B"])
_param_keys = st.sampled_from(["a", "b", "z", "utm_source", "utm_medium", "fbclid", "ref", "q"])
_param_vals = st.text(alphabet="xyz123", max_size=4)


@given(_printable)
def test_idempotent_on_arbitrary_text(value: str) -> None:
    """Normalizing an already-normalized string is a no-op."""
    once = normalize_url(value)
    assert normalize_url(once) == once


@given(_schemes, _hosts, _paths)
def test_structured_urls_are_canonicalized(scheme: str, host: str, path: str) -> None:
    """Scheme/host lowercase, ``www.`` dropped, fragment gone, and idempotent."""
    once = normalize_url(f"{scheme}://{host}{path}#section")
    assert once == normalize_url(once)
    assert "#" not in once
    assert not once.split("://", 1)[1].startswith("www.")
    authority = once.split("://", 1)[1]
    assert authority.split("/")[0].islower() or authority.split("/")[0] == ""


@given(st.lists(st.tuples(_param_keys, _param_vals), max_size=6))
def test_tracking_params_stripped(params: list[tuple[str, str]]) -> None:
    """Tracking params are removed; the result stays idempotent."""
    query = urlencode(params)
    url = "https://example.com/post" + (f"?{query}" if query else "")
    once = normalize_url(url)
    assert "utm_" not in once
    assert "fbclid" not in once
    assert normalize_url(once) == once
