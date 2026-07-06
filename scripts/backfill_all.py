"""scripts/backfill_all.py — one-shot backfill of the whole trading universe.

Fills data/historical/{SYMBOL}_{interval}.csv for every symbol we trade,
routing each (symbol, interval) to the best free source automatically:

    equity  1d            -> HF parquet (local, free, deep history)
    equity  intraday      -> Alpaca historical bars (free, ~5y, no 60-day cap)
    FX / gold  any        -> IBKR (needs the IB Gateway running)

It is **resumable**: already-cached files are skipped unless --force, so you
can stop it (Ctrl-C) and re-run and it picks up where it left off. Failures
are logged and skipped, never fatal — a couple of bad tickers won't stop the
run.

Prerequisites
-------------
- Equity intraday needs Alpaca keys in .env (ALPACA_API_KEY / ALPACA_API_SECRET).
  Free accounts: if SIP is rejected, set ALPACA_DATA_FEED=iex in .env.
- FX needs the IB Gateway up on IBKR_PORT (default 4002). Skip FX with --no-fx
  if the gateway isn't running.

Usage
-----
    # Everything: active screener universe + FX, all intervals:
    python -m scripts.backfill_all --active

    # A specific screener, only daily + 30m:
    python -m scripts.backfill_all --screener core_universe_100 --intervals 1d,30m

    # Equities only (gateway not running):
    python -m scripts.backfill_all --active --no-fx

    # Re-fetch even cached files (force full rebuild):
    python -m scripts.backfill_all --active --force
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from services import hf_data_service, universe_service  # noqa: E402
from services.fvg_scan_service import DEFAULT_SYMBOLS as FX_SYMBOLS  # noqa: E402

HIST_DIR = ROOT / "data" / "historical"
DEFAULT_INTERVALS = ["1d", "1h", "30m", "15m", "5m"]
_FX_SET = {s.upper() for s in FX_SYMBOLS}


def _source_for(symbol: str, interval: str, equity_daily_source: str) -> str:
    """Best source for one (symbol, interval)."""
    if symbol.upper() in _FX_SET:
        return "ibkr"           # FX + gold only come cleanly from IBKR
    if interval == "1d":
        return equity_daily_source   # "hf" (auto-fallback yfinance) by default
    return "alpaca"             # equity intraday: Alpaca (free, deep)


async def _resolve_equities(screener: str | None, active: bool) -> list[str]:
    if active and not screener:
        for p in await universe_service.list_presets_db():
            if p.get("is_active"):
                screener = p["name"]
                print(f"active screener: {screener}")
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
    ap = argparse.ArgumentParser(description="Backfill the whole universe (equity + FX).")
    ap.add_argument("--screener", help="Equity screener name (default: active screener)")
    ap.add_argument("--active", action="store_true", help="Use the active screener")
    ap.add_argument("--intervals", default=",".join(DEFAULT_INTERVALS),
                    help=f"Comma list (default: {','.join(DEFAULT_INTERVALS)})")
    ap.add_argument("--start", default="2010-01-01", help="History start date")
    ap.add_argument("--equity-daily-source", default="hf",
                    choices=["hf", "yfinance", "alpaca", "auto"],
                    help="Source for equity 1d bars (default: hf)")
    ap.add_argument("--no-fx", dest="fx", action="store_false", default=True,
                    help="Skip FX/gold (e.g. IB Gateway not running)")
    ap.add_argument("--no-equities", dest="equities", action="store_false", default=True,
                    help="Skip equities (FX only)")
    ap.add_argument("--force", action="store_true", help="Re-fetch even cached files")
    ap.add_argument("--workers", type=int, default=6,
                    help="Concurrent equity fetches (Alpaca/HF/yfinance). "
                         "Alpaca free tier is ~200 req/min; 6-10 is safe. "
                         "FX/IBKR always runs sequentially. (default: 6)")
    ap.add_argument("--pace", type=float, default=0.4,
                    help="Seconds between sequential FX/IBKR fetches (default: 0.4)")
    args = ap.parse_args()

    intervals = [iv.strip() for iv in args.intervals.split(",") if iv.strip()]
    HIST_DIR.mkdir(parents=True, exist_ok=True)

    equities = await _resolve_equities(args.screener, args.active) if args.equities else []
    fx = list(FX_SYMBOLS) if args.fx else []
    all_syms = equities + fx
    if not all_syms:
        print("nothing to fetch (no equities resolved and FX disabled).")
        return 1

    # Build the (symbol, interval, source) work list, honoring skip-existing.
    work: list[tuple[str, str, str]] = []
    cached = 0
    for interval in intervals:
        for sym in all_syms:
            # FX has no meaningful daily/weekly bars in this app — skip 1d for FX.
            if sym.upper() in _FX_SET and interval in ("1d", "1h"):
                continue
            path = HIST_DIR / f"{sym.upper()}_{interval}.csv"
            if not args.force and path.exists():
                cached += 1
                continue
            work.append((sym, interval, _source_for(sym, interval, args.equity_daily_source)))

    # IBKR (FX) must stay sequential — one gateway connection + IBKR pacing.
    # Everything else (Alpaca/HF/yfinance) runs concurrently.
    ibkr_work = [w for w in work if w[2] == "ibkr"]
    par_work = [w for w in work if w[2] != "ibkr"]

    print(f"universe: {len(equities)} equities + {len(fx)} FX = {len(all_syms)} symbols")
    print(f"intervals: {intervals}")
    print(f"already cached (skipped): {cached}    to fetch: {len(work)}")
    print(f"concurrency: {args.workers} workers (equities)  |  FX sequential: {len(ibkr_work)}")
    print("-" * 78)

    total = len(work)
    counter = {"done": 0, "ok": 0, "fail": 0}
    by_source: dict[str, int] = {}
    t0 = time.time()

    def _record(sym: str, interval: str, source: str, res: dict, dur: float) -> None:
        counter["done"] += 1
        i = counter["done"]
        if res.get("ok"):
            counter["ok"] += 1
            by_source[source] = by_source.get(source, 0) + 1
            elapsed = time.time() - t0
            rate = elapsed / max(i, 1)
            eta = rate * (total - i)
            print(f"[{i:>4d}/{total}] {sym:<8s} {interval:<4s} {source:<8s} "
                  f"ok {res.get('rows', 0):>6d} rows ({dur:.1f}s)  "
                  f"ETA {eta/60:.0f}m")
        else:
            counter["fail"] += 1
            print(f"[{i:>4d}/{total}] {sym:<8s} {interval:<4s} {source:<8s} "
                  f"FAIL {str(res.get('error', '?'))[:50]} ({dur:.1f}s)")

    async def _one(sym: str, interval: str, source: str) -> None:
        ts = time.time()
        try:
            res = await hf_data_service.fetch_and_save(
                sym, source=source, start=args.start, interval=interval,
            )
        except Exception as exc:  # noqa: BLE001
            res = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "rows": 0}
        _record(sym, interval, source, res, time.time() - ts)

    # Concurrent equity lane — bounded by a semaphore.
    sem = asyncio.Semaphore(max(1, args.workers))

    async def _guarded(w: tuple[str, str, str]) -> None:
        async with sem:
            await _one(*w)

    if par_work:
        await asyncio.gather(*[_guarded(w) for w in par_work])

    # Sequential FX lane.
    for w in ibkr_work:
        await _one(*w)
        if args.pace:
            await asyncio.sleep(args.pace)

    elapsed = time.time() - t0
    print("-" * 78)
    print(f"DONE — {counter['ok']} ok, {counter['fail']} failed in {elapsed:.0f}s "
          f"({elapsed/60:.1f}m)   by source: {by_source}")
    return 0 if counter["fail"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
