"""Alpaca News source.

Wraps the existing ``services.news_service.get_news`` flow which already
handles the SDK call + per-(symbol, date) JSONL cache. The source class
is a thin adapter so the aggregator doesn't need to know about the
legacy entry point.

Endpoint: GET https://data.alpaca.markets/v1beta1/news (via alpaca-py SDK)
Credentials: ALPACA_API_KEY + ALPACA_API_SECRET in .env (free-tier account is fine).
"""
from __future__ import annotations

import logging

from services.news_sources.base import NewsSource

logger = logging.getLogger(__name__)


class AlpacaNewsSource(NewsSource):
    id = "alpaca"
    label = "Alpaca News"
    enabled_by_default = True
    requires_credentials = ("ALPACA_API_KEY", "ALPACA_API_SECRET")

    async def fetch(self, symbol: str, lookback_hours: int):
        # Local import to avoid a circular reference (news_service →
        # news_sources/__init__ → here).
        from services.news_service import get_news_alpaca_only
        try:
            return await get_news_alpaca_only(
                symbol, lookback_hours=lookback_hours,
            )
        except Exception as e:                                # noqa: BLE001
            logger.warning("alpaca news fetch failed for %s: %s", symbol, e)
            return []
