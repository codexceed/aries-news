"""Property-based tests for the sentiment -> UI mapping."""

from __future__ import annotations

import re

from hypothesis import given
from hypothesis import strategies as st

from app.core.sentiment import halo_color, marker_percent

_in_range = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False)
_any_float = st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6)
_HEX = re.compile(r"^#[0-9a-f]{6}$")


@given(_any_float)
def test_marker_always_in_bounds(score: float) -> None:
    """The marker percentage never leaves the bar, even for clamped scores."""
    assert 0.0 <= marker_percent(score) <= 100.0


@given(_in_range, _in_range)
def test_marker_is_monotonic(low: float, high: float) -> None:
    """A more positive score sits further left (lower percentage)."""
    if low < high:
        assert marker_percent(low) >= marker_percent(high)


def test_marker_endpoints() -> None:
    """Endpoints and midpoint land where the design expects."""
    assert marker_percent(1.0) == 0.0
    assert marker_percent(0.0) == 50.0
    assert marker_percent(-1.0) == 100.0
    assert marker_percent(5.0) == 0.0  # clamped
    assert marker_percent(-5.0) == 100.0  # clamped


@given(_any_float)
def test_halo_is_valid_hex(score: float) -> None:
    """The halo color is always a valid 6-digit hex string."""
    assert _HEX.match(halo_color(score)) is not None


def test_halo_endpoints_match_palette() -> None:
    """Halo endpoints equal the spectrum's sage/slate/clay stops."""
    assert halo_color(1.0) == "#7fa67c"
    assert halo_color(0.0) == "#8a93a6"
    assert halo_color(-1.0) == "#c97b6a"
