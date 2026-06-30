"""Domain enumerations shared across models, schemas, and services."""

from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    """Lifecycle of an AI analysis job stored on an insight row."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Sentiment(StrEnum):
    """Coarse sentiment label produced by the analysis step.

    A continuous ``score`` in ``[-1, 1]`` accompanies this label and drives the
    UI spectrum bar and the sentiment-tinted card halo.
    """

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
