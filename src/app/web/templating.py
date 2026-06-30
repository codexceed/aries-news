"""Jinja2 templating setup and the helpers exposed to templates."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from fastapi.templating import Jinja2Templates

from app.core.sentiment import halo_color, marker_percent

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def article_slug(url: str) -> str:
    """Return a short, DOM-id-safe slug derived from an article URL.

    Args:
        url: The article URL.

    Returns:
        A 12-character hex digest, stable for a given URL.
    """
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def format_published(value: datetime | None) -> str:
    """Render an article timestamp for display.

    Args:
        value: The publication time, or ``None``.

    Returns:
        A compact ``"Mon DD"`` string, or an empty string when unset.
    """
    if value is None:
        return ""
    return value.strftime("%b %d")


def seconds(value: int | None) -> str:
    """Render a millisecond duration as seconds with one decimal.

    Args:
        value: A duration in milliseconds, or ``None``.

    Returns:
        e.g. ``"2.1s"``, or an empty string when unset.
    """
    if value is None:
        return ""
    return f"{value / 1000:.1f}s"


# env.globals' value type is inferred narrowly from Jinja's defaults; cast so
# our helpers can be registered under strict typing.
_globals = cast(dict[str, Any], templates.env.globals)
_globals["marker_percent"] = marker_percent
_globals["halo_color"] = halo_color
_globals["article_slug"] = article_slug
_globals["format_published"] = format_published
_globals["seconds"] = seconds
