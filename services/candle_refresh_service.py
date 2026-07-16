"""candle_refresh_service.py — keep the bar cache current, incrementally.

The backfill (``scripts/backfill_all.py``) fills deep history once. This
service does the opposite job: a small, cheap **top-up** that fetches only
the recent tail of each series and merges it into the existing CSV, so
``data/historical/{SYMBOL}_{interval}.csv`` stays current without
re-downloading years of history.

Used by:
  * the APScheduler ``candle_refresh`` job (see ``services/scheduler.py``)
  * ``scripts/refresh_candles.py`` for a manual run

Source routing matches the backfill:
    equity 1d        -> the configured daily source (default yfinance for the
                        tail — reliable, no local HF-shard dependency)
    equity intraday  -> Alpaca (free, deep, no 60-day cap)
    FX / gold        -> IBKR (needs the gateway; FX majors + XAUUSD)

Every fetch is best-effort: on any failure the symbol keeps its cached bars
and we log + move on. A stale bar is better than a crash.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from services.fvg_scan_service import DEFAULT_SYMBOLS as _FX_SYMBOLS
from services.settings_service import DATA_DIR

log = logging.getLogger(__name__)

HIST_DIR: Path = DATA_DIR / "historical"
_FX_SET = {s.upper() for s in _FX_SYMBOLS}

# How far back to pull on a refresh, per interval. Generous enough to cover a
# long weekend / holiday gap and any late-arriving bars, small enough to stay
# cheap. The merge dedupes overlap, so over-fetching the tail is harmless.
_LOOKBACK_DAYS: dict[str, int] = {
    "1d": 10, "1h": 12, "30m": 7, "15m": 7, "5m": 5,
}


def resolve_source(symbol: str, interval: str, daily_source: str = "yfinance") -> str:
    """Best source for a (symbol, interval) top-up."""
    if symbol.upper() in _FX_SET:
        return "ibkr"
    if interval == "1d":
        return daily_source
    return "alpaca"


def _merge_into_csv(path: Path, new_df: pd.DataFrame) -> pd.DataFrame:
    """Merge freshly-fetched bars (lowercase ohlcv, UTC index) into the CSV,
    dedupe on timestamp keeping the newest, preserve deep history. Writes the
    {datetime, Open..Volume} shape the rest of the app reads back."""
    frames = []
    if path.exists():
        old = pd.read_csv(path)
        dc = old.columns[0]
        old[dc] = pd.to_datetime(old[dc], utc=True, errors="coerce")
        old = old.dropna(subset=[dc]).set_index(dc)
        old.columns = [c.lower() for c in old.columns]
        keep = [c for c in ("open", "high", "low", "close", "volume") if c in old.columns]
        frames.append(old[keep])
    cols = [c for c in ("open", "high", "low", "close", "volume") if c in new_df.columns]
    frames.append(new_df[cols])
    merged = pd.concat(frames)
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    out = merged.rename(columns={"open": "Open", "high": "High", "low": "Low",
                                 "close": "Close", "volume": "Volume"})
    out.index.name = "datetime"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path)
    return merged


async def _fetch_window(symbol: str, interval: str, source: str, start: str) -> pd.DataFrame | None:
    """Fetch the recent window from the given source. Canonical lowercase
    OHLCV, UTC index. Returns None on empty."""
    from services import hf_data_service as H

    if source == "alpaca":
        df = await H._fetch_symbol_alpaca(symbol, start=start, end=None, interval=interval)
    elif source == "ibkr":
        df = await H._fetch_symbol_ibkr(symbol, start=start, end=None, interval=interval)
    elif source == "hf":
        df = await H.fetch_symbol_hf(symbol, start=start, end=None)
    else:  # yfinance
        df = await H._fetch_symbol_yf(symbol, start=start, end=None, interval=interval)
    if df is None or getattr(df, "empty", True):
        return None
    return df


async def refresh_symbol(
    symbol: str,
    interval: str,
    *,
    source: str | None = None,
    daily_source: str = "yfinance",
    lookback_days: int | None = None,
) -> dict:
    """Top up one (symbol, interval). Returns a status dict."""
    sym = symbol.upper()
    src = source or resolve_source(sym, interval, daily_source)
    look = lookback_days or _LOOKBACK_DAYS.get(interval, 7)
    start = (date.today() - timedelta(days=look)).isoformat()
    path = HIST_DIR / f"{sym}_{interval}.csv"
    try:
        new = await _fetch_window(sym, interval, src, start)
    except Exception as exc:  # noqa: BLE001
        log.info("refresh %s %s via %s failed: %s", sym, interval, src, exc)
        return {"symbol": sym, "interval": interval, "ok": False,
                "source": src, "error": f"{type(exc).__name__}: {exc}"}
    if new is None:
        return {"symbol": sym, "interval": interval, "ok": True,
                "source": src, "added": 0, "note": "no_new_bars"}
    try:
        merged = _merge_into_csv(path, new)
    except Exception as exc:  # noqa: BLE001
        log.warning("refresh %s %s merge failed: %s", sym, interval, exc)
        return {"symbol": sym, "interval": interval, "ok": False,
                "source": src, "error": f"merge: {exc}"}
    last = merged.index[-1] if len(merged) else None
    return {"symbol": sym, "interval": interval, "ok": True, "source": src,
            "added": len(new), "rows": len(merged),
            "last": last.isoformat() if last is not None else None}


async def refresh_daily_batched(
    symbols: list[str],
    *,
    lookback_days: int = 20,
    chunk: int = 50,
    progress=None,
) -> dict:
    """Top up **daily** bars for many equities fast, via Alpaca's multi-symbol
    endpoint (one request per ``chunk`` symbols instead of one per symbol).

    Merges the recent tail into each CSV with ``_merge_into_csv`` so deep
    history is preserved. Best-effort: a failed chunk is logged and skipped,
    the rest still refresh. Returns a summary dict.

    ``progress`` — optional ``callable(done:int, total:int, note:str)`` for UI.
    """
    import asyncio

    from services import hf_data_service as H

    syms = [s.upper() for s in symbols if s and s.upper() not in _FX_SET]
    start = (date.today() - timedelta(days=max(lookback_days, 3))).isoformat()
    ok = fail = added = 0
    total = len(syms)
    done = 0
    for i in range(0, total, chunk):
        batch = syms[i:i + chunk]
        try:
            frames = await asyncio.to_thread(
                H._fetch_batch_alpaca_sync, batch, start, None, "1d",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("daily batch %d-%d fetch failed: %s", i, i + len(batch), exc)
            fail += len(batch)
            done += len(batch)
            if progress:
                progress(done, total, f"batch fetch error: {type(exc).__name__}")
            continue
        for sym in batch:
            done += 1
            df = frames.get(sym)
            if df is None or getattr(df, "empty", True):
                # No bars in the window (holiday-only window, or symbol
                # unknown to Alpaca) — not fatal, keep cached history.
                ok += 1
                continue
            try:
                await asyncio.to_thread(
                    _merge_into_csv, HIST_DIR / f"{sym}_1d.csv", df,
                )
                ok += 1
                added += len(df)
            except Exception as exc:  # noqa: BLE001
                log.warning("daily merge %s failed: %s", sym, exc)
                fail += 1
        if progress:
            progress(done, total, f"{done}/{total} symbols")
    summary = {"symbols": total, "interval": "1d", "ok": ok,
               "failed": fail, "bars_added": added}
    log.info("daily batched refresh: %s", summary)
    return summary


async def refresh_many(
    symbols: list[str],
    intervals: list[str],
    *,
    daily_source: str = "yfinance",
    pace_s: float = 0.3,
) -> dict:
    """Top up every (symbol, interval). Best-effort, never raises."""
    import asyncio

    ok = fail = added = 0
    for interval in intervals:
        for sym in symbols:
            # FX has no daily/hourly bars in this app — intraday only.
            if sym.upper() in _FX_SET and interval in ("1d", "1h"):
                continue
            res = await refresh_symbol(sym, interval, daily_source=daily_source)
            if res.get("ok"):
                ok += 1
                added += int(res.get("added", 0) or 0)
            else:
                fail += 1
            if pace_s:
                await asyncio.sleep(pace_s)
    summary = {"symbols": len(symbols), "intervals": intervals,
               "ok": ok, "failed": fail, "bars_added": added}
    log.info("candle refresh: %s", summary)
    return summary
