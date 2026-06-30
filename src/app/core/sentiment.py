"""Pure helpers mapping a sentiment score onto its UI representation.

A continuous score in ``[-1, 1]`` (``+1`` most positive, ``-1`` most negative)
drives two synchronized visuals: the marker's horizontal position on the
spectrum bar, and the card halo color sampled from that same position on the
``positive -> neutral -> negative`` gradient. Keeping this logic here (pure,
dependency-free) makes it trivially testable and reused by the templates.
"""

from __future__ import annotations

# Spectrum endpoints, left-to-right: positive (sage) -> neutral -> negative (clay).
# Must match the CSS gradient in static/css/app.css.
_POSITIVE = (0x7F, 0xA6, 0x7C)
_NEUTRAL = (0x8A, 0x93, 0xA6)
_NEGATIVE = (0xC9, 0x7B, 0x6A)


def _clamp_score(score: float) -> float:
    """Clamp a raw score into the ``[-1, 1]`` range."""
    return max(-1.0, min(1.0, score))


def marker_percent(score: float) -> float:
    """Return the marker's left offset as a percentage ``[0, 100]``.

    Positive scores sit on the left of the bar, negative on the right, matching
    the gradient direction.

    Args:
        score: Sentiment score in ``[-1, 1]`` (out-of-range values are clamped).

    Returns:
        The horizontal position as a percentage from the left edge.
    """
    return (1.0 - _clamp_score(score)) / 2.0 * 100.0


def _lerp(start: int, end: int, t: float) -> int:
    """Linearly interpolate a single 0-255 color channel."""
    return round(start + (end - start) * t)


def halo_color(score: float) -> str:
    """Return the halo hex color sampled from the spectrum at the marker.

    The color is the gradient value at :func:`marker_percent`, so the halo and
    the marker always agree.

    Args:
        score: Sentiment score in ``[-1, 1]`` (out-of-range values are clamped).

    Returns:
        A ``#rrggbb`` hex string.
    """
    percent = marker_percent(score)
    if percent <= 50.0:
        start, end, t = _POSITIVE, _NEUTRAL, percent / 50.0
    else:
        start, end, t = _NEUTRAL, _NEGATIVE, (percent - 50.0) / 50.0
    r = _lerp(start[0], end[0], t)
    g = _lerp(start[1], end[1], t)
    b = _lerp(start[2], end[2], t)
    return f"#{r:02x}{g:02x}{b:02x}"
