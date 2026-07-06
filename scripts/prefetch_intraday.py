"""Warm the intraday bar cache (5m / 15m / 30m) for the chart viewer.

The chart on /pending and /trades/{id} now offers sub-hourly timeframes
(5m, 10m, 15m, 30m). Those intervals download from yfinance on first
request, so the very first time you open a 5m chart there's a short
delay (and a transient 404 if the fetch is slow). This script pre-fetches
them so the cache is warm before you look.

yfinance caps sub-hourly history at ~60 days, so these CSVs turn over
quickly — run this pre-market (or whenever you're about to review the
queue), the same cadence you'd refresh 30m for the DL detector.

Usage
-----
    # Warm every symbol currently in the pending queue (default):
    python -m scripts.prefetch_intraday

    # Warm every symbol in a named screener's saved universe:
    python -m scripts.prefetch_intraday --screener core_universe_100

    # Warm the active screener's universe:
    python -m scripts.prefetch_intraday --active

    # Warm specific symbols:
    python -m scripts.prefetch_intraday XOM NVDA AAPL

    # Choose intervals (default: 5m,15m,30m — 10m is resampled from 5m):
    python -m scripts.prefetch_intraday --intervals 5m,15m

Notes
-----
- Uses the app's own ``services.data_service`` so the CSV format matches
  exactly what ``routers/bars.py`` reads back. No parallel download path.
- 10m is NOT fetched: the bars router resamples it from the 5m cache, so
  warming 5m is enough.
- Never raises on a bad ticker / empty Yahoo response — it logs and moves on.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from services.data_service import Interval, refresh_bars

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("prefetch_intraday")

# 10m is intentionally excluded — the bars router resamples it from 5m.
_DEFAULT_INTERVALS: tuple[Interval, ...] = ("5m", "15m", "30m")
_VALID: frozenset[str] = frozenset({"5m", "15m", "30m"})


async def _pending_symbols() -> list[str]:
    """Distinct symbols from the current pending queue (best-effort)."""
    try:
        from services.db_service import get_pending_plans
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("cannot import db_service (%s); pass symbols explicitly", exc)
        return []
    try:
        plans = await get_pending_plans(status_filter="pending", limit=500)
    except Exception as exc:
        log.warning("could not read pending queue (%s); pass symbols explicitly", exc)
        return []
    seen: dict[str, None] = {}
    for p in plans:
        sym = (p.get("symbol") or "").upper().strip()
        if sym:
            seen.setdefault(sym, None)
    return list(seen)


async def _screener_symbols(name: str | None) -> list[str]:
    """Distinct tickers from a named screener's saved universe (or the
    active screener when ``name`` is None)."""
    from services import universe_service

    preset: dict | None = None
    if name:
        preset = await universe_service.get_preset_db(name)
        if preset is None:
            log.error("screener %r not found", name)
            return []
    else:
        for p in await universe_service.list_presets_db():
            if p.get("is_active"):
                preset = await universe_service.get_preset_db(p["name"])
                log.info("using active screener %r", p["name"])
                break
        if preset is None:
            log.error("no active screener set; pass --screener NAME")
            return []

    seen: dict[str, None] = {}
    for sym in preset.get("tickers", []) or []:
        s = str(sym).upper().strip()
        if s:
            seen.setdefault(s, None)
    return list(seen)


async def _warm(symbols: list[str], intervals: tuple[str, ...]) -> None:
    ok = 0
    fail = 0
    for sym in symbols:
        for iv in intervals:
            try:
                df = await refresh_bars(sym, iv)  # type: ignore[arg-type]
                log.info("  %-6s %-4s  %d bars", sym, iv, len(df))
                ok += 1
            except Exception as exc:
                log.warning("  %-6s %-4s  FAILED: %s", sym, iv, exc)
                fail += 1
    log.info("done — %d warmed, %d failed", ok, fail)


def main() -> None:
    ap = argparse.ArgumentParser(description="Warm intraday bar cache (5m/15m/30m).")
    ap.add_argument("symbols", nargs="*", help="Symbols to warm (default: pending queue)")
    ap.add_argument("--screener", help="Warm every ticker in this screener's saved universe")
    ap.add_argument("--active", action="store_true",
                    help="Warm the active screener's universe")
    ap.add_argument(
        "--intervals",
        default=",".join(_DEFAULT_INTERVALS),
        help="Comma-separated intervals from {5m,15m,30m} (default: 5m,15m,30m)",
    )
    args = ap.parse_args()

    intervals = tuple(iv.strip() for iv in args.intervals.split(",") if iv.strip())
    bad = [iv for iv in intervals if iv not in _VALID]
    if bad:
        ap.error(f"unsupported interval(s) {bad}; choose from {sorted(_VALID)}")

    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
    elif args.screener or args.active:
        symbols = asyncio.run(_screener_symbols(args.screener))
        if not symbols:
            return
        log.info("warming %d symbol(s) from the screener universe", len(symbols))
    else:
        symbols = asyncio.run(_pending_symbols())
        if not symbols:
            log.info("no symbols given and pending queue is empty — nothing to do.")
            return
        log.info("warming %d symbol(s) from the pending queue", len(symbols))

    asyncio.run(_warm(symbols, intervals))


if __name__ == "__main__":
    main()
