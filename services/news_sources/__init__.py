"""News-source registry — single import surface for callers.

Iterate ``NEWS_SOURCES`` to fan out fetches; look up by id with
``get_source(id)``. Adding a new source = drop a file in this folder
and append the instance to the list below. The widget settings panel
picks it up automatically (multiselect choices come from the registry).
"""
from __future__ import annotations

from services.news_sources.alpaca import AlpacaNewsSource
from services.news_sources.base import NewsSource
from services.news_sources.edgar import EdgarNewsSource
from services.news_sources.webull import WebullNewsSource

NEWS_SOURCES: list[NewsSource] = [
    AlpacaNewsSource(),
    EdgarNewsSource(),
    WebullNewsSource(),
]


def get_source(source_id: str) -> NewsSource | None:
    return next((s for s in NEWS_SOURCES if s.id == source_id), None)


def all_source_ids() -> list[str]:
    return [s.id for s in NEWS_SOURCES]


def default_enabled_source_ids() -> list[str]:
    """Sources turned on out of the box.

    Webull is off by default until the user pastes WEBULL_ACCESS_TOKEN
    into .env — turning it on without the token is harmless (the source
    just returns []) but cleaner to start it disabled.
    """
    return [s.id for s in NEWS_SOURCES if s.enabled_by_default]


def source_choices() -> list[dict]:
    """Format suitable for the widget settings multiselect chip-row."""
    return [{"value": s.id, "label": s.label} for s in NEWS_SOURCES]


__all__ = [
    "NewsSource",
    "NEWS_SOURCES",
    "get_source",
    "all_source_ids",
    "default_enabled_source_ids",
    "source_choices",
]
