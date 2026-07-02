"""Dashboard widget registry — modular monitoring tiles.

Each dashboard "widget" is a small subclass that knows:
  * its visual size in the grid
  * how often it should refresh
  * how to fetch its own data
  * which template partial to render

The dashboard route iterates ``WIDGETS`` and emits an HTMX-driven
placeholder per widget; the dispatcher endpoint
``GET /api/dashboard/widgets/{widget_id}`` calls the matching widget's
``get_data()`` and renders its partial.

To add a widget:
    1. Subclass Widget, fill in ``id``/``title``/``size``/``refresh_seconds``
       and override ``async def get_data() -> dict``.
    2. Drop a partial at ``templates/dashboard/widgets/{id}.html``.
    3. Append the new instance to ``WIDGETS`` below.

That's the whole flow — no router or parent-template edits.

Refresh semantics
-----------------
Widgets use HTMX ``hx-trigger="load, every Ns"`` (option iii from the
session design). Refresh interval per widget is taken from
``refresh_seconds`` and rendered into the grid markup. Slow-moving data
sources (Fear/Greed, daily indicators) use long intervals (15-30 min);
fast-moving data (live quotes) uses 30-60s.
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal

import httpx
import pandas as pd
import yaml

from services.data_service import DataNotAvailableError, get_bars
from services.settings_service import PROJECT_ROOT, STRATEGY_CONFIG_DIR

logger = logging.getLogger(__name__)

WidgetSize = Literal["sm", "md", "lg", "wide"]
WidgetTab  = Literal["portfolio", "market", "news"]


# Default tab ordering — also used by the dashboard template to render
# the tab nav. Add entries here when new tabs are introduced.
TAB_ORDER: list[tuple[WidgetTab, str]] = [
    ("portfolio", "Portfolio"),
    ("market",    "Market"),
    ("news",      "News"),
]


# --------------------------------------------------------------------------- #
# Base class
# --------------------------------------------------------------------------- #


class Widget(ABC):
    """Base widget contract.

    Subclasses set the four class attributes and implement ``get_data``.
    The dispatcher renders ``templates/dashboard/widgets/{id}.html`` with
    whatever dict ``get_data`` returns (plus ``request`` from the route).

    User-configurable widgets
    -------------------------
    Set ``user_configurable = True`` and populate ``settings_schema`` to
    expose a settings panel (⚙ icon in widget header). The schema is a
    dict mapping ``setting_key -> {type, default, label, help, choices?}``.

    Example:
        settings_schema = {
            "indicator_ids": {
                "type":  "indicator_multiselect",
                "label": "Indicators",
                "default": ["sma_20", "sma_50"],
            },
        }

    User overrides are persisted via ``services.widget_settings`` (SQLite).
    Reads at request time go through ``await self.resolve_settings()``,
    which returns the merged user-override-or-default dict.
    """

    id: str = ""
    title: str = ""
    size: WidgetSize = "md"
    tab: WidgetTab = "market"          # which top-level tab the widget lives under
    refresh_seconds: int = 30
    enabled: bool = True

    # Settings layer — only matters for user-configurable widgets.
    # ``user_configurable`` controls UI affordances (⚙ icon, settings modal).
    # ``settings_schema`` declares the configurable keys + their defaults.
    user_configurable: bool = False
    settings_schema: dict[str, dict[str, Any]] = {}

    @abstractmethod
    async def get_data(self) -> dict[str, Any]:
        """Return the template context for the widget partial."""
        raise NotImplementedError

    @property
    def template(self) -> str:
        return f"dashboard/widgets/{self.id}.html"

    async def resolve_settings(self, user_id: str = "default") -> dict[str, Any]:
        """Return effective settings — user overrides merged on top of defaults.

        Defaults come from ``settings_schema[*]['default']``. Override
        comes from the SQLite ``user_widget_settings`` table. Any key
        not in the schema is ignored on read (defensive).
        """
        # Local import keeps the registry importable even if SQLite isn't
        # initialized at module-load time (tests, scripts).
        from services import widget_settings as ws

        defaults = {
            k: spec.get("default") for k, spec in self.settings_schema.items()
        }
        if not self.settings_schema:
            return defaults
        saved = await ws.get_all(user_id, self.id)
        merged = dict(defaults)
        for k, v in saved.items():
            if k in defaults:
                merged[k] = v
        return merged

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id} size={self.size}>"


# --------------------------------------------------------------------------- #
# Widget: Sector heatmap
# --------------------------------------------------------------------------- #


# 11 SPDR sector ETFs in a sensible order: cyclical / financial / defensive
SECTOR_ETFS: list[tuple[str, str]] = [
    ("XLK",  "Technology"),
    ("XLC",  "Communications"),
    ("XLY",  "Consumer Disc"),
    ("XLF",  "Financials"),
    ("XLI",  "Industrials"),
    ("XLB",  "Materials"),
    ("XLE",  "Energy"),
    ("XLV",  "Health Care"),
    ("XLP",  "Consumer Staples"),
    ("XLU",  "Utilities"),
    ("XLRE", "Real Estate"),
]


class SectorHeatmapWidget(Widget):
    """11 SPDR sector ETFs as a colored tile grid.

    Tile color intensity scales with the magnitude of the daily move
    (1-day % change from last cached close). Lets you spot risk-on vs
    risk-off rotation at a glance.

    Data source: daily bars cached by ``services.data_service``. During
    market hours this shows yesterday's close-to-close move, not live
    intraday — that's a known v1 limitation. Once we wire 30m bars into
    the heatmap, we can flip to "today's open → latest 30m close".
    """

    id = "sector_heatmap"
    title = "Sector Heatmap"
    size = "wide"
    tab = "market"
    refresh_seconds = 300   # 5 min — daily bars don't change intra-session

    async def get_data(self) -> dict[str, Any]:
        async def _one(symbol: str, label: str) -> dict[str, Any]:
            try:
                df = await get_bars(symbol, "1d", min_bars=2)
                if len(df) < 2:
                    return {"sym": symbol, "label": label, "pct": None,
                            "close": None, "error": "not enough bars"}
                last = float(df["close"].iloc[-1])
                prev = float(df["close"].iloc[-2])
                pct = (last - prev) / prev * 100 if prev else None
                return {"sym": symbol, "label": label,
                        "pct": round(pct, 2) if pct is not None else None,
                        "close": round(last, 2), "error": None}
            except DataNotAvailableError as e:
                return {"sym": symbol, "label": label, "pct": None,
                        "close": None, "error": str(e)}
            except Exception as e:                       # noqa: BLE001
                logger.warning("sector_heatmap %s: %s", symbol, e)
                return {"sym": symbol, "label": label, "pct": None,
                        "close": None, "error": "fetch failed"}

        rows = await asyncio.gather(*(_one(s, lbl) for s, lbl in SECTOR_ETFS))
        return {"sectors": rows, "as_of": pd.Timestamp.now(tz="UTC").isoformat()}


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Widget: Fear & Greed gauge
# --------------------------------------------------------------------------- #


# CNN's undocumented JSON endpoint that powers the Fear & Greed widget on
# their site. Refreshes a few times daily; we cache server-side 30 min so
# we never hammer it. CNN requires a User-Agent header — without it they
# return 403.
_FG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
_FG_UA  = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_fg_cache: dict[str, Any] = {"ts": 0.0, "data": None}
_FG_TTL_SEC = 1800  # 30 min


def _fg_label(score: float) -> tuple[str, str]:
    """Return (rating_text, css_color_class) for a 0-100 score."""
    if score < 25:  return ("Extreme Fear",  "fg-extreme-fear")
    if score < 45:  return ("Fear",          "fg-fear")
    if score < 55:  return ("Neutral",       "fg-neutral")
    if score < 75:  return ("Greed",         "fg-greed")
    return            ("Extreme Greed", "fg-extreme-greed")


async def _fetch_fear_greed() -> dict[str, Any]:
    """Cached wrapper around CNN's fear-and-greed endpoint.

    Returns dict with: score, rating, prev_close, week_ago, month_ago,
    year_ago. On failure logs and returns the last cached value if any,
    else a placeholder dict.
    """
    now = time.time()
    if _fg_cache["data"] and (now - _fg_cache["ts"]) < _FG_TTL_SEC:
        return _fg_cache["data"]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(_FG_URL, headers={"User-Agent": _FG_UA})
            r.raise_for_status()
            j = r.json()
    except Exception as e:                                # noqa: BLE001
        logger.warning("fear_greed fetch failed: %s", e)
        if _fg_cache["data"]:
            return _fg_cache["data"]
        return dict(score=None, rating="unavailable",
                    prev_close=None, week_ago=None,
                    month_ago=None, year_ago=None,
                    error=str(e))

    fg = j.get("fear_and_greed", {}) or {}
    data = dict(
        score=fg.get("score"),
        rating=fg.get("rating", ""),
        prev_close=fg.get("previous_close"),
        week_ago=(j.get("fear_and_greed_historical", {})
                    .get("data", [None])[-7] if False else None),
        month_ago=fg.get("previous_1_month"),
        year_ago=fg.get("previous_1_year"),
        error=None,
    )
    _fg_cache["ts"] = now
    _fg_cache["data"] = data
    return data


class FearGreedWidget(Widget):
    """CNN Fear & Greed Index — semicircle gauge with the current score.

    The gauge has 5 color bands (extreme fear → extreme greed) and a
    needle pointing at the current score. Source: CNN's data endpoint
    (cached 30 min server-side).
    """

    id = "fear_greed"
    title = "Fear & Greed Index"
    size = "md"
    tab = "market"
    refresh_seconds = 1800   # 30 min

    async def get_data(self) -> dict[str, Any]:
        d = await _fetch_fear_greed()
        score = d.get("score")
        if score is None:
            return {"score": None, "label": "—", "label_class": "fg-na",
                    "needle_angle": 0, "error": d.get("error")}
        label, label_class = _fg_label(float(score))
        # Needle: 0 score -> -90 deg (left), 100 -> +90 (right), 50 -> 0 (top)
        needle_angle = (float(score) / 100.0) * 180.0 - 90.0
        return dict(
            score=round(float(score), 1),
            label=label,
            label_class=label_class,
            needle_angle=round(needle_angle, 2),
            prev_close=d.get("prev_close"),
            month_ago=d.get("month_ago"),
            year_ago=d.get("year_ago"),
            error=None,
        )


# --------------------------------------------------------------------------- #
# Widget: SPY trend strip (1W / 1M / 3M / 1Y / 5Y)
# --------------------------------------------------------------------------- #


_SPY_PERIODS: list[tuple[str, int]] = [
    ("1W",  5),     # ~5 trading days
    ("1M",  21),
    ("3M",  63),
    ("1Y",  252),
    ("5Y",  1260),
]


class SpyTrendWidget(Widget):
    """SPY % return over five lookback periods, rendered as a trend strip.

    Each row: period label | bar (length normalized) | % | bullish/bearish
    badge. Pulls from cached SPY daily bars; needs ~5 years of history
    to populate the 5Y row.
    """

    id = "spy_trend"
    title = "SPY Trend"
    size = "md"
    tab = "market"
    refresh_seconds = 600    # 10 min — daily bar source

    async def get_data(self) -> dict[str, Any]:
        try:
            df = await get_bars("SPY", "1d", min_bars=10)
        except DataNotAvailableError as e:
            return {"rows": [], "error": str(e)}

        last = float(df["close"].iloc[-1])
        rows: list[dict[str, Any]] = []
        for label, lookback in _SPY_PERIODS:
            if len(df) <= lookback:
                rows.append(dict(label=label, pct=None, bullish=None,
                                 bar_pct=0.0, available=False))
                continue
            then = float(df["close"].iloc[-lookback - 1])
            pct = (last - then) / then * 100 if then else 0.0
            rows.append(dict(
                label=label,
                pct=round(pct, 2),
                bullish=pct >= 0,
                # Bar length capped at 100% — displayed length normalized
                # to max(|pct|) across the visible rows so longer periods
                # don't always dominate visually.
                _abs=abs(pct),
                available=True,
            ))
        max_abs = max((r["_abs"] for r in rows if r["available"]), default=1.0)
        for r in rows:
            if r["available"]:
                r["bar_pct"] = round(min(100.0, r["_abs"] / max_abs * 100.0), 1)
                del r["_abs"]
            else:
                r["bar_pct"] = 0.0
        return {"rows": rows, "current": round(last, 2), "error": None}


# --------------------------------------------------------------------------- #
# Widget: Strategy health (live WR vs backtest WR per active strategy)
# --------------------------------------------------------------------------- #


class StrategyHealthWidget(Widget):
    """Per-strategy live-vs-backtest WR with drift indicator.

    Reads each ``strategy_configs/*.yaml`` (only those with ``active: true``)
    and pulls the ``backtest_summary`` block. Live WR/PF come from the
    same trade source the analysis page reads — production-filtered dump
    pre-launch, JSONL once trades flow.

    Status badges:
      green  — live WR >= backtest mean
      blue   — live WR within bootstrap CI
      red    — live WR below CI floor (strategy may be drifting)
      gray   — no live trades yet
    """

    id = "strategy_health"
    title = "Strategy Health"
    size = "lg"
    tab = "portfolio"
    refresh_seconds = 60

    async def get_data(self) -> dict[str, Any]:
        # Per-strategy live stats come from probability_service, which
        # filters the trade journal by strategy_name. This is the single
        # source of truth — do NOT apply one aggregate dump to every row
        # (that produced the "all strategies show identical numbers" bug:
        # the legacy double_lock dump's 82.4%/n=17/PF was copied onto
        # every strategy regardless of whether it had any live trades).
        from services import probability_service as P   # avoid import cycle

        rows: list[dict[str, Any]] = []
        for path in sorted(STRATEGY_CONFIG_DIR.glob("*.yaml")):
            try:
                cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception as e:                            # noqa: BLE001
                logger.warning("strategy_health: bad yaml %s: %s", path.name, e)
                continue
            if not cfg.get("active", False):
                continue
            name = cfg.get("strategy_name", path.stem)
            bt = cfg.get("backtest_summary") or {}
            bt_wr = bt.get("point_wr_pct")
            ci_lo = bt.get("bootstrap_95_ci_lo")

            # Live numbers — strategy-specific. A strategy with no live
            # trades yet returns live_n == 0 and shows "no trades yet".
            try:
                est = await P.compute(name)
                live_wr = est.live_wr
                live_n  = est.live_n
                live_pf = est.live_pf
            except Exception as e:                            # noqa: BLE001
                logger.warning("strategy_health: probability compute failed for %s: %s", name, e)
                live_wr, live_n, live_pf = None, 0, None

            # Drift status
            if live_wr is None or live_n == 0:
                status, status_label = "gray", "no trades yet"
                drift = None
            elif bt_wr is not None and live_wr >= bt_wr:
                status, status_label = "green", "above backtest"
                drift = round(live_wr - bt_wr, 1)
            elif ci_lo is not None and live_wr >= ci_lo:
                status, status_label = "blue", "within CI"
                drift = round(live_wr - bt_wr, 1) if bt_wr is not None else None
            else:
                status, status_label = "red", "below CI floor"
                drift = round(live_wr - bt_wr, 1) if bt_wr is not None else None

            rows.append(dict(
                name=name,
                description=cfg.get("description", "").strip()[:80],
                live_wr=round(live_wr, 1) if live_wr is not None else None,
                live_n=live_n,
                live_pf=round(live_pf, 2) if live_pf is not None else None,
                bt_wr=bt_wr,
                ci_lo=ci_lo,
                drift=drift,
                status=status,
                status_label=status_label,
            ))
        return {"rows": rows}


# --------------------------------------------------------------------------- #
# Widget: Exploded stocks (top up/down movers from a watch universe)
# --------------------------------------------------------------------------- #


# Liquid watch universe — same shape as the analysis dump's symbol list.
# Override later by reading the active universe screener once that
# integration is wired into the dashboard.
_EXPLODED_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "META", "AMZN", "NVDA", "TSLA", "AVGO",
    "NFLX", "AMD", "INTC", "CRM", "ORCL", "ADBE", "QQQ", "SPY", "IWM",
    "DIA", "JPM", "BAC", "GS", "V", "MA", "JNJ", "UNH", "HD", "COST",
    "WMT", "BA", "CAT", "XOM", "CVX",
]
_EXPLODE_THRESHOLD_PCT = 3.0    # |daily move| must clear this to qualify
_EXPLODE_LIMIT_PER_SIDE = 8     # top N up + top N down


class ExplodedStocksWidget(Widget):
    """Top up/down movers from a liquid watch universe.

    Computes today's daily % change for each symbol from cached daily
    bars. Surfaces the largest |moves| above a threshold (default 3%).
    Two columns: explosions up (green) / explosions down (red), each
    showing symbol, % change, and last close.

    Renders empty if no symbol clears the threshold (common in calm
    regimes — that's a feature, not a bug).
    """

    id = "exploded_stocks"
    title = "Today's Explosions"
    size = "wide"
    tab = "market"
    refresh_seconds = 300    # 5 min

    # User-configurable: threshold + max per side. Demonstrates the
    # settings-schema flow — the ⚙ icon in the widget header opens a
    # form generated from this dict.
    user_configurable = True
    settings_schema = {
        "threshold_pct": {
            "type": "number",
            "label": "Threshold (% absolute daily move)",
            "default": _EXPLODE_THRESHOLD_PCT,
            "min": 0.5,
            "max": 20.0,
            "step": 0.5,
            "help": "Minimum |daily change| for a symbol to qualify.",
        },
        "max_per_side": {
            "type": "int",
            "label": "Max symbols per side",
            "default": _EXPLODE_LIMIT_PER_SIDE,
            "min": 1,
            "max": 25,
            "step": 1,
            "help": "How many up- and down-movers to show.",
        },
    }

    async def get_data(self) -> dict[str, Any]:
        cfg = await self.resolve_settings()
        threshold = float(cfg.get("threshold_pct", _EXPLODE_THRESHOLD_PCT))
        limit = int(cfg.get("max_per_side", _EXPLODE_LIMIT_PER_SIDE))

        async def _one(sym: str) -> dict[str, Any] | None:
            try:
                df = await get_bars(sym, "1d", min_bars=2,
                                    download_if_missing=False)
            except DataNotAvailableError:
                return None
            except Exception as e:                            # noqa: BLE001
                logger.warning("exploded_stocks %s: %s", sym, e)
                return None
            if len(df) < 2:
                return None
            last = float(df["close"].iloc[-1])
            prev = float(df["close"].iloc[-2])
            pct = (last - prev) / prev * 100 if prev else 0.0
            if abs(pct) < threshold:
                return None
            return dict(sym=sym, pct=round(pct, 2), close=round(last, 2))

        results = await asyncio.gather(*(_one(s) for s in _EXPLODED_UNIVERSE))
        rows = [r for r in results if r is not None]
        ups   = sorted([r for r in rows if r["pct"] > 0],
                       key=lambda r: -r["pct"])[:limit]
        downs = sorted([r for r in rows if r["pct"] < 0],
                       key=lambda r:  r["pct"])[:limit]
        return {
            "ups": ups,
            "downs": downs,
            "threshold": threshold,
            "universe_size": len(_EXPLODED_UNIVERSE),
        }


# --------------------------------------------------------------------------- #
# Widget: Market Headlines (News tab)
# --------------------------------------------------------------------------- #


# Default watchlist for the headlines stream — major indices + a handful of
# bellwethers. User-overridable via settings_schema.
_HEADLINES_DEFAULT_WATCHLIST = [
    "SPY", "QQQ", "AAPL", "NVDA", "MSFT", "TSLA", "AMZN", "META",
]


class MarketHeadlinesWidget(Widget):
    """Combined Alpaca news + EDGAR filings stream across a small watchlist.

    Pulls per-symbol news (last 24h) for each symbol in the watchlist plus
    EDGAR 8-K / 10-Q / 10-K filings (last 14d), VADER-scores every item,
    sorts newest-first, caps at 25. Empty watchlists or full credential-
    less environments degrade to a graceful empty state — never throws.

    User-configurable: edit the watchlist (comma-separated tickers) and
    toggle whether EDGAR filings are included.
    """

    id = "market_headlines"
    title = "Market Headlines"
    size = "wide"
    tab = "news"
    refresh_seconds = 600   # 10 min

    user_configurable = True

    # ``settings_schema`` is a property so the source-multiselect choices
    # come from the live news_sources registry — adding a new provider
    # adds a new chip here without touching this dict. (Pulling the
    # registry at class-definition time would create an import cycle:
    # news_sources/__init__ pulls NewsItem out of news_service, which
    # in turn imports widgets at registry-load time.)
    @property
    def settings_schema(self) -> dict[str, dict[str, Any]]:    # type: ignore[override]
        from services.news_sources import (
            default_enabled_source_ids,
            source_choices,
        )
        return {
            "watchlist": {
                "type": "text",
                "label": "Watchlist (comma-separated)",
                "default": ",".join(_HEADLINES_DEFAULT_WATCHLIST),
                "help": "Symbols to pull news for. Up to ~12 keeps latency reasonable.",
            },
            "enabled_sources": {
                "type": "multiselect",
                "label": "News sources",
                "default": default_enabled_source_ids(),
                "choices": source_choices(),
                "help": "Toggle providers on/off. Adding a new source "
                        "in services/news_sources/ adds a new chip here.",
            },
            "lookback_hours": {
                "type": "int",
                "label": "Lookback (hours)",
                "default": 24,
                "min": 1, "max": 168, "step": 1,
                "help": "Per-source window. EDGAR floors this at 14d "
                        "internally so quarterly filings still surface.",
            },
            "max_items": {
                "type": "int",
                "label": "Max items rendered",
                "default": 25,
                "min": 5, "max": 100, "step": 5,
            },
        }

    async def get_data(self) -> dict[str, Any]:
        from services import news_service, sentiment_service  # local imports
        from services.news_sources import (
            NEWS_SOURCES, default_enabled_source_ids,
        )

        cfg = await self.resolve_settings()
        raw = str(cfg.get("watchlist", "") or "")
        symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
        if not symbols:
            symbols = _HEADLINES_DEFAULT_WATCHLIST
        enabled_sources = (
            list(cfg.get("enabled_sources") or default_enabled_source_ids())
        )
        lookback_hours = int(cfg.get("lookback_hours", 24))
        max_items = int(cfg.get("max_items", 25))

        async def _per_symbol(sym: str) -> list:
            try:
                return await news_service.get_news_multi_source(
                    sym,
                    source_ids=enabled_sources,
                    lookback_hours=lookback_hours,
                )
            except Exception as e:                            # noqa: BLE001
                logger.warning("market_headlines %s: %s", sym, e)
                return []

        per_symbol = await asyncio.gather(*(_per_symbol(s) for s in symbols))
        items: list = []
        for lst in per_symbol:
            items.extend(lst)

        # Already newest-first per get_news_multi_source, but a second
        # sort across the merged set is cheap and removes any cross-symbol
        # ordering surprises.
        items.sort(key=lambda n: n.published_at, reverse=True)
        items = items[:max_items]
        scored = sentiment_service.score_items(items)

        rows: list[dict[str, Any]] = []
        for item, sc in zip(items, scored):
            d = sc.to_dict()
            d["symbol"]     = item.symbol
            d["summary"]    = item.summary
            d["image_url"]  = item.image_url
            d["tags"]       = item.tags or []
            d["detail_url"] = f"/news/{item.source}/{item.article_id}"
            d["form_type"]  = (
                item.extra.get("form_type") if item.extra else None
            )
            rows.append(d)

        summary = sentiment_service.summarize(items).to_dict() if items else {}
        # Source descriptors for the empty-state hint and credential warnings
        source_states = [
            {"id": s.id, "label": s.label,
             "enabled": s.id in set(enabled_sources),
             "creds_ok": s.credentials_present()}
            for s in NEWS_SOURCES
        ]
        return {
            "rows": rows,
            "summary": summary,
            "watchlist": symbols,
            "enabled_sources": enabled_sources,
            "source_states": source_states,
            "lookback_hours": lookback_hours,
        }


# --------------------------------------------------------------------------- #
# Widget: Open Positions (the most important cards — one per live position)
# --------------------------------------------------------------------------- #


def _humanize_since(iso_ts: str | None) -> str:
    """'2026-06-20T14:30:00Z' -> '5d 3h' style time-since string."""
    if not iso_ts:
        return "—"
    from datetime import datetime, timezone
    try:
        t = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
    except ValueError:
        return "—"
    secs = (datetime.now(timezone.utc) - t).total_seconds()
    if secs < 0:
        return "just now"
    d, rem = divmod(int(secs), 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


class OpenPositionsWidget(Widget):
    """One card per live broker position — the dashboard's most important cards.

    Each card joins the broker position (symbol/shares/avg price/PnL) with its
    originating TradePlan (stop, strategy, entry time, TP, evidence) so the
    reviewer sees entry time, time-held, stop, and strategy at a glance, clicks
    through to the full /trades/{id} detail, and can close immediately.
    """

    id = "open_positions"
    title = "Open Positions"
    size = "wide"
    tab = "portfolio"
    refresh_seconds = 15

    async def get_data(self) -> dict[str, Any]:
        from services import broker_service, db_service, trade_lookup
        rows: list[dict[str, Any]] = []
        error: str | None = None
        try:
            adapter = await broker_service.get_adapter_async()
            st = await adapter.get_account_state()
            positions = st.open_positions or []
        except Exception as e:  # noqa: BLE001
            return {"positions": [], "error": f"broker unavailable: {e}"}

        # symbol -> most-recent open/approved/filled plan_id (plans come ts DESC)
        by_symbol: dict[str, str] = {}
        try:
            plans = await db_service.get_pending_plans(status_filter=None, limit=300)
            for pl in plans:
                if str(pl.get("status", "")).lower() in ("approved", "awaiting_fill", "filled", "open"):
                    sym = str(pl.get("symbol", "")).upper()
                    if sym and sym not in by_symbol and pl.get("plan_id"):
                        by_symbol[sym] = pl["plan_id"]
        except Exception as e:  # noqa: BLE001
            error = f"plan join degraded: {e}"

        for p in positions:
            entry = float(p.avg_entry_price or 0.0)
            current = float(p.market_price or 0.0)
            shares = int(p.shares or 0)
            direction = "long" if shares >= 0 else "short"
            pnl_pct = ((current - entry) / entry * 100.0) if entry else 0.0
            if direction == "short":
                pnl_pct = -pnl_pct
            stop = strategy = entry_ts = plan_id = tp1 = None
            pnl_r = None
            pid = by_symbol.get(str(p.symbol).upper())
            if pid:
                try:
                    v = await trade_lookup.get(pid)
                    if v is not None:
                        stop = v.stop_price; strategy = v.strategy_name
                        entry_ts = v.ts_entered or v.ts_created
                        tp1 = v.tp1_price; plan_id = v.id
                        if stop and entry and (entry - stop) != 0:
                            risk = abs(entry - stop)
                            pnl_r = ((current - entry) / risk) if direction == "long" else ((entry - current) / risk)
                except Exception:  # noqa: BLE001
                    pass
            rows.append({
                "symbol": p.symbol, "direction": direction, "shares": abs(shares),
                "entry": entry, "current": current,
                "pnl_usd": float(p.unrealized_pnl_usd or 0.0), "pnl_pct": pnl_pct,
                "pnl_r": pnl_r, "stop": stop, "tp1": tp1,
                "strategy": strategy or "—", "entry_ts": entry_ts,
                "held": _humanize_since(entry_ts), "plan_id": plan_id,
            })
        rows.sort(key=lambda r: (r["pnl_r"] is None, -(r["pnl_r"] or 0)))
        return {"positions": rows, "error": error}


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


WIDGETS: list[Widget] = [
    OpenPositionsWidget(),       # most important — render first, portfolio tab
    SectorHeatmapWidget(),
    FearGreedWidget(),
    SpyTrendWidget(),
    StrategyHealthWidget(),
    ExplodedStocksWidget(),
    MarketHeadlinesWidget(),
]


def get_widget(widget_id: str) -> Widget | None:
    return next((w for w in WIDGETS if w.id == widget_id), None)


def enabled_widgets() -> list[Widget]:
    return [w for w in WIDGETS if w.enabled]


def widgets_by_tab() -> dict[str, list[Widget]]:
    """Group enabled widgets by their tab attribute, in declaration order.

    Tabs with no widgets still appear in the result (empty list) so the
    dashboard template can render the tab nav consistently and show an
    empty-state placeholder where applicable (e.g. News today).
    """
    out: dict[str, list[Widget]] = {tab: [] for tab, _ in TAB_ORDER}
    for w in enabled_widgets():
        out.setdefault(w.tab, []).append(w)
    return out


# --------------------------------------------------------------------------- #
# Layout overrides — per-user widget order and size-class overrides
# --------------------------------------------------------------------------- #


# Synthetic widget id under which layout state lives in user_widget_settings.
# Keys: "<tab>.order" -> ordered list of widget ids
#       "<widget_id>.size" -> "sm" | "md" | "lg" | "wide" override
LAYOUT_WIDGET_ID = "__layout__"


async def widgets_by_tab_for_user(user_id: str = "default") -> dict[str, list[dict[str, Any]]]:
    """Tab → ordered list of widget descriptors honoring user overrides.

    Each descriptor is a flat dict the template iterates without needing
    to call methods on the Widget. Order is the saved per-tab order
    (unknown widgets appended; missing widgets dropped). Size honors any
    saved override; falls back to ``Widget.size``.
    """
    from services import widget_settings as ws

    saved = await ws.get_all(user_id, LAYOUT_WIDGET_ID)
    grouped = widgets_by_tab()
    out: dict[str, list[dict[str, Any]]] = {}
    for tab, widgets in grouped.items():
        order_key = f"{tab}.order"
        saved_order = saved.get(order_key) or []
        if isinstance(saved_order, list):
            by_id = {w.id: w for w in widgets}
            ordered: list[Widget] = []
            seen: set[str] = set()
            for wid in saved_order:
                if wid in by_id and wid not in seen:
                    ordered.append(by_id[wid])
                    seen.add(wid)
            for w in widgets:
                if w.id not in seen:
                    ordered.append(w)
            widgets = ordered
        descriptors: list[dict[str, Any]] = []
        for w in widgets:
            size = saved.get(f"{w.id}.size") or w.size
            if size not in ("sm", "md", "lg", "wide"):
                size = w.size
            descriptors.append({
                "id": w.id,
                "title": w.title,
                "size": size,
                "default_size": w.size,
                "refresh_seconds": w.refresh_seconds,
                "user_configurable": w.user_configurable,
                "tab": w.tab,
            })
        out[tab] = descriptors
    return out
