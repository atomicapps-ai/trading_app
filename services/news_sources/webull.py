"""Webull News source — retail sentiment angle.

Endpoint: GET https://api.webull.com/quotes/ticker/news
Auth: ``WEBULL_ACCESS_TOKEN`` env var passed in the request header.
      (Webull rolled out App Key/Secret auth in 2026; the token is
      typically obtained out-of-band from the developer console and
      pasted into .env.)

Why we want this: Webull's news feed often carries social tags and
"hot" / trending indicators that the Benzinga-sourced Alpaca feed
doesn't have. We surface both in the unified stream and tag the
Webull items with whatever extras the response includes (passed
through to NewsItem.extra so the detail view can show them).

Defensive shape handling
------------------------
The Webull endpoint isn't formally documented and has shifted across
versions. We accept the response under any of these top-level shapes:
    - ``{"newsList": [...]}``     (most common)
    - ``{"data": [...]}``
    - ``[...]``                    (bare array)
…and within each item, look for the headline / link / timestamp under
several common key names. Any item that fails to parse is skipped with
a warning rather than failing the whole fetch.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pandas as pd

from services.news_sources.base import NewsSource

logger = logging.getLogger(__name__)

_WEBULL_NEWS_URL = "https://api.webull.com/quotes/ticker/news"
_DEFAULT_TIMEOUT = 15.0
_DEFAULT_PAGE_SIZE = 50


def _to_utc(ts) -> datetime | None:
    """Convert anything timestamp-shaped to a UTC-aware datetime, or None."""
    if ts is None or ts == "":
        return None
    try:
        # Numeric epoch (Webull often uses seconds, sometimes ms).
        if isinstance(ts, (int, float)) or (isinstance(ts, str) and ts.isdigit()):
            n = float(ts)
            if n > 1e12:           # ms epoch
                n = n / 1000.0
            return datetime.fromtimestamp(n, tz=timezone.utc)
        # ISO-ish strings — pandas handles a wide variety
        t = pd.Timestamp(ts)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        else:
            t = t.tz_convert("UTC")
        return t.to_pydatetime()
    except Exception:                                          # noqa: BLE001
        return None


def _pick(d: dict, *keys: str) -> Any:
    """Return the first non-empty value among ``keys`` in ``d``."""
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


class WebullNewsSource(NewsSource):
    id = "webull"
    label = "Webull News"
    enabled_by_default = False    # off by default until user adds the token
    requires_credentials = ("WEBULL_ACCESS_TOKEN",)

    async def fetch(self, symbol: str, lookback_hours: int):
        from services.news_service import NewsItem

        token = os.environ.get("WEBULL_ACCESS_TOKEN")
        if not token:
            return []

        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=lookback_hours)

        # Webull's endpoint typically takes ``symbol`` (uppercase) — some
        # builds expect a numeric tickerId instead. We try ``symbol``
        # first since it matches what the user passes. If a deployment
        # needs tickerId it can be swapped in here without touching
        # callers.
        params = {"symbol": symbol.upper(), "pageSize": _DEFAULT_PAGE_SIZE}
        headers = {
            "access_token": token,         # documented form for the 2026 auth scheme
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "TradeAgent/0.1 (+webull news consumer)",
        }
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                r = await client.get(_WEBULL_NEWS_URL, params=params, headers=headers)
                if r.status_code == 401:
                    logger.warning("webull news 401 — check WEBULL_ACCESS_TOKEN")
                    return []
                if r.status_code != 200:
                    logger.warning("webull news %s for %s: %s",
                                   r.status_code, symbol, r.text[:200])
                    return []
                payload = r.json()
        except Exception as e:                                 # noqa: BLE001
            logger.warning("webull news fetch raised for %s: %s", symbol, e)
            return []

        # Tolerate the three response shapes we've seen in the wild.
        if isinstance(payload, dict):
            raw_items = payload.get("newsList") or payload.get("data") or []
        elif isinstance(payload, list):
            raw_items = payload
        else:
            raw_items = []

        items: list[NewsItem] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            try:
                headline = _pick(raw, "title", "headline", "newsTitle")
                published = _to_utc(
                    _pick(raw, "newsTime", "publishTime", "createTime",
                          "publishedAt", "time")
                )
                if not headline or published is None:
                    continue
                if published < start or published > end:
                    continue   # drop items outside the window

                url = _pick(raw, "newsUrl", "url", "link", "sourceUrl") or ""
                article_id = str(_pick(raw, "id", "newsId", "uuid")
                                 or f"{symbol}-{int(published.timestamp())}")
                author = _pick(raw, "sourceName", "source", "author")
                summary = _pick(raw, "summary", "description", "abstract")
                image_url = _pick(raw, "imageUrl", "mainPic", "thumbnail")

                # Webull's secret sauce — surface social/hot signals as tags
                tags: list[str] = []
                if raw.get("hot"):
                    tags.append("hot")
                if raw.get("trending"):
                    tags.append("trending")
                explicit_tags = raw.get("tags") or raw.get("labels") or []
                if isinstance(explicit_tags, list):
                    tags.extend(str(t) for t in explicit_tags if t)

                # Anything else in the raw item — preserve under .extra so
                # the detail view can render the unique-value bits Webull
                # provides without us re-modelling them all.
                extra = {
                    k: v for k, v in raw.items()
                    if k not in {"title", "headline", "newsTitle",
                                 "newsTime", "publishTime", "createTime",
                                 "publishedAt", "time",
                                 "newsUrl", "url", "link", "sourceUrl",
                                 "id", "newsId", "uuid",
                                 "sourceName", "source", "author",
                                 "summary", "description", "abstract",
                                 "imageUrl", "mainPic", "thumbnail",
                                 "hot", "trending", "tags", "labels"}
                    and not (isinstance(v, (dict, list)) and len(v) > 50)
                }

                # Some Webull builds return content under "content" /
                # "newsContent". Detect HTML so the detail view formats
                # it correctly.
                from services.news_service import looks_like_html
                body = _pick(raw, "content", "newsContent", "fullText")
                body_str = str(body) if body else None
                body_format = (
                    "html" if (body_str and looks_like_html(body_str)) else "text"
                )

                items.append(NewsItem(
                    source="webull",
                    symbol=symbol.upper(),
                    headline=str(headline),
                    body=body_str,
                    body_format=body_format,
                    published_at=published,
                    url=str(url),
                    article_id=article_id,
                    author=str(author) if author else None,
                    summary=str(summary) if summary else None,
                    image_url=str(image_url) if image_url else None,
                    tags=tags,
                    extra=extra,
                ))
            except Exception as e:                             # noqa: BLE001
                logger.warning("webull item parse failed for %s: %s", symbol, e)
        return items
