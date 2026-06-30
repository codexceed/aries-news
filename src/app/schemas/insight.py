"""Insight schemas: the analysis result contract and API responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import JobStatus, Sentiment


class AnalysisResult(BaseModel):
    """Structured output of the AI analysis step.

    This is the contract the OpenAI client must satisfy; the worker persists it
    onto the insight row.
    """

    summary: str
    sentiment: Sentiment
    score: float = Field(ge=-1.0, le=1.0, description="Continuous sentiment in [-1, 1].")


class InsightRead(BaseModel):
    """An insight row as exposed by the API and rendered into the UI."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    article_id: int
    status: JobStatus
    summary: str | None
    sentiment: Sentiment | None
    score: float | None
    model: str | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None
