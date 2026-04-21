"""news_service.py — time-scoped news + filings access layer.

Single source of truth for news across live and backtest. Every lens
reads through this module — no HTTP clients anywhere else in the
analyst code. The `as_of_ts` parameter makes the whole layer safe
for Phase 5 backtest replay: given a historical timestamp, return
only items with `published_at <= as_of_ts`.

Sources
-------
Alpaca News (primary)
    - alpaca-py `NewsClient` against the Benzinga-sourced feed.
    - Archive runs roughly 2015 → present, hourly granularity.
    - No daily call cap; we self-throttle with ALPACA_NEWS_DELAY_SECONDS.
    - Requires ALPACA_API_KEY + ALPACA_API_SECRET in .env. Free account.

SEC EDGAR (filings only, not general news)
    - Atom feed via feedparser.
    - Ticker → CIK lookup seeded from the SEC's company-tickers JSON;
      cached at data/edgar_cik_map.json.
    - SEC asks for a real User-Agent with a contact email.

Caching
-------
Alpaca news: per-(symbol, UTC-date) JSONL at
    data/news_cache/{SYMBOL}/{YYYY-MM-DD}.jsonl

    - A file means "we've fetched this date fully." Present = trust cache,
      missing = fetch.
    - "Today" (UTC) is never trusted — always refetched, never cached to
      disk — because partial-day data would poison future backtests.

EDGAR filings: one file per symbol at
    data/edgar_cache/{SYMBOL}.jsonl (append-only, dedupe on accession_no).

The cache is what makes Phase 5 news-aware backtesting cheap: a
10-year replay across a 50-symbol shortlist touches ~130k daily files,
each read once, no API calls after the first warm-up pass.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Literal

import feedparser
import httpx
import pandas as pd
from pydantic import BaseModel, ConfigDict

from services.settings_service import DATA_DIR

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Paths + constants
# --------------------------------------------------------------------------- #

NEWS_CACHE_DIR: Path = DATA_DIR / "news_cache"
EDGAR_CACHE_DIR: Path = DATA_DIR / "edgar_cache"
EDGAR_CIK_MAP_PATH: Path = DATA_DIR / "edgar_cik_map.json"

_SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_EDGAR_ATOM = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include"
    "&count=40&output=atom"
)

# SEC requires a real UA with contact info. Pulled from env so users
# set their own email rather than blasting SEC with a generic default.
_SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "TradeAgent/0.1 (contact: set SEC_USER_AGENT in .env)",
)

_ALPACA_NEWS_DELAY_SECONDS = float(os.environ.get("ALPACA_NEWS_DELAY_SECONDS", "0.25"))
_EDGAR_DELAY_SECONDS = 1.0

DEFAULT_NEWS_LOOKBACK_HOURS = 72
DEFAULT_FILINGS_LOOKBACK_DAYS = 14
DEFAULT_FILING_FORMS: tuple[str, ...] = ("8-K", "10-Q", "10-K")


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


class NewsItem(BaseModel):
    """One normalized news article, cache- and backtest-friendly."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: Literal["alpaca", "edgar"]
    symbol: str
    headline: str
    body: str | None = None
    published_at: datetime  # UTC-aware
    url: str
    article_id: str  # source-specific unique id (Alpaca item id, EDGAR accession_no)
    author: str | None = None


class Filing(BaseModel):
    """One SEC filing (8-K, 10-Q, 10-K)."""

    symbol: str
    cik: str
    form_type: str
    filed_at: datetime  # UTC-aware
    url: str
    title: str
    accession_no: str


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #


def _to_utc(ts: datetime | pd.Timestamp | None) -> datetime | None:
    """Coerce to tz-aware UTC datetime. None-in → None-out."""
    if ts is None:
        return None
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    return t.to_pydatetime()


def _window_bounds(
    as_of_ts: datetime | pd.Timestamp | None,
    lookback_hours: int,
) -> tuple[datetime, datetime]:
    """Return (start, end) in UTC for a lookback-from-as-of window."""
    end = _to_utc(as_of_ts) or datetime.now(timezone.utc)
    start = end - timedelta(hours=lookback_hours)
    return start, end


def _dates_in_range(start: datetime, end: datetime) -> list[str]:
    """YYYY-MM-DD strings (UTC) for every day touched by [start, end]."""
    d = start.astimezone(timezone.utc).date()
    last = end.astimezone(timezone.utc).date()
    out: list[str] = []
    while d <= last:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _today_utc_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# --------------------------------------------------------------------------- #
# Alpaca news — client wiring + cache helpers
# --------------------------------------------------------------------------- #


def _alpaca_client():
    """Build a NewsClient lazily. Returns None if credentials are missing
    — lenses should treat 'no news' as a valid outcome, not a crash."""
    try:
        from alpaca.data.historical.news import NewsClient  # type: ignore
    except ImportError:
        log.warning("alpaca-py not installed; Alpaca news disabled")
        return None

    key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_API_SECRET")
    if not key or not secret:
        log.warning("ALPACA_API_KEY / ALPACA_API_SECRET missing; Alpaca news disabled")
        return None
    return NewsClient(api_key=key, secret_key=secret)


def _alpaca_cache_path(symbol: str, date_iso: str) -> Path:
    return NEWS_CACHE_DIR / symbol.upper() / f"{date_iso}.jsonl"


def _read_news_cache_sync(symbol: str, date_iso: str) -> list[NewsItem]:
    path = _alpaca_cache_path(symbol, date_iso)
    if not path.exists():
        return []
    out: list[NewsItem] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(NewsItem.model_validate_json(line))
            except Exception as e:
                log.warning("corrupt news cache line in %s: %s", path, e)
    return out


def _write_news_cache_sync(symbol: str, date_iso: str, items: list[NewsItem]) -> None:
    """Overwrite the date-bucket file with `items`. Assumes the caller
    fetched the full day (otherwise callers would need to merge)."""
    path = _alpaca_cache_path(symbol, date_iso)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(item.model_dump_json())
            f.write("\n")


def _alpaca_item_to_news(item, default_symbol: str) -> NewsItem | None:
    """Convert an alpaca-py news object into our NewsItem. Returns None
    if the item lacks the fields we need (defensive — the SDK shape has
    shifted between versions)."""
    try:
        # alpaca-py returns objects with attributes; stay duck-typed.
        headline = getattr(item, "headline", None) or ""
        body = getattr(item, "content", None) or getattr(item, "summary", None)
        url = getattr(item, "url", "") or ""
        author = getattr(item, "author", None)
        item_id = getattr(item, "id", None)
        created = getattr(item, "created_at", None) or getattr(item, "updated_at", None)
        symbols = getattr(item, "symbols", None) or [default_symbol]

        if not headline or created is None or item_id is None:
            return None

        published = _to_utc(created)
        if published is None:
            return None

        # Pick the most specific symbol tag that matches our query.
        sym = (default_symbol.upper()
               if default_symbol.upper() in {s.upper() for s in symbols}
               else str(symbols[0]).upper())

        return NewsItem(
            source="alpaca",
            symbol=sym,
            headline=headline,
            body=body,
            published_at=published,
            url=url,
            article_id=str(item_id),
            author=author,
        )
    except Exception as e:  # defensive
        log.warning("failed to normalize alpaca news item: %s", e)
        return None


def _fetch_alpaca_sync(
    symbol: str,
    start: datetime,
    end: datetime,
) -> list[NewsItem]:
    """Single blocking fetch of Alpaca news for one symbol in one window."""
    client = _alpaca_client()
    if client is None:
        return []

    from alpaca.data.requests import NewsRequest  # type: ignore

    req = NewsRequest(
        symbols=[symbol.upper()],
        start=start,
        end=end,
        include_content=True,
        limit=50,
    )
    try:
        resp = client.get_news(req)
    except Exception as e:
        log.warning("Alpaca get_news failed for %s [%s, %s]: %s",
                    symbol, start, end, e)
        return []

    # The SDK returns a NewsSet-like object with a `.news` list, OR a
    # dict-shaped response keyed by symbol. Handle both defensively.
    raw_items: Iterable = ()
    if hasattr(resp, "news"):
        raw_items = resp.news  # type: ignore[attr-defined]
    elif hasattr(resp, "data"):
        d = resp.data  # type: ignore[attr-defined]
        raw_items = d.get(symbol.upper(), []) if isinstance(d, dict) else d
    elif isinstance(resp, dict):
        raw_items = resp.get(symbol.upper(), [])

    out: list[NewsItem] = []
    for raw in raw_items:
        item = _alpaca_item_to_news(raw, symbol)
        if item is not None:
            out.append(item)
    return out


def _bucket_by_date(items: list[NewsItem]) -> dict[str, list[NewsItem]]:
    buckets: dict[str, list[NewsItem]] = {}
    for it in items:
        d = it.published_at.astimezone(timezone.utc).date().isoformat()
        buckets.setdefault(d, []).append(it)
    return buckets


# --------------------------------------------------------------------------- #
# EDGAR — CIK map + filings
# --------------------------------------------------------------------------- #


def _load_cik_map_sync() -> dict[str, str]:
    """Return {TICKER: CIK} with CIKs zero-padded to 10 chars."""
    if EDGAR_CIK_MAP_PATH.exists():
        try:
            return json.loads(EDGAR_CIK_MAP_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("corrupt edgar_cik_map.json (%s); re-downloading", e)

    log.info("downloading SEC ticker→CIK map from %s", _SEC_TICKER_MAP_URL)
    try:
        resp = httpx.get(
            _SEC_TICKER_MAP_URL,
            headers={"User-Agent": _SEC_USER_AGENT},
            timeout=30.0,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        log.warning("could not download SEC ticker map: %s", e)
        return {}

    # The SEC JSON is keyed by numeric index; values have ticker + cik_str.
    out: dict[str, str] = {}
    for row in raw.values():
        try:
            out[str(row["ticker"]).upper()] = str(row["cik_str"]).zfill(10)
        except (KeyError, TypeError):
            continue

    EDGAR_CIK_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    EDGAR_CIK_MAP_PATH.write_text(json.dumps(out), encoding="utf-8")
    log.info("wrote %d ticker→CIK mappings → %s", len(out), EDGAR_CIK_MAP_PATH.name)
    return out


def _edgar_cache_path(symbol: str) -> Path:
    return EDGAR_CACHE_DIR / f"{symbol.upper()}.jsonl"


def _read_edgar_cache_sync(symbol: str) -> list[Filing]:
    path = _edgar_cache_path(symbol)
    if not path.exists():
        return []
    out: list[Filing] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(Filing.model_validate_json(line))
            except Exception as e:
                log.warning("corrupt edgar cache line in %s: %s", path, e)
    return out


def _merge_edgar_cache_sync(symbol: str, new: list[Filing]) -> list[Filing]:
    """Append-only merge with dedupe on accession_no. Returns full cache."""
    existing = _read_edgar_cache_sync(symbol)
    seen = {f.accession_no for f in existing}
    added = [f for f in new if f.accession_no not in seen]
    if not added:
        return existing

    path = _edgar_cache_path(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for filing in added:
            f.write(filing.model_dump_json())
            f.write("\n")
    return existing + added


def _fetch_edgar_sync(
    symbol: str,
    form_types: tuple[str, ...],
    cik_map: dict[str, str],
) -> list[Filing]:
    """Hit the SEC atom feed for each form type. Polite 1s delay between."""
    cik = cik_map.get(symbol.upper())
    if not cik:
        log.debug("no CIK for %s; skipping EDGAR", symbol)
        return []

    out: list[Filing] = []
    headers = {"User-Agent": _SEC_USER_AGENT}
    for i, form in enumerate(form_types):
        if i > 0:
            import time
            time.sleep(_EDGAR_DELAY_SECONDS)
        url = _SEC_EDGAR_ATOM.format(cik=cik, form=form)
        try:
            # feedparser does its own HTTP — pass UA via request_headers.
            feed = feedparser.parse(url, request_headers=headers)
        except Exception as e:
            log.warning("EDGAR fetch failed for %s %s: %s", symbol, form, e)
            continue

        for entry in feed.entries:
            try:
                accession = (entry.get("id") or "").split("accession-number=")[-1].strip()
                updated = entry.get("updated") or entry.get("published")
                filed_at = _to_utc(pd.Timestamp(updated)) if updated else None
                if filed_at is None or not accession:
                    continue
                out.append(Filing(
                    symbol=symbol.upper(),
                    cik=cik,
                    form_type=form,
                    filed_at=filed_at,
                    url=entry.get("link", ""),
                    title=entry.get("title", ""),
                    accession_no=accession,
                ))
            except Exception as e:
                log.warning("EDGAR parse error for %s %s: %s", symbol, form, e)
                continue

    return out


# --------------------------------------------------------------------------- #
# Public async API — news
# --------------------------------------------------------------------------- #


async def get_news(
    symbol: str,
    as_of_ts: datetime | pd.Timestamp | None = None,
    lookback_hours: int = DEFAULT_NEWS_LOOKBACK_HOURS,
) -> list[NewsItem]:
    """Return Alpaca news for `symbol` in the window
    [as_of_ts - lookback_hours, as_of_ts].

    `as_of_ts=None` means "live / now". Any item with
    `published_at > as_of_ts` is filtered out — the caller can never
    see future news.

    Cache: per (symbol, UTC date) JSONL files under data/news_cache/.
    Cached days are trusted; today (UTC) is always refetched.
    """
    symbol = symbol.upper()
    start, end = _window_bounds(as_of_ts, lookback_hours)
    today = _today_utc_iso()
    dates = _dates_in_range(start, end)

    # Partition: cached vs needs-fetch.
    # "today" is never trusted — always counted as needs-fetch.
    cached: list[NewsItem] = []
    missing_dates: list[str] = []
    for d in dates:
        if d == today:
            missing_dates.append(d)
            continue
        path = _alpaca_cache_path(symbol, d)
        if path.exists():
            cached.extend(await asyncio.to_thread(_read_news_cache_sync, symbol, d))
        else:
            missing_dates.append(d)

    # Fetch the missing range in a single API call, then bucket + cache.
    fetched: list[NewsItem] = []
    if missing_dates:
        m_start = max(
            start,
            datetime.fromisoformat(missing_dates[0]).replace(tzinfo=timezone.utc),
        )
        m_end = min(
            end,
            datetime.fromisoformat(missing_dates[-1]).replace(tzinfo=timezone.utc)
            + timedelta(days=1),
        )
        fetched = await asyncio.to_thread(_fetch_alpaca_sync, symbol, m_start, m_end)
        if _ALPACA_NEWS_DELAY_SECONDS > 0:
            await asyncio.sleep(_ALPACA_NEWS_DELAY_SECONDS)

        # Bucket by date; persist every bucket *except* today (partial day).
        buckets = _bucket_by_date(fetched)
        for d in missing_dates:
            if d == today:
                continue
            await asyncio.to_thread(
                _write_news_cache_sync, symbol, d, buckets.get(d, [])
            )

    combined = cached + fetched

    # Hard filter: window + as_of_ts safety slice + dedupe.
    seen: set[str] = set()
    out: list[NewsItem] = []
    for it in combined:
        if it.published_at < start or it.published_at > end:
            continue
        if it.article_id in seen:
            continue
        seen.add(it.article_id)
        out.append(it)

    out.sort(key=lambda n: n.published_at)
    return out


async def get_news_multi(
    symbols: list[str],
    as_of_ts: datetime | pd.Timestamp | None = None,
    lookback_hours: int = DEFAULT_NEWS_LOOKBACK_HOURS,
) -> dict[str, list[NewsItem]]:
    """Batch news fetch. Per-symbol errors are logged and the symbol
    returns []. Never raises, so one bad symbol doesn't kill the run."""

    async def _one(sym: str) -> tuple[str, list[NewsItem]]:
        try:
            items = await get_news(sym, as_of_ts=as_of_ts, lookback_hours=lookback_hours)
            return sym.upper(), items
        except Exception as e:
            log.exception("get_news_multi: %s failed: %s", sym, e)
            return sym.upper(), []

    pairs = await asyncio.gather(*(_one(s) for s in symbols))
    return dict(pairs)


# --------------------------------------------------------------------------- #
# Public async API — filings
# --------------------------------------------------------------------------- #


async def get_filings(
    symbol: str,
    as_of_ts: datetime | pd.Timestamp | None = None,
    lookback_days: int = DEFAULT_FILINGS_LOOKBACK_DAYS,
    form_types: tuple[str, ...] = DEFAULT_FILING_FORMS,
) -> list[Filing]:
    """Return EDGAR filings for `symbol` in the trailing `lookback_days` window.

    Semantics mirror `get_news`: `as_of_ts=None` → now; items with
    `filed_at > as_of_ts` are dropped; cache under data/edgar_cache/.

    Cache is append-only with dedupe on accession_no — EDGAR's atom
    feed is monotonic, so a single refresh extends the archive safely.
    """
    symbol = symbol.upper()
    start, end = _window_bounds(as_of_ts, lookback_hours=lookback_days * 24)

    cik_map = await asyncio.to_thread(_load_cik_map_sync)

    # Always hit the feed for freshness (EDGAR is low-volume; cheap).
    # Merge into cache, then filter from the combined archive.
    fetched = await asyncio.to_thread(_fetch_edgar_sync, symbol, form_types, cik_map)
    all_filings = await asyncio.to_thread(_merge_edgar_cache_sync, symbol, fetched)

    out = [
        f for f in all_filings
        if start <= f.filed_at <= end and f.form_type in form_types
    ]
    out.sort(key=lambda f: f.filed_at)
    return out
