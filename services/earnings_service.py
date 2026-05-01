"""earnings_service.py — next earnings date lookup with TTL cache.

Used by pipeline_service to populate ``MarketState.earnings_within_hours``,
which compliance gate C7 (earnings blackout) reads to block any plan
within ``settings.compliance.earnings_blackout_hours`` of an upcoming
report.

Data source: yfinance ``Ticker.calendar``, which returns a dict with
an ``Earnings Date`` key whose value is either a single date or a list
of dates representing the next 1–3 earnings events. We pick the next
future event and convert to hours-from-now.

Caching: 4-hour TTL per symbol, in-process. Earnings dates don't shift
intra-session, and 4h ensures we re-check after a long-running
trading session. No persistence — process restart re-warms the cache.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# {symbol: (hours_to_earnings_or_None, fetched_at_unix)}
_CACHE: dict[str, tuple[float | None, float]] = {}
_TTL_SECONDS = 4 * 3600  # refresh every 4 hours


def _now() -> float:
    return time.time()


def _next_earnings_dt(cal: Any) -> datetime | None:
    """Pull the next future earnings datetime from yfinance's calendar dict."""
    if not cal:
        return None
    raw = None
    try:
        raw = cal.get("Earnings Date") if isinstance(cal, dict) else None
    except Exception:                                                 # noqa: BLE001
        return None
    if raw is None:
        return None
    candidates: list[datetime] = []
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    for it in items:
        if isinstance(it, datetime):
            candidates.append(it)
        elif isinstance(it, date):
            # Treat the date as 09:00 ET that day (typical pre-open report).
            # We only need approx hours-to-event, not the exact minute.
            candidates.append(datetime.combine(it, datetime.min.time()).replace(hour=9))

    now_naive = datetime.now()
    future = [c for c in candidates if c >= now_naive]
    if not future:
        return None
    return min(future)


def _fetch_sync(symbol: str) -> float | None:
    """Synchronous yfinance lookup. Returns hours_to_next_earnings,
    or None if unknown / no upcoming event found."""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        cal = t.calendar
    except Exception as exc:                                          # noqa: BLE001
        logger.debug("earnings_service: %s lookup failed: %s", symbol, exc)
        return None

    next_dt = _next_earnings_dt(cal)
    if next_dt is None:
        return None
    delta = next_dt - datetime.now()
    return max(0.0, delta.total_seconds() / 3600.0)


async def get_hours_to_next_earnings(symbol: str) -> float | None:
    """Return hours until the next earnings event for ``symbol``, or
    None if not known. Cached for 4h per symbol."""
    sym = symbol.upper()
    cached = _CACHE.get(sym)
    if cached is not None and (_now() - cached[1]) < _TTL_SECONDS:
        return cached[0]
    hours = await asyncio.to_thread(_fetch_sync, sym)
    _CACHE[sym] = (hours, _now())
    return hours


def clear_cache() -> None:
    _CACHE.clear()
