"""Capitol Trades scraper and politician ranking service.

Fetches congressional trade disclosures from capitoltrades.com and ranks
politicians by trading activity and recency.

Data note: STOCK Act requires disclosure within 45 days, so all data is
delayed. The value is in consistent signal from active, high-conviction
traders — not in speed.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.capitoltrades.com/trades",
}

# Regex to extract dollar amounts from range strings like "$100,001 - $250,000"
_RANGE_RE = re.compile(r"\$?([\d,]+)\s*[-–]\s*\$?([\d,]+)")
_OVER_RE = re.compile(r"[Oo]ver\s+\$?([\d,]+)")


# --------------------------------------------------------------------------- #
# Data models
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
    asset_type: str           # stock, option, etf, crypto, other
    transaction_type: str     # purchase, sale
    transaction_date: str     # YYYY-MM-DD
    published_date: str       # YYYY-MM-DD (when disclosed)
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


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #


def _parse_amount(raw: str) -> tuple[float, float]:
    """Parse Capitol Trades amount string to (min, max) floats."""
    if not raw:
        return 1_001.0, 15_000.0
    m = _RANGE_RE.search(raw)
    if m:
        lo = float(m.group(1).replace(",", ""))
        hi = float(m.group(2).replace(",", ""))
        return lo, hi
    m = _OVER_RE.search(raw)
    if m:
        lo = float(m.group(1).replace(",", ""))
        return lo, lo * 3
    return 1_001.0, 15_000.0


def _normalize_tx_type(raw: str) -> str:
    raw = raw.lower().strip()
    if raw in ("purchase", "buy", "bought"):
        return "purchase"
    if raw in ("sale", "sell", "sold", "sale_full", "sale_partial", "exchange"):
        return "sale"
    return raw


def _parse_trade(raw: dict[str, Any]) -> PoliticianTrade | None:
    """Parse one Capitol Trades API object into a PoliticianTrade."""
    try:
        pol = raw.get("politician") or {}
        asset = raw.get("asset") or {}

        ticker = (
            asset.get("ticker")
            or asset.get("symbol")
            or asset.get("assetTicker")
            or ""
        ).strip().upper()
        if not ticker or ticker in ("N/A", "NONE", ""):
            return None

        amount_str = str(raw.get("amount") or raw.get("size") or "")
        lo, hi = _parse_amount(amount_str)

        tx_raw = str(raw.get("txType") or raw.get("type") or raw.get("transactionType") or "")
        tx_type = _normalize_tx_type(tx_raw)

        # Capitol Trades dates come as ISO strings; take first 10 chars (YYYY-MM-DD)
        tx_date = str(raw.get("txDate") or raw.get("transactionDate") or "")[:10]
        pub_date = str(raw.get("publishedDate") or raw.get("filedDate") or raw.get("disclosureDate") or "")[:10]
        if not pub_date:
            pub_date = tx_date

        pol_name = (
            pol.get("name")
            or f"{pol.get('firstName', '')} {pol.get('lastName', '')}".strip()
            or "Unknown"
        )
        pol_slug = pol.get("slug") or pol_name.lower().replace(" ", "-").replace(".", "")

        trade_id = (
            str(raw.get("_id") or raw.get("id") or "")
            or f"{pol_slug}-{ticker}-{tx_date}-{tx_type}"
        )

        return PoliticianTrade(
            trade_id=trade_id,
            politician_name=pol_name,
            politician_slug=pol_slug,
            party=str(pol.get("party") or pol.get("Party") or "Unknown"),
            chamber=str(pol.get("chamber") or pol.get("Chamber") or "Unknown"),
            ticker=ticker,
            asset_name=str(asset.get("name") or asset.get("assetName") or ticker),
            asset_type=str(asset.get("assetType") or asset.get("type") or "stock").lower(),
            transaction_type=tx_type,
            transaction_date=tx_date,
            published_date=pub_date,
            amount_min=lo,
            amount_max=hi,
            amount_mid=(lo + hi) / 2,
        )
    except Exception as exc:
        logger.debug("Failed to parse trade row: %s | raw=%r", exc, raw)
        return None


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


class CapitolTradesService:
    """Fetches and ranks congressional trade disclosures."""

    # Capitol Trades runs a separate REST API backend
    API_BASE = "https://api.capitoltrades.com"
    SITE_BASE = "https://www.capitoltrades.com"
    TIMEOUT = 25.0

    # ------------------------------------------------------------------ #
    # Public interface
    # ------------------------------------------------------------------ #

    async def fetch_recent_trades(self, pages: int = 5) -> list[PoliticianTrade]:
        """Fetch the most recent trades across all politicians."""
        trades = await self._fetch_api_trades(pages=pages)
        if not trades:
            logger.warning("Capitol Trades API returned nothing; falling back to HTML scrape")
            trades = await self._fetch_html_trades(pages=min(pages, 2))
        logger.info("Capitol Trades: fetched %d trades (%d pages requested)", len(trades), pages)
        return trades

    async def fetch_politician_trades(
        self, politician_slug: str, pages: int = 10
    ) -> list[PoliticianTrade]:
        """Fetch all trades for one politician by slug."""
        all_trades: list[PoliticianTrade] = []
        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=self.TIMEOUT, follow_redirects=True
        ) as client:
            for page in range(1, pages + 1):
                try:
                    resp = await client.get(
                        f"{self.API_BASE}/trade",
                        params={
                            "page": page,
                            "pageSize": 50,
                            "sortBy": "-publishedDate",
                            "politician": politician_slug,
                        },
                    )
                    if resp.status_code != 200:
                        logger.debug(
                            "Politician trades page %d → HTTP %d", page, resp.status_code
                        )
                        break
                    data = resp.json()
                    items = data.get("data") or []
                    if not items:
                        break
                    parsed = [t for item in items if (t := _parse_trade(item))]
                    all_trades.extend(parsed)
                    meta = data.get("meta") or {}
                    total = meta.get("total") or meta.get("totalCount") or 0
                    if len(all_trades) >= total and total > 0:
                        break
                except Exception as exc:
                    logger.warning(
                        "Failed fetching page %d for %s: %s", page, politician_slug, exc
                    )
                    break
        return all_trades

    def rank_politicians(
        self, trades: list[PoliticianTrade], top_n: int = 20
    ) -> list[PoliticianScore]:
        """Rank politicians by trading activity and recency in the last 90 days."""
        from collections import defaultdict

        today = datetime.now(timezone.utc).date()
        cutoff = (today - timedelta(days=90)).isoformat()

        stats: dict[str, dict] = defaultdict(lambda: {
            "name": "",
            "party": "",
            "chamber": "",
            "recent_dates": [],
            "tickers": set(),
            "recent_buys": 0,
        })

        for t in trades:
            s = stats[t.politician_slug]
            s["name"] = t.politician_name
            s["party"] = t.party
            s["chamber"] = t.chamber
            if t.transaction_date >= cutoff:
                s["recent_dates"].append(t.transaction_date)
                s["tickers"].add(t.ticker)
                if t.transaction_type == "purchase":
                    s["recent_buys"] += 1

        scores: list[PoliticianScore] = []
        for slug, s in stats.items():
            if not s["recent_dates"]:
                continue
            last_date = max(s["recent_dates"])
            days_ago = (today - datetime.fromisoformat(last_date).date()).days
            count = len(s["recent_dates"])
            buy_ratio = s["recent_buys"] / count if count else 0.0
            # Score: activity × recency × ticker diversity
            score = count * (100.0 / (days_ago + 1)) * (1 + len(s["tickers"]) * 0.1)
            scores.append(PoliticianScore(
                politician_name=s["name"],
                politician_slug=slug,
                party=s["party"],
                chamber=s["chamber"],
                trade_count_90d=count,
                last_trade_date=last_date,
                days_since_last_trade=days_ago,
                unique_tickers=len(s["tickers"]),
                buy_ratio=round(buy_ratio, 2),
                score=round(score, 2),
            ))

        scores.sort(key=lambda x: x.score, reverse=True)
        return scores[:top_n]

    # ------------------------------------------------------------------ #
    # Internal — API fetch
    # ------------------------------------------------------------------ #

    async def _fetch_api_trades(self, pages: int) -> list[PoliticianTrade]:
        all_trades: list[PoliticianTrade] = []
        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=self.TIMEOUT, follow_redirects=True
        ) as client:
            for page in range(1, pages + 1):
                try:
                    resp = await client.get(
                        f"{self.API_BASE}/trade",
                        params={"page": page, "pageSize": 50, "sortBy": "-publishedDate"},
                    )
                    if resp.status_code != 200:
                        logger.debug("API page %d → HTTP %d", page, resp.status_code)
                        break
                    data = resp.json()
                    items = data.get("data") or []
                    if not items:
                        break
                    parsed = [t for item in items if (t := _parse_trade(item))]
                    all_trades.extend(parsed)
                    # Stop early if the page was short (last page)
                    if len(items) < 50:
                        break
                except Exception as exc:
                    logger.warning("Capitol Trades API page %d failed: %s", page, exc)
                    break
        return all_trades

    # ------------------------------------------------------------------ #
    # Internal — HTML scrape fallback
    # ------------------------------------------------------------------ #

    async def _fetch_html_trades(self, pages: int) -> list[PoliticianTrade]:
        """Scrape trades from the HTML page (Next.js __NEXT_DATA__ or table)."""
        from bs4 import BeautifulSoup

        all_trades: list[PoliticianTrade] = []
        html_headers = {**_HEADERS, "Accept": "text/html,application/xhtml+xml,*/*"}

        async with httpx.AsyncClient(
            headers=html_headers, timeout=self.TIMEOUT, follow_redirects=True
        ) as client:
            for page in range(1, pages + 1):
                try:
                    params = {"page": page} if page > 1 else {}
                    resp = await client.get(f"{self.SITE_BASE}/trades", params=params)
                    if resp.status_code != 200:
                        break
                    soup = BeautifulSoup(resp.text, "lxml")

                    # Next.js embeds page data in a <script id="__NEXT_DATA__"> tag
                    next_tag = soup.find("script", id="__NEXT_DATA__")
                    if next_tag and next_tag.string:
                        try:
                            payload = json.loads(next_tag.string)
                            page_props = payload.get("props", {}).get("pageProps", {})
                            # Try multiple possible data locations
                            raw_list = (
                                page_props.get("trades", {}).get("data")
                                or page_props.get("data")
                                or []
                            )
                            if raw_list:
                                parsed = [t for item in raw_list if (t := _parse_trade(item))]
                                all_trades.extend(parsed)
                                if parsed:
                                    continue  # Got data; move to next page
                        except (json.JSONDecodeError, AttributeError):
                            pass

                    # Fallback: look for a <table> with trade rows
                    rows = soup.select("table tbody tr")
                    for row in rows:
                        cells = row.find_all("td")
                        if len(cells) < 5:
                            continue
                        try:
                            # Positional parsing: 0=politician, 1=asset, 2=type, 3=date, 4=filed, 5=amount
                            pol_text = cells[0].get_text(" ", strip=True)
                            asset_text = cells[1].get_text(" ", strip=True)
                            ticker_m = re.search(r"\b([A-Z]{1,5})\b", asset_text)
                            if not ticker_m:
                                continue
                            raw = {
                                "_id": f"html-{pol_text[:20]}-{ticker_m.group()}-{page}-{len(all_trades)}",
                                "politician": {
                                    "name": pol_text,
                                    "slug": pol_text.lower()[:40].replace(" ", "-"),
                                    "party": "Unknown",
                                    "chamber": "Unknown",
                                },
                                "asset": {
                                    "ticker": ticker_m.group(),
                                    "name": asset_text,
                                    "assetType": "stock",
                                },
                                "txType": cells[2].get_text(strip=True),
                                "txDate": cells[3].get_text(strip=True),
                                "publishedDate": cells[4].get_text(strip=True) if len(cells) > 4 else "",
                                "amount": cells[5].get_text(strip=True) if len(cells) > 5 else "",
                            }
                            t = _parse_trade(raw)
                            if t:
                                all_trades.append(t)
                        except Exception:
                            continue

                    if not all_trades:
                        # Nothing parsed on this page; stop trying
                        break

                except Exception as exc:
                    logger.warning("HTML scrape page %d failed: %s", page, exc)
                    break

        return all_trades
