"""hf_data_service.py — bulk OHLCV fetch with three source backends.

1. **HF Stocks-Daily-Price** (default, no auth) — paperswithbacktest's public
   parquet dataset of 7000+ US stocks. Fast, no rate limits. **Daily only,
   stocks only — no ETFs (SPY/QQQ etc.) and no indices (^GSPC).**

2. **yfinance** (fallback) — covers everything Yahoo does: ETFs, indices,
   foreign tickers. Caps: ~730d for 1h, ~60d for 30m bars. Reuses the same
   caching path as ``services/data_service``.

3. **Alpaca** — historical bars via ``StockHistoricalDataClient``. Paid-for-free
   on a paper account, SIP feed, ~5y of intraday (30m/1h) history. **The right
   source when you need 30m bars deep enough for backtest sample sizes.**

The saved CSV format is identical for both sources so a downstream
``get_bars(symbol, "1d")`` reads the local file without touching network:

    Date,Open,High,Low,Close,Volume
    2010-01-04 00:00:00+00:00,...

Useful for bulk-seeding the bar cache before backtests where pulling
100+ symbols from yfinance live would be rate-limited and slow.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from services.settings_service import DATA_DIR

log = logging.getLogger(__name__)

HISTORICAL_DIR: Path = DATA_DIR / "historical"

_HF_DATASET = "paperswithbacktest/Stocks-Daily-Price"
_HF_SHARDS = 4
_HF_URL_TEMPLATE = (
    "hf://datasets/{ds}@~parquet/default/train/{idx:04d}.parquet"
)
_HF_LOCAL_CACHE: Path = DATA_DIR / "hf_cache" / "stocks_daily_price"


def _shard_urls() -> list[str]:
    return [
        _HF_URL_TEMPLATE.format(ds=_HF_DATASET, idx=i) for i in range(_HF_SHARDS)
    ]


def _local_shard_paths() -> list[Path]:
    return [_HF_LOCAL_CACHE / f"{i:04d}.parquet" for i in range(_HF_SHARDS)]


def ensure_hf_shards_local() -> list[Path]:
    """Download all 4 HF parquet shards to local disk once. ~510 MB total.

    Subsequent reads filter locally — no network, no rate-limit risk.
    Idempotent: returns immediately if all 4 files already exist with size > 50 MB.
    """
    _HF_LOCAL_CACHE.mkdir(parents=True, exist_ok=True)
    paths = _local_shard_paths()
    urls = _shard_urls()

    needs_download = []
    for p, u in zip(paths, urls):
        if not p.exists() or p.stat().st_size < 50 * 1024 * 1024:
            needs_download.append((p, u))

    if not needs_download:
        log.info("hf_data_service: all %d shards already cached (%s)",
                 len(paths), _HF_LOCAL_CACHE)
        return paths

    import urllib.request
    for p, u in needs_download:
        # Translate hf:// URL to https:// for direct download
        # hf://datasets/{ds}@~parquet/default/train/0000.parquet
        # -> https://huggingface.co/datasets/{ds}/resolve/refs%2Fconvert%2Fparquet/default/train/0000.parquet
        ds_part = u.split("@~parquet/", 1)[1]
        https_url = (
            f"https://huggingface.co/datasets/{_HF_DATASET}/"
            f"resolve/refs%2Fconvert%2Fparquet/{ds_part}"
        )
        log.info("downloading shard: %s", https_url)
        urllib.request.urlretrieve(https_url, p)
        log.info("  saved %.1f MB to %s", p.stat().st_size / (1024 * 1024), p.name)

    return paths


def _cache_path(symbol: str) -> Path:
    return HISTORICAL_DIR / f"{symbol.upper()}_1d.csv"


def _fetch_symbol_sync(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Sync fetch — pulls all 4 shards filtered by symbol, returns canonical frame.

    Columns returned: open, high, low, close, volume. Index is tz-aware UTC.

    Reads from LOCAL parquet shards (in `data/hf_cache/`) when available,
    falls back to streaming over HTTPS only if the local copy is missing.
    Always prefer the local path for bulk fetches — HF rate-limits aggressive
    streaming.
    """
    sym = symbol.upper()
    frames = []

    local_paths = _local_shard_paths()
    use_local = all(p.exists() and p.stat().st_size > 50 * 1024 * 1024
                    for p in local_paths)
    sources = local_paths if use_local else _shard_urls()

    for src in sources:
        try:
            part = pd.read_parquet(
                src,
                engine="pyarrow",
                filters=[("symbol", "=", sym)],
                columns=["date", "open", "high", "low", "close", "volume"],
            )
        except Exception as exc:                                       # noqa: BLE001
            log.warning("HF shard read failed (%s): %s", src, exc)
            continue
        if not part.empty:
            frames.append(part)

    if not frames:
        raise ValueError(
            f"no rows for {sym!r} in {_HF_DATASET} (bad ticker or network error)"
        )

    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.set_index("date").sort_index()
    df.index.name = "Date"

    if start is not None:
        df = df.loc[pd.Timestamp(start, tz="UTC"):]
    if end is not None:
        df = df.loc[: pd.Timestamp(end, tz="UTC")]

    df = df.dropna(how="all")
    return df[["open", "high", "low", "close", "volume"]]


def _save_sync(symbol: str, df: pd.DataFrame) -> Path:
    """Write the canonical CSV expected by `services/data_service`."""
    HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)
    out = _cache_path(symbol)
    out_df = df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )
    out_df.to_csv(out)
    log.info("hf_data_service: cached %d rows → %s", len(out_df), out.name)
    return out


# --------------------------------------------------------------------------- #
# Public async API
# --------------------------------------------------------------------------- #


async def fetch_symbol_hf(
    symbol: str,
    start: str | None = "2010-01-01",
    end: str | None = None,
) -> pd.DataFrame:
    """Fetch a single symbol from the HF stocks dataset; do NOT save to disk."""
    return await asyncio.to_thread(_fetch_symbol_sync, symbol, start, end)


async def _fetch_symbol_yf(
    symbol: str,
    start: str | None = "2010-01-01",
    end: str | None = None,
    interval: str = "1d",
) -> pd.DataFrame:
    """yfinance path — supports 1d/1h/30m via the existing data_service cache."""
    from services import data_service

    await data_service.refresh_bars(symbol, interval)                  # type: ignore[arg-type]
    df = await data_service.get_bars(
        symbol, interval, min_bars=1, download_if_missing=False        # type: ignore[arg-type]
    )
    if start is not None:
        df = df.loc[pd.Timestamp(start, tz="UTC"):]
    if end is not None:
        df = df.loc[: pd.Timestamp(end, tz="UTC")]
    return df


# --------------------------------------------------------------------------- #
# Alpaca historical bars
# --------------------------------------------------------------------------- #

_ALPACA_INTERVAL_TO_SDK = {
    # (amount, unit) used to build alpaca.data.timeframe.TimeFrame at runtime
    "1d": (1, "Day"),
    "1h": (1, "Hour"),
    "30m": (30, "Minute"),
    "15m": (15, "Minute"),
    "5m": (5, "Minute"),
}


def _fetch_symbol_alpaca_sync(
    symbol: str,
    start: str,
    end: str | None,
    interval: str,
) -> pd.DataFrame:
    """Sync Alpaca historical-bars fetch. Returns canonical OHLCV frame."""
    from datetime import datetime as _dt
    from alpaca.data.historical.stock import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    key = os.getenv("ALPACA_TRADING_KEY_ID") or os.getenv("ALPACA_API_KEY")
    secret = os.getenv("ALPACA_TRADING_SECRET") or os.getenv("ALPACA_API_SECRET")
    if not key or not secret:
        raise RuntimeError(
            "Alpaca credentials missing — set ALPACA_API_KEY + "
            "ALPACA_API_SECRET in .env or use the /broker page."
        )

    if interval not in _ALPACA_INTERVAL_TO_SDK:
        raise ValueError(
            f"unsupported Alpaca interval {interval!r}; expected one of "
            f"{list(_ALPACA_INTERVAL_TO_SDK)}"
        )
    amount, unit = _ALPACA_INTERVAL_TO_SDK[interval]
    tf_unit = getattr(TimeFrameUnit, unit)
    timeframe = TimeFrame(amount, tf_unit)

    start_ts = _dt.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_ts = (
        _dt.fromisoformat(end).replace(tzinfo=timezone.utc)
        if end
        else None
    )

    # Dual-class tickers differ by source: yfinance/HF use a dash (BRK-B),
    # Alpaca uses a dot (BRK.B). Translate for the request only — the caller
    # still saves under the canonical dash name so the cache stays consistent.
    api_symbol = symbol.upper().replace("-", ".")

    # Feed: "sip" (full consolidated tape) or "iex" (free tier). Alpaca now
    # serves SIP historical to free accounts, but if yours rejects it set
    # ALPACA_DATA_FEED=iex in .env to fall back without a code change.
    feed = os.getenv("ALPACA_DATA_FEED", "sip").lower()
    client = StockHistoricalDataClient(api_key=key, secret_key=secret)
    req = StockBarsRequest(
        symbol_or_symbols=api_symbol,
        timeframe=timeframe,
        start=start_ts,
        end=end_ts,
        adjustment="all",
        feed=feed,
    )
    bars = client.get_stock_bars(req)
    df = bars.df  # multi-index (symbol, timestamp) → tabular
    if df is None or df.empty:
        raise ValueError(
            f"Alpaca returned no bars for {symbol} {interval} from {start}"
        )
    if "symbol" in df.index.names:
        df = df.reset_index(level="symbol", drop=True)
    return _normalize_alpaca_frame(df, interval)


def _normalize_alpaca_frame(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """tz-normalize, keep OHLCV, RTH-filter intraday. ``df`` is single-symbol
    (any symbol index level already dropped)."""
    df.index.name = "Date"
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep].sort_index()

    # Filter intraday bars to RTH (9:30-16:00 ET) so the saved CSV matches
    # what yfinance returns (RTH-only) — detectors that key off `bar.time()`
    # for c1/c2 slot identification rely on this contract.
    if interval in ("30m", "15m", "5m", "1h"):
        et = df.index.tz_convert("America/New_York")
        rth_mask = (
            ((et.hour == 9) & (et.minute >= 30))
            | ((et.hour > 9) & (et.hour < 16))
        )
        df = df[rth_mask]
    return df


def _fetch_batch_alpaca_sync(
    symbols: list[str],
    start: str,
    end: str | None,
    interval: str,
) -> dict[str, pd.DataFrame]:
    """Fetch bars for MANY symbols in ONE Alpaca request (the multi-symbol
    endpoint), returning {canonical_dash_symbol: frame}. This is the fast
    path for bulk backfill — one request per batch instead of one per symbol,
    so the ~200 req/min free limit stops being the bottleneck."""
    from datetime import datetime as _dt
    from alpaca.data.historical.stock import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    key = os.getenv("ALPACA_TRADING_KEY_ID") or os.getenv("ALPACA_API_KEY")
    secret = os.getenv("ALPACA_TRADING_SECRET") or os.getenv("ALPACA_API_SECRET")
    if not key or not secret:
        raise RuntimeError("Alpaca credentials missing — set ALPACA_API_KEY + ALPACA_API_SECRET")
    if interval not in _ALPACA_INTERVAL_TO_SDK:
        raise ValueError(f"unsupported Alpaca interval {interval!r}")

    amount, unit = _ALPACA_INTERVAL_TO_SDK[interval]
    timeframe = TimeFrame(amount, getattr(TimeFrameUnit, unit))
    start_ts = _dt.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_ts = _dt.fromisoformat(end).replace(tzinfo=timezone.utc) if end else None

    # dash (universe/yfinance) -> dot (Alpaca), with a reverse map to save
    # under the canonical dash name.
    api_syms = [s.upper().replace("-", ".") for s in symbols]
    rev = {a: s.upper() for a, s in zip(api_syms, symbols)}

    feed = os.getenv("ALPACA_DATA_FEED", "sip").lower()
    client = StockHistoricalDataClient(api_key=key, secret_key=secret)
    req = StockBarsRequest(
        symbol_or_symbols=api_syms, timeframe=timeframe,
        start=start_ts, end=end_ts, adjustment="all", feed=feed,
    )
    bars = client.get_stock_bars(req)
    df = bars.df
    out: dict[str, pd.DataFrame] = {}
    if df is None or df.empty:
        return out
    # Multi-index (symbol, timestamp) → per-symbol frames.
    if "symbol" in (df.index.names or []):
        for api_sym, sub in df.groupby(level="symbol"):
            sub = sub.reset_index(level="symbol", drop=True)
            out[rev.get(api_sym, api_sym)] = _normalize_alpaca_frame(sub, interval)
    else:  # single symbol came back flat
        only = api_syms[0]
        out[rev.get(only, only)] = _normalize_alpaca_frame(df, interval)
    return out


async def fetch_batch_alpaca_and_save(
    symbols: list[str],
    start: str | None = "2010-01-01",
    end: str | None = None,
    interval: str = "1d",
) -> dict[str, dict]:
    """Batch-fetch + persist. Returns {symbol: {ok, rows|error}} for each
    requested symbol (symbols Alpaca returns nothing for are marked ok=False,
    no bars)."""
    frames = await asyncio.to_thread(
        _fetch_batch_alpaca_sync, symbols, start or "2010-01-01", end, interval,
    )
    results: dict[str, dict] = {}
    for sym in symbols:
        df = frames.get(sym.upper())
        if df is None or df.empty:
            results[sym] = {"ok": False, "error": "no bars returned", "rows": 0}
            continue
        await asyncio.to_thread(_save_sync_interval, sym, df, interval)
        results[sym] = {"ok": True, "rows": len(df)}
    return results


async def _fetch_symbol_alpaca(
    symbol: str,
    start: str | None = "2010-01-01",
    end: str | None = None,
    interval: str = "1d",
) -> pd.DataFrame:
    return await asyncio.to_thread(
        _fetch_symbol_alpaca_sync,
        symbol,
        start or "2010-01-01",
        end,
        interval,
    )


# --------------------------------------------------------------------------- #
# IBKR (Interactive Brokers) — FX + stocks via a running IB Gateway/TWS.
# The API is NOT a cloud endpoint: it talks to a LOCAL gateway you must run.
# This is the source that unlocks forex candles (e.g. for fvg_continuation).
# --------------------------------------------------------------------------- #

_IBKR_BAR_SIZE = {"1d": "1 day", "1h": "1 hour", "30m": "30 mins",
                  "15m": "15 mins", "5m": "5 mins"}
_IBKR_DURATION = {"1d": "20 Y", "1h": "2 Y", "30m": "60 D",
                  "15m": "30 D", "5m": "10 D"}
# Per-request chunk when pulling YEARS (IBKR caps history per request; deep
# intraday must be paged backward). Conservative windows well inside IBKR limits.
_IBKR_CHUNK = {"1d": "15 Y", "1h": "6 M", "30m": "1 M", "15m": "1 M", "5m": "20 D"}
# Spot metals trade as CMDTY on IBKR, not FX pairs.
_IBKR_METALS = {"XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD"}
_IBKR_PACE_S = 3.0   # sleep between paged requests (IBKR pacing: ~60 req / 10 min)


def _ibkr_contract(s: str):
    """(contract, whatToShow) for a symbol: metal → CMDTY, 6-alpha → Forex, else Stock."""
    from ib_insync import Forex, Stock, Contract  # local import (optional dep)
    if s in _IBKR_METALS:
        return Contract(secType="CMDTY", symbol=s, exchange="SMART", currency="USD"), "MIDPOINT"
    if len(s) == 6 and s.isalpha():
        return Forex(s), "MIDPOINT"
    return Stock(s, "SMART", "USD"), "TRADES"


def _fetch_symbol_ibkr_sync(symbol: str, interval: str = "30m",
                            duration: str | None = None,
                            start: str | None = None) -> pd.DataFrame:
    """Pull historical bars from a running IB Gateway/TWS via ib_insync.

    Contract type is auto-detected: spot metals (XAUUSD…) → CMDTY, 6-letter
    alpha (EURUSD…) → Forex+MIDPOINT, else US Stock+TRADES. When ``start`` is
    given the request is **paged backward** in ``_IBKR_CHUNK`` windows until it
    reaches ``start`` (this is how you get YEARS of intraday — a single request
    is capped). Spins its own event loop, so call via ``asyncio.to_thread``.

    NOTE: only validated against a live IB Gateway on the operator's machine;
    the sandbox has no route to a local gateway.
    """
    import time as _time

    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    try:
        from ib_insync import IB, util
    except ImportError:
        try:
            from ib_async import IB, util  # maintained fork
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("ib_insync/ib_async not installed") from e

    bar_size = _IBKR_BAR_SIZE.get(interval)
    if bar_size is None:
        raise ValueError(f"ibkr: unsupported interval {interval!r}")

    s = symbol.upper().replace("/", "")
    contract, what = _ibkr_contract(s)

    host = os.getenv("IBKR_HOST", "127.0.0.1")
    port = int(os.getenv("IBKR_PORT", "4002"))
    client_id = int(os.getenv(
        "IBKR_DATA_CLIENT_ID",
        str(int(os.getenv("IBKR_CLIENT_ID", "7")) + 20),
    ))

    ib = IB()
    frames: list[pd.DataFrame] = []
    try:
        ib.connect(host, port, clientId=client_id, timeout=15)
        if start:
            # Page backward from "now" in chunks until we cover `start`.
            start_ts = pd.Timestamp(start).tz_localize("UTC") if pd.Timestamp(start).tzinfo is None else pd.Timestamp(start)
            chunk = _IBKR_CHUNK.get(interval, "1 M")
            end_dt = ""  # "" = now
            for _ in range(600):  # safety cap
                bars = ib.reqHistoricalData(
                    contract, endDateTime=end_dt, durationStr=chunk,
                    barSizeSetting=bar_size, whatToShow=what,
                    useRTH=False, formatDate=2,
                )
                d = util.df(bars)
                if d is None or d.empty:
                    break
                frames.append(d)
                earliest = pd.to_datetime(d["date"].iloc[0], utc=True)
                if earliest <= start_ts:
                    break
                end_dt = earliest.to_pydatetime()  # next chunk ends where this began
                _time.sleep(_IBKR_PACE_S)          # respect IBKR pacing
        else:
            dur = duration or _IBKR_DURATION.get(interval, "60 D")
            bars = ib.reqHistoricalData(
                contract, endDateTime="", durationStr=dur,
                barSizeSetting=bar_size, whatToShow=what,
                useRTH=False, formatDate=2,
            )
            d = util.df(bars)
            if d is not None and not d.empty:
                frames.append(d)
    finally:
        if ib.isConnected():
            ib.disconnect()

    if not frames:
        raise ValueError(
            f"ibkr returned no bars for {s} {interval}. "
            f"Is IB Gateway/TWS running with the API enabled?"
        )
    df = pd.concat(frames, ignore_index=True)
    df = df.rename(columns={"date": "datetime"})
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.drop_duplicates(subset="datetime").set_index("datetime").sort_index()
    if start:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"ibkr df missing column {col!r}")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0).clip(lower=0.0)
    return df[["open", "high", "low", "close", "volume"]]


async def _fetch_symbol_ibkr(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    interval: str = "30m",
) -> pd.DataFrame:
    # start → paged backward for deep history; no start → single default window.
    return await asyncio.to_thread(_fetch_symbol_ibkr_sync, symbol, interval, None, start)


def _save_sync_interval(symbol: str, df: pd.DataFrame, interval: str) -> Path:
    """Variant of _save_sync that writes to {SYMBOL}_{interval}.csv."""
    HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)
    out = HISTORICAL_DIR / f"{symbol.upper()}_{interval}.csv"
    out_df = df.rename(
        columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        }
    )
    out_df.to_csv(out)
    log.info("hf_data_service: cached %d rows → %s", len(out_df), out.name)
    return out


async def fetch_and_save(
    symbol: str,
    source: str = "auto",
    start: str | None = "2010-01-01",
    end: str | None = None,
    interval: str = "1d",
) -> dict:
    """Fetch + persist to ``data/historical/{SYMBOL}_{interval}.csv``.

    ``source``:
      * ``"hf"`` — HF stocks dataset (1d only; will error on 1h/30m)
      * ``"yfinance"`` — yfinance (1d/1h/30m, but 30m capped at ~60d)
      * ``"alpaca"`` — Alpaca historical bars (1d/1h/30m/15m/5m, ~5y deep)
      * ``"auto"`` (default) — HF for 1d-stocks, else yfinance

    Returns a status dict the router can render directly.
    """
    sym = symbol.upper()
    used_source = source

    try:
        if source == "alpaca":
            df = await _fetch_symbol_alpaca(sym, start=start, end=end, interval=interval)
            used_source = "alpaca"
        elif source == "ibkr":
            df = await _fetch_symbol_ibkr(sym, start=start, end=end, interval=interval)
            used_source = "ibkr"
        elif source == "yfinance":
            df = await _fetch_symbol_yf(sym, start=start, end=end, interval=interval)
            used_source = "yfinance"
        elif source == "hf":
            if interval != "1d":
                raise ValueError(
                    "HF source only supports 1d bars; pick yfinance or alpaca for "
                    f"{interval}"
                )
            df = await fetch_symbol_hf(sym, start=start, end=end)
            used_source = "hf"
        else:  # auto
            if interval != "1d":
                # auto for intraday → yfinance (Alpaca requires explicit pick)
                df = await _fetch_symbol_yf(sym, start=start, end=end, interval=interval)
                used_source = "yfinance (auto)"
            else:
                try:
                    df = await fetch_symbol_hf(sym, start=start, end=end)
                    used_source = "hf"
                except ValueError as hf_miss:
                    log.info("HF miss for %s; falling back to yfinance: %s", sym, hf_miss)
                    df = await _fetch_symbol_yf(sym, start=start, end=end, interval=interval)
                    used_source = "yfinance (auto-fallback)"
    except Exception as exc:                                           # noqa: BLE001
        return {
            "symbol": sym,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "rows": 0,
            "source": used_source,
            "interval": interval,
        }

    # Persist. yfinance path already wrote the CSV via data_service.refresh_bars,
    # but with the *full* yfinance window — re-save the date-sliced frame so the
    # on-disk file matches what the user asked for.
    if (used_source.startswith("yfinance") or used_source in ("alpaca", "ibkr")
            or used_source.startswith("hf")):
        path = await asyncio.to_thread(_save_sync_interval, sym, df, interval)
    else:
        path = HISTORICAL_DIR / f"{sym}_{interval}.csv"

    return {
        "symbol": sym,
        "ok": True,
        "rows": int(len(df)),
        "first": df.index[0].strftime("%Y-%m-%d %H:%M") if len(df) else None,
        "last": df.index[-1].strftime("%Y-%m-%d %H:%M") if len(df) else None,
        "path": str(path.relative_to(DATA_DIR.parent)).replace("\\", "/"),
        "size_kb": round(path.stat().st_size / 1024, 1) if path.exists() else 0,
        "source": used_source,
        "interval": interval,
    }


async def fetch_many_and_save(
    symbols: list[str],
    source: str = "auto",
    start: str | None = "2010-01-01",
    end: str | None = None,
    interval: str = "1d",
) -> list[dict]:
    """Run `fetch_and_save` for many symbols sequentially."""
    out: list[dict] = []
    for s in symbols:
        out.append(await fetch_and_save(
            s, source=source, start=start, end=end, interval=interval
        ))
    return out


def list_cached() -> list[dict]:
    """List every CSV currently in ``data/historical/`` with row counts."""
    if not HISTORICAL_DIR.exists():
        return []
    rows: list[dict] = []
    for path in sorted(HISTORICAL_DIR.glob("*.csv")):
        stem = path.stem  # e.g. "SPY_1d"
        if "_" in stem:
            sym, interval = stem.rsplit("_", 1)
        else:
            sym, interval = stem, ""
        try:
            row_count = sum(1 for _ in path.open("r")) - 1
        except Exception:
            row_count = -1
        st = path.stat()
        rows.append({
            "filename": path.name,
            "symbol": sym,
            "interval": interval,
            "rows": row_count,
            "size_kb": round(st.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(
                st.st_mtime, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC"),
        })
    return rows


def delete_cached(filename: str) -> bool:
    """Delete a single cached CSV. Filename must match a real entry exactly."""
    safe = Path(filename).name
    target = HISTORICAL_DIR / safe
    if not target.exists() or target.parent != HISTORICAL_DIR:
        return False
    target.unlink()
    return True
