"""Base contract for pluggable news sources.

Every news source — Alpaca, EDGAR, Webull, anything we add later —
implements this interface. The ``news_service.get_news_multi_source``
aggregator iterates the registry, filters by user-enabled ids, fans out
fetches in parallel, dedupes, and returns the unified list.

Adding a new source
-------------------
1. Subclass ``NewsSource``. Set ``id`` / ``label`` / ``requires_credentials``.
2. Implement ``async def fetch(symbol, lookback_hours) -> list[NewsItem]``.
3. Append an instance to ``NEWS_SOURCES`` in ``__init__.py``.

That's the whole flow — the widget settings panel picks up the new source
automatically (the multiselect choices come from the registry), and the
trade detail page + dashboard widget aggregate it without further edits.

Credentials
-----------
``requires_credentials`` lists the env vars the source needs. The
aggregator skips a source when any of its required vars is unset, so a
fresh checkout without `WEBULL_ACCESS_TOKEN` doesn't error — Webull
just contributes zero items.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.news_service import NewsItem


class NewsSource(ABC):
    """One news source. Subclasses set the four class attributes and
    implement ``fetch``."""

    id: str = ""
    label: str = ""
    enabled_by_default: bool = True
    requires_credentials: tuple[str, ...] = ()

    @abstractmethod
    async def fetch(self, symbol: str, lookback_hours: int) -> list["NewsItem"]:
        """Return news items for ``symbol`` in the trailing window."""

    def credentials_present(self) -> bool:
        """True when every required env var is non-empty."""
        return all(os.environ.get(name) for name in self.requires_credentials)

    def __repr__(self) -> str:
        return f"<NewsSource id={self.id!r} label={self.label!r}>"
