"""SEC EDGAR filings as a news source.

Filings are NOT general news, but for a trade detail page they're the
single highest-signal item-stream available — 8-Ks, 10-Qs, 10-Ks land
on a fixed cadence and almost always move price. We surface them
alongside news and let the partial split them visually with a
"SEC Filings" section header + form-type badge.

Wraps the existing ``services.news_service.get_filings`` flow. The
form_type ends up in the headline as ``"<form>: <title>"`` — the trade
detail router pulls it out into a structured ``form_type`` field for
badge rendering.

Endpoint: SEC atom feed (no key required, polite UA per SEC guidance).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from services.news_sources.base import NewsSource

logger = logging.getLogger(__name__)


class EdgarNewsSource(NewsSource):
    id = "edgar"
    label = "SEC EDGAR Filings"
    enabled_by_default = True
    requires_credentials = ()  # public — only needs polite UA, set in news_service

    async def fetch(self, symbol: str, lookback_hours: int):
        from services.news_service import NewsItem, get_filings

        # Filings are quarterly-ish — convert hours to days, floor at 14d
        # so a 24h window doesn't filter out a 3-day-old 10-Q.
        lookback_days = max(14, int(timedelta(hours=lookback_hours).days))
        try:
            filings = await get_filings(symbol, lookback_days=lookback_days)
        except Exception as e:                                # noqa: BLE001
            logger.warning("edgar fetch failed for %s: %s", symbol, e)
            return []

        items: list[NewsItem] = []
        for f in filings:
            try:
                items.append(NewsItem(
                    source="edgar",
                    symbol=symbol.upper(),
                    headline=f"{f.form_type}: {f.title}",
                    body=None,
                    published_at=f.filed_at,
                    url=f.url,
                    article_id=f.accession_no,
                    author="SEC EDGAR",
                    tags=[f.form_type],
                    extra={"form_type": f.form_type, "cik": f.cik},
                ))
            except Exception as e:                            # noqa: BLE001
                logger.warning("edgar coerce failed for %s: %s", symbol, e)
        return items
