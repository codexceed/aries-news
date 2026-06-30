"""Tests for the OpenAI analysis client using an injected fake client.

These never touch the network: a fake ``AsyncOpenAI``-shaped object stands in for
the real client, so we exercise parsing, the no-result guard, and retry behavior
deterministically.
"""

from __future__ import annotations

import httpx
import pytest
from openai import APIConnectionError

from app.core.config import Settings
from app.core.enums import Sentiment
from app.schemas import AnalysisResult, ArticleBase
from app.services.openai_client import OpenAIAnalysisError, analyze_article

ARTICLE = ArticleBase(
    url="https://example.com/markets",
    title="Markets rally on upbeat data",
    source="Example Wire",
    description="Equities climbed after strong earnings.",
)


class _FakeMessage:
    def __init__(self, parsed: AnalysisResult | None) -> None:
        self.parsed = parsed


class _FakeChoice:
    def __init__(self, parsed: AnalysisResult | None) -> None:
        self.message = _FakeMessage(parsed)


class _FakeCompletion:
    def __init__(self, parsed: AnalysisResult | None) -> None:
        self.choices = [_FakeChoice(parsed)]


class _FakeCompletions:
    def __init__(self, result: AnalysisResult | None, error: Exception | None) -> None:
        self._result = result
        self._error = error
        self.calls = 0

    async def parse(self, **_kwargs: object) -> _FakeCompletion:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return _FakeCompletion(self._result)


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    """Minimal stand-in matching the bits of ``AsyncOpenAI`` we use."""

    def __init__(
        self, result: AnalysisResult | None = None, error: Exception | None = None
    ) -> None:
        self.completions = _FakeCompletions(result, error)
        self.chat = _FakeChat(self.completions)

    async def close(self) -> None:
        return None


def _settings() -> Settings:
    return Settings(openai_api_key="test-key", openai_model="gpt-4.1-nano")


async def test_parses_structured_result() -> None:
    expected = AnalysisResult(summary="A calm summary.", sentiment=Sentiment.POSITIVE, score=0.7)
    client = _FakeClient(result=expected)

    result = await analyze_article(ARTICLE, settings=_settings(), client=client)  # type: ignore[arg-type]

    assert result == expected
    assert client.completions.calls == 1


async def test_missing_parsed_raises() -> None:
    client = _FakeClient(result=None)

    with pytest.raises(OpenAIAnalysisError):
        await analyze_article(ARTICLE, settings=_settings(), client=client)  # type: ignore[arg-type]


async def test_permanent_error_not_retried() -> None:
    client = _FakeClient(error=ValueError("bad request"))

    with pytest.raises(OpenAIAnalysisError):
        await analyze_article(ARTICLE, settings=_settings(), client=client)  # type: ignore[arg-type]

    assert client.completions.calls == 1


async def test_transient_error_is_retried_then_raises() -> None:
    transient = APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"))
    client = _FakeClient(error=transient)

    with pytest.raises(OpenAIAnalysisError):
        await analyze_article(ARTICLE, settings=_settings(), client=client)  # type: ignore[arg-type]

    assert client.completions.calls == 3
