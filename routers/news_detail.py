"""News detail router — `/news/{source}/{article_id}` shows one article.

Implementation strategy: re-fetch from the source rather than caching
the full body. The Alpaca cache holds the body already; EDGAR/Webull
re-fetch on demand. For symbol-less id lookups we lean on the per-source
``article_id`` being globally unique within that source.

Why a server-side detail page instead of just opening the source URL?
* Consistent dark-theme rendering across providers (some source pages
  are awful on mobile or load 30s of trackers).
* VADER sentiment scoring + tags surfaced in one place.
* "Open original ↗" button still ships the user to the source if they
  want the canonical view.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services import news_service, sentiment_service, widget_settings as ws
from services.news_sources import default_enabled_source_ids
from services.settings_service import TEMPLATES_DIR, Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/news/{source}/{article_id:path}", response_class=HTMLResponse)
async def news_detail(
    source: str, article_id: str, request: Request,
    symbol: str | None = None,
    s: Settings = Depends(get_settings),
):
    """One article's full detail.

    ``symbol`` is optional — most callers (the news card on /trades/{id}
    and the headlines widget) pass ?symbol=… so we can re-fetch quickly.
    Without it we still try the article_id against a small bellwether
    set; if that fails we 404 with a "couldn't relocate" message rather
    than a generic stack trace.
    """
    # Honor the user's enabled-sources list — if they've turned a source
    # off we still let them open detail pages for already-rendered items
    # (the link was on the page before the toggle), but we mark it.
    enabled = await ws.get_with_default(
        "default", "market_headlines", "enabled_sources",
        default_enabled_source_ids(),
    )

    candidate_symbols = [symbol] if symbol else [
        # Pragmatic fallback — match the default headlines watchlist.
        "SPY", "QQQ", "AAPL", "NVDA", "MSFT", "TSLA", "AMZN", "META",
    ]

    found = None
    for sym in candidate_symbols:
        if not sym:
            continue
        try:
            items = await news_service.get_news_multi_source(
                sym, source_ids=[source], lookback_hours=168,
            )
        except Exception as e:                                # noqa: BLE001
            logger.warning("news_detail re-fetch %s/%s for %s failed: %s",
                           source, article_id, sym, e)
            items = []
        for it in items:
            if it.article_id == article_id:
                found = it
                break
        if found:
            break

    if not found:
        raise HTTPException(
            404,
            f"Couldn't locate article {article_id!r} from source "
            f"{source!r}. The provider may have rotated it out of the "
            f"recent window — try the original link from the listing.",
        )

    score = sentiment_service.score_news_item(found).to_dict()

    # If the source flagged the body as HTML, sanitize before rendering
    # — the template uses ``|safe`` only after this allowlist scrub.
    # Plain-text bodies pass through untouched and Jinja escapes them
    # in the normal way.
    if found.body and found.body_format == "html":
        found.body = news_service.sanitize_html(found.body)

    return templates.TemplateResponse(
        request=request,
        name="news/detail.html",
        context={
            "settings": s,
            "active_page": "trades",
            "app_version": "0.1.0",
            "item": found,
            "sentiment": score,
            "source_enabled": source in set(enabled or []),
        },
    )
