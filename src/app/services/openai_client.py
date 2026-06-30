"""OpenAI-backed article analysis producing a structured :class:`AnalysisResult`.

The single public coroutine, :func:`analyze_article`, asks the model for a short
neutral summary, a sentiment label, and a continuous sentiment score, and returns
them validated against the shared :class:`AnalysisResult` contract. Structured
outputs (a JSON schema derived from the Pydantic model) guarantee the shape, so
the worker never has to defensively parse free-form text.

The client is injectable: tests pass a pre-built fake ``AsyncOpenAI`` so they never
touch the network.
"""

from __future__ import annotations

import logging

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from openai.types.chat import ChatCompletionMessageParam
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import Settings, get_settings
from app.schemas import AnalysisResult, ArticleBase

logger = logging.getLogger(__name__)

_RETRY_ATTEMPTS = 3
_SERVER_ERROR_FLOOR = 500

_SYSTEM_PROMPT = (
    "You are a precise financial-news analyst. For the article you are given, "
    "produce a neutral, factual 2-3 sentence summary, classify its overall "
    "sentiment as positive, neutral, or negative, and assign a continuous "
    "sentiment score in the range -1 to 1, where -1 is very negative, 0 is "
    "neutral, and 1 is very positive. Base the score on the article's tone and "
    "implications, and keep it consistent with the sentiment label."
)


class OpenAIAnalysisError(RuntimeError):
    """Raised when the model cannot return a usable analysis result."""


def _is_transient(exc: BaseException) -> bool:
    """Return whether an OpenAI error is worth retrying.

    Connection errors, timeouts, rate limits, and ``5xx`` responses are transient;
    everything else (bad requests, auth failures, refusals) is permanent.

    Args:
        exc: The exception raised during an API call attempt.

    Returns:
        ``True`` if the call should be retried, ``False`` otherwise.
    """
    if isinstance(exc, APIConnectionError | APITimeoutError | RateLimitError | InternalServerError):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code >= _SERVER_ERROR_FLOOR
    return False


def _build_messages(article: ArticleBase) -> list[ChatCompletionMessageParam]:
    """Build the chat messages describing ``article`` for analysis.

    Args:
        article: The article to analyze.

    Returns:
        The system and user messages to send to the model.
    """
    body = article.description or "(no description provided)"
    user_content = f"Title: {article.title}\nSource: {article.source}\n\nContent: {body}"
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


async def analyze_article(
    article: ArticleBase,
    settings: Settings | None = None,
    client: AsyncOpenAI | None = None,
) -> AnalysisResult:
    """Analyze an article into a summary, sentiment label, and sentiment score.

    Transient API failures are retried with exponential backoff; a permanent
    failure (or a response missing structured output) is surfaced as
    :class:`OpenAIAnalysisError`.

    Args:
        article: The article to analyze.
        settings: Optional settings override. Defaults to
            :func:`~app.core.config.get_settings`.
        client: Optional pre-built async OpenAI client. When provided the caller
            owns its lifecycle; when omitted one is created and closed internally.

    Returns:
        The structured :class:`AnalysisResult`.

    Raises:
        OpenAIAnalysisError: If analysis fails permanently or yields no result.
    """
    settings = settings or get_settings()
    owns_client = client is None
    openai_client = client or AsyncOpenAI(api_key=settings.openai_api_key)
    messages = _build_messages(article)

    retrying = retry(
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=0.5, max=8),
        retry=retry_if_exception(_is_transient),
        reraise=True,
    )

    async def _call() -> AnalysisResult:
        completion = await openai_client.chat.completions.parse(
            model=settings.openai_model,
            messages=messages,
            response_format=AnalysisResult,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise OpenAIAnalysisError("model returned no structured output")
        return parsed

    try:
        result = await retrying(_call)()
    except OpenAIAnalysisError:
        raise
    except Exception as exc:
        logger.warning("openai analysis failed for %r: %s", article.title, exc)
        raise OpenAIAnalysisError(f"analysis failed: {exc}") from exc
    finally:
        if owns_client:
            await openai_client.close()

    logger.debug(
        "analyzed %r -> sentiment=%s score=%.2f", article.title, result.sentiment, result.score
    )
    return result
