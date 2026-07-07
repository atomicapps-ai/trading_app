"""scripts/refresh_candles.py — manual incremental top-up of the bar cache.

Same logic the scheduler's ``candle_refresh`` job runs, but on demand. Fetches
only the recent tail per (symbol, interval) and merges it into the existing
CSV (deep history preserved). Routes equity intraday → Alpaca, equity daily →
yfinance, FX → IBKR.

Usage
-----
    # Refresh the active screener universe at daily:
    python -m scripts.refresh_candles --active --intervals 1d

    # Refresh specific names at intraday:
    python -m scripts.refresh_candles AAPL NVDA --intervals 30m,15m,5m

    # Refresh a whole screener across several intervals:
    python -m scripts.refresh_candles --screener core_universe --intervals 1d,30m
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from services import candle_refresh_service as C  # noqa: E402
from services import universe_service  # noqa: E402


async def _universe(screener: str | None, active: bool) -> list[str]:
    if active and not screener:
        for p in await universe_service.list_presets_db():
            if p.get("is_active"):
                screener = p["name"]
                break
    if not screener:
        return []
    preset = await universe_service.get_preset_db(screener)
    if preset is None:
        print(f"screener {screener!r} not found")
        return []
    seen: dict[str, None] = {}
    for s in preset.get("tickers", []) or []:
        u = str(s).upper().strip()
        if u:
            seen.setdefault(u, None)
    return list(seen)


async def main() -> int:
    ap = argparse.ArgumentParser(description="Incrementally refresh cached bars.")
    ap.add_argument("symbols", nargs="*", help="Symbols (default: screener/active)")
    ap.add_argument("--screener", help="Refresh this screener's universe")
    ap.add_argument("--active", action="store_true", help="Refresh the active screener")
    ap.add_argument("--intervals", default="1d", help="Comma list (default: 1d)")
    ap.add_argument("--daily-source", default="yfinance",
                    choices=["yfinance", "hf", "alpaca"])
    args = ap.parse_args()

    intervals = [iv.strip() for iv in args.intervals.split(",") if iv.strip()]
    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
    else:
        symbols = await _universe(args.screener, args.active)
    if not symbols:
        print("no symbols to refresh.")
        return 1

    print(f"refreshing {len(symbols)} symbol(s) × {intervals} …")
    summary = await C.refresh_many(symbols, intervals, daily_source=args.daily_source)
    print(f"DONE — {summary}")
    return 0


def _install_sigint_handler() -> None:
    """Ctrl+C exits now — the fetch runs in a blocking worker thread that
    asyncio's graceful shutdown would otherwise wait on. Safe: resumable."""
    import os
    import signal

    def _die(*_a):
        print("\n^C — stopping.", flush=True)
        os._exit(130)

    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGBREAK", None)):
        if sig is not None:
            try:
                signal.signal(sig, _die)
            except (ValueError, OSError):
                pass


if __name__ == "__main__":
    _install_sigint_handler()
    raise SystemExit(asyncio.run(main()))
