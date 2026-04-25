"""Congressional trades data service.

Originally targeted capitoltrades.com, but their API subdomain
(api.capitoltrades.com) is dead and their new BFF (bff.capitoltrades.com)
is currently broken (CloudFront Lambda errors). Rewritten to use the
free, hosted, actively-maintained API from `ivanma9/CongressionalTrading`:

  https://congressional-trading-datastore-production-9fd6.up.railway.app

Coverage: U.S. House of Representatives only (PTR filings parsed from
disclosures-clerk.house.gov). Senate trades not included.

Public interface preserved (CapitolTradesService class, PoliticianTrade /
PoliticianScore dataclasses) so existing callers in scheduler.py and
routers/copy_trading.py keep working.
"""
from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Data models — kept compatible with the old api.capitoltrades.com shape
# --------------------------------------------------------------------------- #


@dataclass
class PoliticianTrade:
    trade_id: str
    politician_name: str
    politician_slug: str
    party: str
    chamber: str
    ticker: str
    asset_name: str
    asset_type: str          # stock, bond, options, etc.
    transaction_type: str    # purchase, sale, sale_partial, exchange
    transaction_date: str    # YYYY-MM-DD
    published_date: str      # YYYY-MM-DD (disclosure_date)
    amount_min: float
    amount_max: float
    amount_mid: float


@dataclass
class PoliticianScore:
    politician_name: str
    politician_slug: str
    party: str
    chamber: str
    trade_count_90d: int
    last_trade_date: str
    days_since_last_trade: int
    unique_tickers: int
    buy_ratio: float
    score: float
    state: str = ""
    district: str = ""


@dataclass
class PoliticianPerformance:
    politician_slug: str
    politician_name: str
    total_trades: int
    win_rate_30d: float | None       # 0.0–1.0
    avg_return_30d: float | None     # decimal (0.05 = 5%)
    avg_spy_return_30d: float | None # SPY benchmark over same horizon


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _normalize_tx_type(raw: str) -> str:
    """Collapse the API's transaction_type into our internal {purchase, sale}."""
    if not raw:
        return ""
    r = raw.lower().strip()
    if r in ("purchase", "buy", "bought"):
        return "purchase"
    if r in ("sale", "sale_full", "sale_partial", "sell", "sold", "exchange"):
        return "sale"
    return r


def _name_to_slug(name: str) -> str:
    """Generate a stable slug from a display name (kebab-case lowercase)."""
    out = []
    for ch in name.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")


def _parse_trade(raw: dict[str, Any]) -> PoliticianTrade | None:
    """Convert one ivanma9 API trade row into our PoliticianTrade dataclass."""
    try:
        member_name = (raw.get("member_name") or "").strip()
        ticker = (raw.get("ticker") or "").strip().upper()
        if not member_name or not ticker:
            return None  # Skip bond/non-equity rows with no ticker

        slug = _name_to_slug(member_name)
        amount_min = float(raw.get("amount_range_low") or 0)
        amount_max = float(raw.get("amount_range_high") or amount_min)
        tx_type = _normalize_tx_type(str(raw.get("transaction_type") or ""))
        if tx_type not in ("purchase", "sale"):
            return None

        return PoliticianTrade(
            trade_id=str(raw.get("id") or f"{slug}-{ticker}-{raw.get('transaction_date','')}-{tx_type}"),
            politician_name=member_name,
            politician_slug=slug,
            party="",  # API doesn't expose party
            chamber="House",
            ticker=ticker,
            asset_name=str(raw.get("asset_description") or ticker),
            asset_type=str(raw.get("asset_type") or "stock").lower(),
            transaction_type=tx_type,
            transaction_date=str(raw.get("transaction_date") or "")[:10],
            published_date=str(raw.get("disclosure_date") or raw.get("transaction_date") or "")[:10],
            amount_min=amount_min,
            amount_max=amount_max,
            amount_mid=(amount_min + amount_max) / 2,
        )
    except Exception as exc:
        logger.debug("parse_trade failed: %s | row=%r", exc, raw)
        return None


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


class CapitolTradesService:
    """Wraps the ivanma9 hosted Congressional Trading API."""

    API_BASE = "https://congressional-trading-datastore-production-9fd6.up.railway.app"
    TIMEOUT = 25.0
    PERFORMANCE_TIMEOUT = 60.0   # /performance is slower; involves price lookups
    HEADERS = {"User-Agent": "TradeAgent/1.0 (+local)"}

    # ------------------------------------------------------------------ #
    # Trades
    # ------------------------------------------------------------------ #

    async def fetch_recent_trades(self, pages: int = 5) -> list[PoliticianTrade]:
        """Fetch the most recent disclosures across all members.

        `pages` kept for backward compatibility — translated to a single
        request with `limit = pages * 50` since the new API is offset-paged.
        """
        limit = max(50, pages * 50)
        async with httpx.AsyncClient(headers=self.HEADERS, timeout=self.TIMEOUT) as client:
            try:
                r = await client.get(
                    f"{self.API_BASE}/api/v1/trades/recent",
                    params={"days": 90, "limit": limit},
                )
                if r.status_code != 200:
                    logger.warning("trades/recent returned %s", r.status_code)
                    return []
                rows = r.json().get("trades", [])
                trades = [t for row in rows if (t := _parse_trade(row))]
                logger.info("fetch_recent_trades: %d parsed from %d rows", len(trades), len(rows))
                return trades
            except Exception as exc:
                logger.warning("fetch_recent_trades failed: %s", exc)
                return []

    async def fetch_politician_trades(
        self, politician_slug: str, pages: int = 10
    ) -> list[PoliticianTrade]:
        """Fetch trades for one politician.

        `politician_slug` may be a kebab-case slug (e.g. 'nancy-pelosi') or
        a last-name fragment ('Pelosi'). The API does substring matching on
        member_name, so we strip dashes and use whatever portion matches.
        """
        if not politician_slug:
            return []
        # Convert kebab slug back to a name fragment the API will match.
        # 'nancy-pelosi' -> 'Pelosi' (last token is most distinctive)
        tokens = politician_slug.replace("-", " ").split()
        name_query = tokens[-1].title() if tokens else politician_slug
        limit = max(100, pages * 50)

        async with httpx.AsyncClient(headers=self.HEADERS, timeout=self.TIMEOUT) as client:
            try:
                r = await client.get(
                    f"{self.API_BASE}/api/v1/trades",
                    params={"member": name_query, "days": 365, "limit": limit},
                )
                if r.status_code != 200:
                    logger.warning("trades?member=%s returned %s", name_query, r.status_code)
                    return []
                rows = r.json().get("trades", [])
                trades = [t for row in rows if (t := _parse_trade(row))]
                # Filter to exact slug match in case substring caught multiple members
                trades = [t for t in trades if t.politician_slug == politician_slug] or trades
                logger.info("fetch_politician_trades(%s): %d parsed", politician_slug, len(trades))
                return trades
            except Exception as exc:
                logger.warning("fetch_politician_trades(%s) failed: %s", politician_slug, exc)
                return []

    # ------------------------------------------------------------------ #
    # Member ranking
    # ------------------------------------------------------------------ #

    async def fetch_ranked_members(self, limit: int = 50, days: int = 365) -> list[PoliticianScore]:
        """Fetch the most active members directly from the API's members endpoint.

        Default `days=365` so members who traded once or twice in the last
        year still appear (Pelosi's last trade was 99 days ago, would be
        excluded by the API's default 90-day filter).
        """
        async with httpx.AsyncClient(headers=self.HEADERS, timeout=self.TIMEOUT) as client:
            try:
                r = await client.get(
                    f"{self.API_BASE}/api/v1/members",
                    params={"days": days, "limit": limit},
                )
                if r.status_code != 200:
                    logger.warning("members returned %s", r.status_code)
                    return []
                members = r.json().get("members", [])
            except Exception as exc:
                logger.warning("fetch_ranked_members failed: %s", exc)
                return []

        today = datetime.now(timezone.utc).date()
        scored: list[PoliticianScore] = []
        for m in members:
            name = (m.get("name") or "").strip()
            if not name:
                continue
            slug = _name_to_slug(name)
            count = int(m.get("trade_count") or 0)
            last_date = str(m.get("latest_trade_date") or "")[:10]
            try:
                last = datetime.fromisoformat(last_date).date() if last_date else today
                days_ago = max(0, (today - last).days)
            except ValueError:
                days_ago = 999
            # Activity-weighted recency score
            score = round(count * (100.0 / (days_ago + 1)), 2)
            scored.append(PoliticianScore(
                politician_name=name,
                politician_slug=slug,
                party="",          # not exposed by this API
                chamber="House",
                trade_count_90d=count,
                last_trade_date=last_date,
                days_since_last_trade=days_ago,
                unique_tickers=0,  # not exposed
                buy_ratio=0.0,     # not exposed
                score=score,
                state=str(m.get("state") or ""),
                district=str(m.get("district") or ""),
            ))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored

    def rank_politicians(
        self, trades: list[PoliticianTrade], top_n: int = 20
    ) -> list[PoliticianScore]:
        """Compatibility shim — the new API ranks members natively, but this
        function is still called by routers/copy_trading.py with a trade list.
        Compute the ranking from the trade list (slower than fetch_ranked_members)."""
        from collections import defaultdict
        today = datetime.now(timezone.utc).date()
        stats: dict[str, dict] = defaultdict(lambda: {
            "name": "", "tickers": set(), "buys": 0, "dates": [],
        })
        for t in trades:
            s = stats[t.politician_slug]
            s["name"] = t.politician_name
            s["tickers"].add(t.ticker)
            s["dates"].append(t.transaction_date)
            if t.transaction_type == "purchase":
                s["buys"] += 1
        out: list[PoliticianScore] = []
        for slug, s in stats.items():
            if not s["dates"]:
                continue
            last = max(s["dates"])
            try:
                days = max(0, (today - datetime.fromisoformat(last).date()).days)
            except ValueError:
                days = 999
            count = len(s["dates"])
            buy_ratio = s["buys"] / count if count else 0
            score = round(count * (100.0 / (days + 1)) * (1 + len(s["tickers"]) * 0.1), 2)
            out.append(PoliticianScore(
                politician_name=s["name"],
                politician_slug=slug,
                party="", chamber="House",
                trade_count_90d=count,
                last_trade_date=last,
                days_since_last_trade=days,
                unique_tickers=len(s["tickers"]),
                buy_ratio=round(buy_ratio, 2),
                score=score,
            ))
        out.sort(key=lambda x: x.score, reverse=True)
        return out[:top_n]

    # ------------------------------------------------------------------ #
    # Performance metrics — the headline "trading success" measure
    # ------------------------------------------------------------------ #

    async def fetch_politician_performance(
        self, politician_slug: str, politician_name: str | None = None
    ) -> PoliticianPerformance | None:
        """Compute win-rate and avg 30-day return for a politician's trades.

        The hosted API exposes a /performance endpoint but it's buggy —
        always returns total_trades=0. Instead we compute locally:
          1. Fetch the politician's trades from the API
          2. For each trade with a ticker, look up the close price on the
             disclosure date and 30 days later via yfinance
          3. Win = price moved the same direction as the trade (up for buys)
          4. Aggregate: win_rate, avg_return, avg_spy_return for benchmark
        """
        if not politician_slug:
            return None

        trades = await self.fetch_politician_trades(politician_slug, pages=4)
        if not trades:
            return PoliticianPerformance(
                politician_slug=politician_slug,
                politician_name=politician_name or politician_slug,
                total_trades=0,
                win_rate_30d=None, avg_return_30d=None, avg_spy_return_30d=None,
            )

        # Run the yfinance lookups in a thread (sync library, blocking calls)
        import asyncio
        return await asyncio.to_thread(
            _compute_performance_locally,
            politician_slug, politician_name or trades[0].politician_name, trades,
        )


def _compute_performance_locally(
    slug: str, name: str, trades: list[PoliticianTrade]
) -> PoliticianPerformance:
    """Compute win rate and avg return over a 30-day post-disclosure horizon.

    Synchronous because yfinance is sync — call from asyncio.to_thread.
    Only includes trades whose 30-day window is fully in the past.
    """
    from datetime import date, timedelta
    import yfinance as yf
    import pandas as pd

    today = date.today()
    cutoff = today - timedelta(days=31)  # need 30+ days of post-trade history
    eligible = [t for t in trades if t.transaction_date and _to_date(t.transaction_date) and _to_date(t.transaction_date) <= cutoff]
    if not eligible:
        return PoliticianPerformance(
            politician_slug=slug, politician_name=name, total_trades=0,
            win_rate_30d=None, avg_return_30d=None, avg_spy_return_30d=None,
        )

    # Collect SPY benchmark range once
    earliest = min(_to_date(t.transaction_date) for t in eligible)
    spy_end = today
    try:
        spy_df = yf.download("SPY", start=earliest.isoformat(), end=spy_end.isoformat(),
                             progress=False, auto_adjust=True, threads=False)
        spy_close = spy_df["Close"]["SPY"] if isinstance(spy_df["Close"], pd.DataFrame) else spy_df["Close"]
    except Exception as exc:
        logger.warning("SPY download failed: %s", exc)
        spy_close = None

    returns: list[float] = []
    spy_returns: list[float] = []
    wins = 0
    counted = 0

    # Group trades by ticker so we download each ticker only once
    by_ticker: dict[str, list[PoliticianTrade]] = {}
    for t in eligible:
        by_ticker.setdefault(t.ticker, []).append(t)

    for ticker, ticker_trades in by_ticker.items():
        try:
            start_dt = min(_to_date(t.transaction_date) for t in ticker_trades) - timedelta(days=2)
            end_dt = today
            df = yf.download(ticker, start=start_dt.isoformat(), end=end_dt.isoformat(),
                             progress=False, auto_adjust=True, threads=False)
            if df.empty:
                continue
            close = df["Close"][ticker] if isinstance(df["Close"], pd.DataFrame) else df["Close"]
        except Exception as exc:
            logger.debug("yf download failed for %s: %s", ticker, exc)
            continue

        for t in ticker_trades:
            d0 = _to_date(t.transaction_date)
            d1 = d0 + timedelta(days=30)
            try:
                p0 = _nearest_close(close, d0)
                p1 = _nearest_close(close, d1)
                if p0 is None or p1 is None or p0 <= 0:
                    continue
                raw = (p1 - p0) / p0
                # Win if direction matches: up for buy, down for sell
                signed_return = raw if t.transaction_type == "purchase" else -raw
                returns.append(signed_return)
                counted += 1
                if signed_return > 0:
                    wins += 1
                # SPY benchmark over same window
                if spy_close is not None:
                    sp0 = _nearest_close(spy_close, d0)
                    sp1 = _nearest_close(spy_close, d1)
                    if sp0 and sp1 and sp0 > 0:
                        spy_returns.append((sp1 - sp0) / sp0)
            except Exception:
                continue

    return PoliticianPerformance(
        politician_slug=slug,
        politician_name=name,
        total_trades=counted,
        win_rate_30d=wins / counted if counted else None,
        avg_return_30d=sum(returns) / len(returns) if returns else None,
        avg_spy_return_30d=sum(spy_returns) / len(spy_returns) if spy_returns else None,
    )


def _to_date(s: str):
    from datetime import date
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _nearest_close(series, target_date) -> float | None:
    """Find the close price on or just after target_date in a price series."""
    import pandas as pd
    if series is None or len(series) == 0:
        return None
    target = pd.Timestamp(target_date)
    # Make timezone naive to match yfinance index
    idx = series.index.tz_localize(None) if series.index.tz else series.index
    matches = series.loc[idx >= target]
    if matches.empty:
        return None
    val = matches.iloc[0]
    return float(val) if val == val else None  # NaN check
