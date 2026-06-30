"""Article schemas for the news boundary and API responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ArticleBase(BaseModel):
    """An article as returned by the news provider (not yet persisted).

    ``from_attributes`` lets the ORM ``Article`` model be converted directly via
    ``ArticleBase.model_validate(article)`` everywhere, rather than copying
    fields by hand.
    """

    model_config = ConfigDict(from_attributes=True)

    url: str
    title: str
    source: str
    description: str | None = None
    image_url: str | None = None
    published_at: datetime | None = None


class ArticleRead(ArticleBase):
    """A persisted article, including its database identity."""

    id: int
    url_normalized: str
