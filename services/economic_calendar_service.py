"""economic_calendar_service.py — high-impact macro event windows + FRED.

Two responsibilities:

1. **Event windows** — given a timestamp, return the set of high-impact
   macro releases (FOMC decisions, CPI, NFP, PCE, GDP, retail sales)
   scheduled within ±N hours. The Alpha Score agent uses this to
   tighten stops or pause new long entries inside the 24-hour
   pre-release window.

2. **FRED integration** — a thin async client over
   https://api.stlouisfed.org/fred/series/observations. Pulls daily
   series for DGS2, DGS10, DTWEXBGS (DXY proxy), DFF (effective Fed
   funds rate). On-disk cache at ``data/fred_cache/{series_id}.csv``
   so backtest replays don't hammer the API. ``FRED_API_KEY`` env
   var is required for live fetches; with no key we fall back to
   the cache (and log a warning if it's empty).

A *minimal* known-event seed list is shipped in this file so the
strategy works offline / without a FRED key. The seed covers the
major recurring events (monthly CPI, monthly NFP, 8-per-year FOMC).
For live precision the seed can be augmented from the FRED release
schedule or any standard economic calendar feed.
"""
from __future__ import annotations

import asyncio
import calendar
import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd

from models.alpha_score import EconomicEvent
from services.settings_service import DATA_DIR

log = logging.getLogger(__name__)

FRED_CACHE_DIR: Path = DATA_DIR / "fred_cache"
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# Series we care about for the macro pulse.
FRED_SERIES = {
    "DGS2":      "2-Year Treasury Constant Maturity",
    "DGS10":     "10-Year Treasury Constant Maturity",
    "DTWEXBGS":  "Trade-Weighted USD Broad Index (DXY proxy)",
    "DFF":       "Federal Funds Effective Rate",
    "T10Y2Y":    "10Y minus 2Y Treasury Spread",
}


# --------------------------------------------------------------------------- #
# FRED client
# --------------------------------------------------------------------------- #


def _cache_path(series_id: str) -> Path:
    FRED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return FRED_CACHE_DIR / f"{series_id}.csv"


def _read_cache_sync(series_id: str) -> pd.DataFrame | None:
    p = _cache_path(series_id)
    if not p.exists():
        return None
    try:
        df = pd.read_csv(p, parse_dates=["date"])
        return df.sort_values("date")
    except Exception as e:                         # noqa: BLE001
        log.warning("FRED cache read failed (%s): %s", series_id, e)
        return None


def _write_cache_sync(series_id: str, df: pd.DataFrame) -> None:
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    df.to_csv(_cache_path(series_id), index=False)


# In-memory dedup so a backtest hitting score_symbol thousands of times
# doesn't make 40,000 FRED calls — once we have the full series for a
# given series_id this process, every subsequent call returns the same
# DataFrame. Process-level (lost on restart); the disk cache survives.
_FRED_MEMORY_CACHE: dict[str, pd.DataFrame] = {}
_FRED_MEMORY_LOCK: asyncio.Lock | None = None


def _get_fred_lock() -> asyncio.Lock:
    """Lazy-init the lock so tests / sync imports don't need a loop."""
    global _FRED_MEMORY_LOCK
    if _FRED_MEMORY_LOCK is None:
        _FRED_MEMORY_LOCK = asyncio.Lock()
    return _FRED_MEMORY_LOCK


async def fetch_fred_series(
    series_id: str,
    *,
    api_key: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """Fetch a FRED series, falling back to disk cache when offline.

    Returns a DataFrame with columns ``[date, value]``. ``value`` is
    float; FRED's "." (no observation) is dropped. Caches in memory
    so a single FRED call serves the whole process lifetime.
    """
    # Memory-cache fast path — only honored when caller didn't pin a
    # specific date window (start/end is unused inside the function
    # anyway since FRED returns the full series and we slice later).
    if start is None and end is None and series_id in _FRED_MEMORY_CACHE:
        return _FRED_MEMORY_CACHE[series_id]

    api_key = api_key or os.environ.get("FRED_API_KEY")
    cached = await asyncio.to_thread(_read_cache_sync, series_id)

    # Hold the lock through the HTTP call so 8 concurrent backtest workers
    # don't all stampede FRED for the same series_id. The first coroutine
    # makes the network call; the rest wait, recheck the memory cache,
    # and return the populated entry without ever hitting the wire.
    async with _get_fred_lock():
        # Recheck under lock — another coroutine may have populated the
        # cache while we were waiting for it.
        if start is None and end is None and series_id in _FRED_MEMORY_CACHE:
            return _FRED_MEMORY_CACHE[series_id]

        if not api_key:
            if cached is None or cached.empty:
                log.warning(
                    "fetch_fred_series: no FRED_API_KEY and no cache for %s; "
                    "returning empty frame", series_id,
                )
                empty = pd.DataFrame(columns=["date", "value"])
                _FRED_MEMORY_CACHE[series_id] = empty
                return empty
            _FRED_MEMORY_CACHE[series_id] = cached
            return cached

        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
        }
        if start:
            params["observation_start"] = start.isoformat()
        if end:
            params["observation_end"] = end.isoformat()

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(FRED_BASE_URL, params=params)
                r.raise_for_status()
                payload = r.json()
        except Exception as e:                     # noqa: BLE001
            # Redact api_key from exception messages — httpx includes the
            # full URL on raise_for_status, leaking the FRED key into logs.
            import re as _re
            msg = str(e)
            if api_key and api_key in msg:
                msg = msg.replace(api_key, "***REDACTED***")
            msg = _re.sub(r"api_key=[A-Za-z0-9]+", "api_key=***REDACTED***", msg)
            log.warning("FRED fetch failed for %s: %s — using cache", series_id, msg)
            # Memo the failure-fallback so a flaky FRED endpoint doesn't
            # cause a 40,000-call retry storm during a backtest.
            fallback = cached if cached is not None else pd.DataFrame(columns=["date", "value"])
            if start is None and end is None:
                _FRED_MEMORY_CACHE[series_id] = fallback
            return fallback

        rows: list[dict] = []
        for obs in payload.get("observations", []):
            if obs.get("value") in (None, ".", ""):
                continue
            try:
                rows.append({
                    "date": pd.Timestamp(obs["date"]).normalize(),
                    "value": float(obs["value"]),
                })
            except (TypeError, ValueError):
                continue
        df = pd.DataFrame(rows)
        if df.empty:
            result = cached if cached is not None else df
            if start is None and end is None:
                _FRED_MEMORY_CACHE[series_id] = result
            return result

        if cached is not None and not cached.empty:
            df = pd.concat([cached, df], ignore_index=True)
        await asyncio.to_thread(_write_cache_sync, series_id, df)
        df = df.sort_values("date").reset_index(drop=True)
        if start is None and end is None:
            _FRED_MEMORY_CACHE[series_id] = df
        return df


async def latest_value(series_id: str, *, as_of: datetime | None = None) -> float | None:
    """Return the most recent FRED observation at-or-before ``as_of``."""
    df = await fetch_fred_series(series_id)
    if df.empty:
        return None
    if as_of is not None:
        cutoff = pd.Timestamp(as_of).tz_localize(None).normalize()
        df = df[df["date"] <= cutoff]
        if df.empty:
            return None
    return float(df["value"].iloc[-1])


async def change_over(
    series_id: str, *, days: int, as_of: datetime | None = None,
) -> float | None:
    """Return the simple difference between the latest value and the value ``days`` back."""
    df = await fetch_fred_series(series_id)
    if df.empty:
        return None
    if as_of is not None:
        cutoff = pd.Timestamp(as_of).tz_localize(None).normalize()
        df = df[df["date"] <= cutoff]
    if len(df) < 2:
        return None
    latest = df.iloc[-1]
    target_date = latest["date"] - pd.Timedelta(days=days)
    prior = df[df["date"] <= target_date]
    if prior.empty:
        return None
    return float(latest["value"] - prior.iloc[-1]["value"])


# --------------------------------------------------------------------------- #
# Recurring high-impact event seed
# --------------------------------------------------------------------------- #
#
# This seed covers the predictable monthly cadence of the three biggest
# moves: NFP (1st Friday, 8:30 ET), CPI (mid-month Tuesday, 8:30 ET),
# and FOMC decisions (8 scheduled meetings/year, 14:00 ET on the second
# day of the meeting). Treat the FOMC list as approximate — the actual
# 2026 schedule from federalreserve.gov should be substituted in
# production. A blackout window matters more than perfect timestamps.

# FOMC 2025–2026 announcement dates (approximate, 14:00 ET).
_FOMC_DATES_ISO = [
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-17",
    "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-16",
]


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _et_naive_to_utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """Approximate ET → UTC conversion. ET is UTC-5 (EST) Nov–Mar, UTC-4 (EDT) Mar–Nov.

    We use a simple month-based heuristic; precise DST boundaries don't
    matter for a pause-window check that operates on hour resolution.
    """
    offset = 4 if 3 <= month <= 10 else 5
    return datetime(year, month, day, hour + offset, minute, tzinfo=timezone.utc)


def _first_friday(year: int, month: int) -> date:
    cal = calendar.Calendar()
    for d in cal.itermonthdates(year, month):
        if d.month == month and d.weekday() == calendar.FRIDAY:
            return d
    raise RuntimeError(f"no Friday in {year}-{month}")  # impossible


def _second_tuesday(year: int, month: int) -> date:
    cal = calendar.Calendar()
    tuesdays = [d for d in cal.itermonthdates(year, month)
                if d.month == month and d.weekday() == calendar.TUESDAY]
    if len(tuesdays) < 2:
        raise RuntimeError(f"<2 Tuesdays in {year}-{month}")
    return tuesdays[1]


def known_events(window_start: datetime, window_end: datetime) -> list[EconomicEvent]:
    """Return seeded high-impact events whose scheduled_at falls in [start, end]."""
    start = _to_utc(window_start)
    end = _to_utc(window_end)
    events: list[EconomicEvent] = []

    cur = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    while cur <= last:
        nfp_date = _first_friday(cur.year, cur.month)
        nfp_dt = _et_naive_to_utc(nfp_date.year, nfp_date.month, nfp_date.day, 8, 30)
        events.append(EconomicEvent(
            name="Non-Farm Payrolls",
            category="NFP",
            scheduled_at=nfp_dt,
            importance="high",
        ))

        cpi_date = _second_tuesday(cur.year, cur.month)
        cpi_dt = _et_naive_to_utc(cpi_date.year, cpi_date.month, cpi_date.day, 8, 30)
        events.append(EconomicEvent(
            name="CPI",
            category="CPI",
            scheduled_at=cpi_dt,
            importance="high",
        ))

        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)

    for iso in _FOMC_DATES_ISO:
        d = date.fromisoformat(iso)
        dt = _et_naive_to_utc(d.year, d.month, d.day, 14, 0)
        events.append(EconomicEvent(
            name="FOMC Decision",
            category="FOMC",
            scheduled_at=dt,
            importance="high",
        ))

    return [e for e in events if start <= e.scheduled_at <= end]


def events_within(
    as_of: datetime,
    *,
    hours_before: int = 24,
    hours_after: int = 2,
) -> list[EconomicEvent]:
    """Events scheduled in [as_of - hours_after, as_of + hours_before].

    Naming note: we want events that are *coming up soon* (within
    `hours_before` hours from now) plus events that *just happened*
    (within `hours_after` hours). Both raise volatility.
    """
    start = _to_utc(as_of) - timedelta(hours=hours_after)
    end = _to_utc(as_of) + timedelta(hours=hours_before)
    return known_events(start, end)


def in_event_blackout(as_of: datetime, *, hours_before: int = 24) -> tuple[bool, list[EconomicEvent]]:
    """Are we inside the pre-release blackout for any high-impact event?"""
    start = _to_utc(as_of)
    end = start + timedelta(hours=hours_before)
    upcoming = [e for e in known_events(start, end) if e.importance == "high"]
    return (len(upcoming) > 0, upcoming)
