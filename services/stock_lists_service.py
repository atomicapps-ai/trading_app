"""Stock lists — curated and dynamic ticker collections.

Defaults are seeded on first startup. Each list has a `source_type` indicating
where its tickers come from:

  - `wikipedia` — scraped from a Wikipedia constituents page (S&P 500, etc.)
  - `static`    — hardcoded ticker list (Magnificent 7, FAANG, sector ETFs)

`refresh_list(slug)` re-fetches dynamic sources. Static lists are no-ops on
refresh (their tickers don't change without code edit).

We intentionally start small: 10 well-known lists, all with verified working
sources. Adding more is trivial — append to `_DEFAULTS`.
"""
from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite
import httpx

from services.settings_service import LOCAL_DB_PATH as DB_PATH

logger = logging.getLogger(__name__)

# Wikipedia is strict about UAs — they want something descriptive that
# identifies the project and a contact. A bare "TradeAgent/1.0" gets a 403.
_HEADERS = {
    "User-Agent": "TradeAgent/1.0 (https://github.com/devguyjk/trading_app; local-personal-use) httpx",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# --------------------------------------------------------------------------- #
# Default catalog — 10 commonly-used lists, all sourced from public data
# --------------------------------------------------------------------------- #


_DEFAULTS: list[dict[str, Any]] = [
    {
        "slug": "sp500",
        "name": "S&P 500",
        "description": "500 large-cap U.S. companies; the broadest large-cap index.",
        "source_type": "wikipedia",
        "source_url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "wiki_table": 0,
        "wiki_col": "Symbol",
    },
    {
        "slug": "nasdaq100",
        "name": "NASDAQ-100",
        "description": "100 largest non-financial companies on the NASDAQ.",
        "source_type": "wikipedia",
        "source_url": "https://en.wikipedia.org/wiki/Nasdaq-100",
        "wiki_table": 5,
        "wiki_col": "Ticker",
    },
    {
        "slug": "dow30",
        "name": "Dow Jones Industrial Average (Dow 30)",
        "description": "Price-weighted index of 30 prominent U.S. companies.",
        "source_type": "wikipedia",
        "source_url": "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average",
        "wiki_table": 1,
        "wiki_col": "Symbol",
    },
    {
        "slug": "sp400",
        "name": "S&P 400 (Mid-Cap)",
        "description": "400 mid-capitalization U.S. companies.",
        "source_type": "wikipedia",
        "source_url": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
        "wiki_table": 0,
        "wiki_col": "Symbol",
    },
    {
        "slug": "sp600",
        "name": "S&P 600 (Small-Cap)",
        "description": "600 small-capitalization U.S. companies.",
        "source_type": "wikipedia",
        "source_url": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
        "wiki_table": 0,
        "wiki_col": "Symbol",
    },
    {
        "slug": "magnificent7",
        "name": "Magnificent 7",
        "description": "The seven mega-cap tech stocks driving most index returns.",
        "source_type": "static",
        "source_url": "",
        "static_tickers": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"],
    },
    {
        "slug": "faang",
        "name": "FAANG",
        "description": "Original FAANG: Facebook (Meta), Apple, Amazon, Netflix, Google.",
        "source_type": "static",
        "source_url": "",
        "static_tickers": ["META", "AAPL", "AMZN", "NFLX", "GOOGL"],
    },
    {
        "slug": "spdr_sectors",
        "name": "SPDR Sector ETFs",
        "description": "11 SPDR sector ETFs covering the full GICS sector breakdown.",
        "source_type": "static",
        "source_url": "",
        "static_tickers": ["XLK", "XLV", "XLF", "XLY", "XLC", "XLI", "XLP", "XLE", "XLU", "XLRE", "XLB"],
    },
    {
        "slug": "ai_leaders",
        "name": "AI Leaders",
        "description": "Companies most exposed to AI buildout (chips, cloud, AI services).",
        "source_type": "static",
        "source_url": "",
        "static_tickers": ["NVDA", "MSFT", "GOOGL", "AMZN", "META", "AMD", "TSM", "AVGO", "PLTR", "ORCL", "SMCI", "ARM"],
    },
    {
        "slug": "crypto_adjacent",
        "name": "Crypto-Adjacent Equities",
        "description": "Public stocks with material crypto exposure (miners, custodians, holders).",
        "source_type": "static",
        "source_url": "",
        "static_tickers": ["COIN", "MSTR", "MARA", "RIOT", "HUT", "CLSK", "BITF", "HIVE", "WULF", "CIFR"],
    },
]


# --------------------------------------------------------------------------- #
# Wikipedia fetching
# --------------------------------------------------------------------------- #


def _fetch_wiki_tickers(url: str, table_idx: int, col_hint: str) -> list[str]:
    """Sync helper — pulls a Wikipedia page and parses the constituents table.

    Returns a deduplicated, uppercased list of tickers.
    """
    import pandas as pd

    r = httpx.get(url, headers=_HEADERS, timeout=20.0, follow_redirects=True)
    r.raise_for_status()
    tables = pd.read_html(io.StringIO(r.text))
    if table_idx >= len(tables):
        raise ValueError(f"table index {table_idx} out of range ({len(tables)} tables)")
    df = tables[table_idx]
    # Match column case-insensitively
    actual = next(
        (c for c in df.columns if str(c).lower().startswith(col_hint.lower())),
        None,
    )
    if not actual:
        raise ValueError(f"no column starting with {col_hint!r}; cols={list(df.columns)}")
    raw = df[actual].dropna().astype(str).tolist()
    # Wikipedia sometimes has Yahoo-format suffixes (BRK.B vs BRK-B); leave as-is
    seen, out = set(), []
    for s in raw:
        s = s.strip().upper()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# --------------------------------------------------------------------------- #
# DB CRUD
# --------------------------------------------------------------------------- #


async def list_all() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM stock_lists ORDER BY name ASC")
        rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def get(slug: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM stock_lists WHERE slug = ?", (slug,))
        row = await cur.fetchone()
    return _row_to_dict(row) if row else None


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["tickers"] = json.loads(d.pop("tickers_json") or "[]")
    return d


async def upsert_list(
    slug: str,
    *,
    name: str,
    description: str,
    source_type: str,
    source_url: str,
    tickers: list[str],
    refreshed: bool = True,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO stock_lists
                (slug, name, description, source_type, source_url,
                 tickers_json, ticker_count, last_refreshed_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                source_type = excluded.source_type,
                source_url = excluded.source_url,
                tickers_json = excluded.tickers_json,
                ticker_count = excluded.ticker_count,
                last_refreshed_at = excluded.last_refreshed_at
            """,
            (slug, name, description, source_type, source_url,
             json.dumps(tickers), len(tickers),
             now if refreshed else None, now),
        )
        await db.commit()


# --------------------------------------------------------------------------- #
# Public ops
# --------------------------------------------------------------------------- #


async def seed_defaults() -> int:
    """Insert any default lists not yet in the DB. Returns count inserted."""
    existing = {r["slug"] for r in await list_all()}
    inserted = 0
    for d in _DEFAULTS:
        if d["slug"] in existing:
            continue
        # Static lists get their tickers immediately
        tickers = d.get("static_tickers", [])
        await upsert_list(
            d["slug"],
            name=d["name"],
            description=d["description"],
            source_type=d["source_type"],
            source_url=d["source_url"],
            tickers=tickers,
            refreshed=bool(tickers),  # static => already populated
        )
        inserted += 1
    if inserted:
        logger.info("stock_lists_service: seeded %d default lists", inserted)
    return inserted


async def refresh(slug: str) -> dict:
    """Re-fetch a list's source and update the DB.

    For static lists this is a no-op (no source to refresh from).
    Returns the updated list dict.
    """
    record = await get(slug)
    if not record:
        # Try seeding from defaults if we have a matching default
        d = next((x for x in _DEFAULTS if x["slug"] == slug), None)
        if not d:
            raise KeyError(f"unknown stock list: {slug}")
        await seed_defaults()
        record = await get(slug)
        if not record:
            raise RuntimeError(f"failed to seed {slug}")

    src_type = record.get("source_type", "static")
    src_default = next((x for x in _DEFAULTS if x["slug"] == slug), None)

    if src_type == "wikipedia":
        if not src_default:
            raise RuntimeError(f"no default config for wikipedia list {slug}")
        # yfinance / pandas / httpx are sync — run in a thread
        import asyncio
        tickers = await asyncio.to_thread(
            _fetch_wiki_tickers,
            src_default["source_url"],
            src_default["wiki_table"],
            src_default["wiki_col"],
        )
        await upsert_list(
            slug,
            name=record["name"],
            description=record["description"],
            source_type=src_type,
            source_url=record["source_url"],
            tickers=tickers,
            refreshed=True,
        )
        logger.info("refresh(%s): %d tickers from Wikipedia", slug, len(tickers))
        return await get(slug) or {}

    if src_type == "static":
        # Refresh static lists from defaults so code-level edits propagate
        if src_default and src_default.get("static_tickers"):
            await upsert_list(
                slug,
                name=record["name"],
                description=record["description"],
                source_type=src_type,
                source_url=record["source_url"],
                tickers=src_default["static_tickers"],
                refreshed=True,
            )
        return await get(slug) or {}

    raise NotImplementedError(f"refresh not implemented for source_type={src_type!r}")
