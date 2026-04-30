#!/usr/bin/env python
"""replay_dl.py — replay the production Double Lock detector across a date range.

Goal
----
Answer "if the DL strategy were running every day this week and I'd
approved every signal, what trades would have happened and what would
the P&L be?"

How it works
------------
For each trading day in [--since, --until]:
  1. Set ``as_of_ts`` to that day's 10:30 ET (the live workflow's fire time).
  2. Compute the macro context (SPY trend + VIX) at that timestamp.
  3. Call ``run_intraday_on_shortlist`` — the SAME function the live
     workflow's ``analyze`` step calls. This exercises the full
     detector path: regime filter, c1/c2 conviction check, PQS scoring.
  4. For each fire, simulate the exit:
       * Fetch that day's 30m bars after 10:30 ET via ``data_service``.
       * Walk forward bar by bar.
       * If a bar's high/low touches the catastrophic stop, exit there.
       * Otherwise exit at the 15:00 ET bar's close (live ``close_at_time``).
  5. Accumulate per-trade rows + aggregate stats.

Usage
-----
  .venv\\Scripts\\python.exe -m scripts.replay_dl --since 2026-04-21 --until 2026-04-29
  .venv\\Scripts\\python.exe -m scripts.replay_dl --week
  .venv\\Scripts\\python.exe -m scripts.replay_dl --since 2026-04-22 --symbols AAPL,NVDA,SPY

Defaults
--------
* date range: this Monday → today (or last completed weekday)
* symbols: ``DEFAULT_UNIVERSE`` (mirror of smoke_intraday_pipeline)
* strategy: ``double_lock`` (loads ``strategy_configs/double_lock.yaml`` —
  catastrophic stop pct comes from the YAML's ``thresholds.cat_stop_pct``)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import warnings
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

# Make project imports work
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.detectors.double_lock_filtered import detect_double_lock_filtered  # noqa: E402
from services import data_service                                              # noqa: E402
from services.indicator_service import add_indicators                          # noqa: E402
from services.settings_service import STRATEGY_CONFIG_DIR, get_settings        # noqa: E402

warnings.filterwarnings("ignore")
logging.getLogger("yfinance").setLevel(logging.ERROR)
logging.getLogger("agents.analyst").setLevel(logging.WARNING)
logging.getLogger("services.data_service").setLevel(logging.WARNING)

# Liquid mega-caps + ETFs that historically produce DL fires. Mirrors
# scripts/smoke_intraday_pipeline.py so live + replay scan the same set.
DEFAULT_UNIVERSE = [
    "AMD", "AMZN", "BA", "COST", "GS", "HD", "INTC", "IWM", "META",
    "ORCL", "SPY", "TSLA", "XLF", "AAPL", "MSFT", "NVDA",
]


@dataclass
class ReplayTrade:
    date_str: str           # YYYY-MM-DD
    symbol: str
    direction: str          # LONG / SHORT
    entry: float
    stop: float
    exit_px: float
    exit_reason: str        # STOP / EOD
    pnl_pct: float          # signed P&L %
    pnl_dollars_per_100shr: float
    win: bool
    pqs: int
    notes: str = ""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _last_completed_weekday(today: date | None = None) -> date:
    today = today or date.today()
    d = today
    while d.weekday() >= 5:        # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d


def _trading_days(since: date, until: date) -> list[date]:
    out = []
    d = since
    while d <= until:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _as_of_for(d: date) -> pd.Timestamp:
    """10:30 America/New_York for the given calendar date, in UTC."""
    et = pd.Timestamp(year=d.year, month=d.month, day=d.day,
                      hour=10, minute=30, tz="America/New_York")
    return et.tz_convert("UTC")


def _load_cat_stop_pct(strategy_name: str) -> float:
    path = STRATEGY_CONFIG_DIR / f"{strategy_name}.yaml"
    if not path.exists():
        return 3.0
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return float((cfg.get("thresholds") or {}).get("cat_stop_pct", 3.0))


# --------------------------------------------------------------------------- #
# Exit simulation
# --------------------------------------------------------------------------- #


async def _simulate_exit(
    symbol: str, d: date, entry: float, stop: float, direction: str,
) -> tuple[float, str] | None:
    """Walk the post-10:30 30m bars to find the exit. Returns (exit_px, reason)
    or None if data is missing for that day."""
    try:
        bars = await data_service.get_bars(symbol, "30m")
    except Exception:                                                 # noqa: BLE001
        return None
    if bars is None or bars.empty:
        return None

    # 30m bars from data_service are tz-aware UTC; convert to ET for slicing.
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    et = bars.tz_convert("America/New_York")
    day_bars = et[et.index.date == d]
    # Bars STARTING at 10:30 ET or later, up through the close.
    post = day_bars.between_time("10:30", "16:00")
    # Drop the 10:30 candle itself — that's c2 (entry); we exit AFTER it.
    post = post[post.index.time > pd.Timestamp("10:30").time()]
    if post.empty:
        return None

    for _, bar in post.iterrows():
        hi = float(bar["high"]); lo = float(bar["low"])
        if direction == "long" and lo <= stop:
            return stop, "STOP"
        if direction == "short" and hi >= stop:
            return stop, "STOP"

    # No stop hit — exit at the 15:00 ET bar's close (live ``close_at_time``).
    # Use the bar whose start time is 15:00 if present, otherwise the
    # last bar before 16:00.
    fifteen = post[post.index.time == pd.Timestamp("15:00").time()]
    if not fifteen.empty:
        return float(fifteen.iloc[0]["close"]), "EOD"
    return float(post.iloc[-1]["close"]), "EOD"


# --------------------------------------------------------------------------- #
# Core replay
# --------------------------------------------------------------------------- #


async def _full_frames(symbol: str, force_refresh: bool = False) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Fetch full 30m + daily frames (no as_of slicing) so the detector's
    slot-volume baseline sees the full 60-day series, matching the smoke
    test's invocation pattern. The detector handles the as_of cutoff itself.

    The detector requires 30m bars indexed in America/New_York (it compares
    timestamps to wall-clock 9:30/10:00 ET). data_service hands back
    UTC-indexed frames, so we convert here.
    """
    try:
        if force_refresh:
            await data_service.refresh_bars(symbol, "30m")
            await data_service.refresh_bars(symbol, "1d")
        bars30 = await data_service.get_bars(symbol, "30m", min_bars=2)
        daily  = await data_service.get_bars(symbol, "1d",  min_bars=50)
    except Exception:                                                  # noqa: BLE001
        return None, None
    if bars30 is not None and not bars30.empty:
        if bars30.index.tz is None:
            bars30.index = bars30.index.tz_localize("UTC")
        bars30 = bars30.tz_convert("America/New_York")
    return bars30, daily


async def _vix_prev_close_map(force_refresh: bool = False) -> dict[date, float]:
    """Build a {trading_date -> prior session's VIX close} lookup.

    The cached daily ^VIX file may lag the latest trading day; pass
    ``force_refresh=True`` (or run with --refresh) to re-pull from yfinance.
    """
    try:
        if force_refresh:
            await data_service.refresh_bars("^VIX", "1d")
        vix = await data_service.get_bars("^VIX", "1d", min_bars=10)
    except Exception:                                                  # noqa: BLE001
        return {}
    if vix is None or vix.empty:
        return {}
    closes = [(ts.date(), float(row["close"])) for ts, row in vix.iterrows()]
    closes.sort(key=lambda kv: kv[0])
    out: dict[date, float] = {}
    for i, (d, _c) in enumerate(closes):
        if i == 0:
            continue
        out[d] = closes[i - 1][1]   # prior session's close
    return out


async def replay(
    symbols: list[str], since: date, until: date, strategy: str = "double_lock",
    refresh: bool = False,
) -> list[ReplayTrade]:
    _ = get_settings()  # ensure settings load (also primes data dirs)
    cat_stop_pct = _load_cat_stop_pct(strategy)
    days = _trading_days(since, until)
    cfg_path = STRATEGY_CONFIG_DIR / f"{strategy}.yaml"
    config = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    trades: list[ReplayTrade] = []
    print(f"\nReplay {strategy} | {since} -> {until}  ({len(days)} trading days, {len(symbols)} symbols)")
    print(f"Catastrophic stop pct: {cat_stop_pct:.2f}%   Exit time: 15:00 ET (or stop hit, whichever first)\n")

    # Pre-fetch all data: full frames + VIX prev-close map
    print(f"Fetching 30m + daily for {len(symbols)} symbols + ^VIX{' (force refresh)' if refresh else ''}...")
    sym_data: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for sym in symbols:
        b, d = await _full_frames(sym, force_refresh=refresh)
        if b is None or d is None or b.empty or d.empty:
            print(f"  ! {sym}: data unavailable, skipping")
            continue
        sym_data[sym] = (b, add_indicators(d))
    vix_by_date = await _vix_prev_close_map(force_refresh=refresh)
    print(f"  ready: {len(sym_data)} symbols + {len(vix_by_date)} VIX rows\n")

    for d in days:
        as_of = _as_of_for(d)
        vix_prev = vix_by_date.get(d)
        if vix_prev is None:
            print(f"  {d}  no prior-session VIX close (likely no trading data) -> skip")
            continue

        day_fires = 0
        for sym, (bars30, daily_ind) in sym_data.items():
            try:
                pat = detect_double_lock_filtered(
                    bars_30m=bars30, daily=daily_ind, vix_prev_close=vix_prev,
                    config=config, as_of_ts=as_of,
                )
            except Exception as e:                                    # noqa: BLE001
                print(f"  ! {d} {sym}: detector raised: {e}")
                continue
            if pat is None:
                continue

            entry = float(pat.entry_price)
            stop  = float(pat.stop_price)
            exit_pair = await _simulate_exit(sym, d, entry, stop, pat.direction)
            if exit_pair is None:
                print(f"  {d}  {sym} {pat.direction.upper():5s} entry={entry:.2f}  -- no exit data")
                continue
            exit_px, reason = exit_pair
            raw_pct = (exit_px - entry) / entry * 100.0
            pnl_pct = raw_pct if pat.direction == "long" else -raw_pct
            pnl_per_100 = (exit_px - entry) * 100.0 * (1 if pat.direction == "long" else -1)

            trades.append(ReplayTrade(
                date_str=str(d),
                symbol=sym,
                direction=pat.direction.upper(),
                entry=round(entry, 2),
                stop=round(stop, 2),
                exit_px=round(exit_px, 2),
                exit_reason=reason,
                pnl_pct=round(pnl_pct, 2),
                pnl_dollars_per_100shr=round(pnl_per_100, 2),
                win=pnl_pct > 0,
                pqs=int(pat.pqs_total or 0),
                notes=pat.pattern_name or "",
            ))
            day_fires += 1

        print(f"  {d}  VIX_prev={vix_prev:.2f}  -> {day_fires} signals")

    return trades


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def _print_table(trades: list[ReplayTrade]) -> None:
    if not trades:
        print("\n(no trades fired in this date range)")
        return
    print(f"\nTrades ({len(trades)}):\n")
    hdr = (
        f"| {'Date':10s} | {'Sym':5s} | {'Dir':5s} | "
        f"{'Entry':>8s} | {'Stop':>8s} | {'Exit':>8s} | {'Why':4s} | "
        f"{'P&L %':>7s} | {'$/100sh':>8s} | {'PQS':>3s} | W |"
    )
    print(hdr)
    print("|" + "|".join(["-" * (len(c)) for c in hdr.split("|")[1:-1]]) + "|")
    for t in sorted(trades, key=lambda x: (x.date_str, x.symbol)):
        print(
            f"| {t.date_str:10s} | {t.symbol:5s} | {t.direction:5s} | "
            f"{t.entry:>8.2f} | {t.stop:>8.2f} | {t.exit_px:>8.2f} | {t.exit_reason:4s} | "
            f"{t.pnl_pct:>+7.2f} | {t.pnl_dollars_per_100shr:>+8.2f} | {t.pqs:>3d} | {'Y' if t.win else 'N'} |"
        )


def _print_summary(trades: list[ReplayTrade]) -> None:
    if not trades:
        return
    n = len(trades)
    wins = sum(1 for t in trades if t.win)
    losses = n - wins
    win_rate = wins / n * 100.0
    avg_pnl = sum(t.pnl_pct for t in trades) / n
    total_pnl = sum(t.pnl_pct for t in trades)
    best = max(trades, key=lambda t: t.pnl_pct)
    worst = min(trades, key=lambda t: t.pnl_pct)
    stop_hits = sum(1 for t in trades if t.exit_reason == "STOP")

    longs = [t for t in trades if t.direction == "LONG"]
    shorts = [t for t in trades if t.direction == "SHORT"]
    long_wr = (sum(1 for t in longs if t.win) / len(longs) * 100.0) if longs else 0.0
    short_wr = (sum(1 for t in shorts if t.win) / len(shorts) * 100.0) if shorts else 0.0

    print()
    print("-" * 60)
    print(f"  Trades:        {n}   (wins {wins} | losses {losses})")
    print(f"  Win rate:      {win_rate:.1f}%")
    print(f"  Avg P&L/trade: {avg_pnl:+.2f}%")
    print(f"  Total P&L:     {total_pnl:+.2f}%   (sum of trade %)")
    print(f"  Stop hits:     {stop_hits}/{n}   ({stop_hits/n*100:.0f}%)")
    print(f"  Longs:  {len(longs):2d}   WR {long_wr:.0f}%")
    print(f"  Shorts: {len(shorts):2d}   WR {short_wr:.0f}%")
    print(f"  Best:   {best.symbol} {best.date_str} {best.pnl_pct:+.2f}%")
    print(f"  Worst:  {worst.symbol} {worst.date_str} {worst.pnl_pct:+.2f}%")
    print("-" * 60)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def _argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Replay the DL strategy across a date range.")
    p.add_argument("--since", type=_parse_date, default=None,
                   help="start date YYYY-MM-DD (default: this week's Monday)")
    p.add_argument("--until", type=_parse_date, default=None,
                   help="end date YYYY-MM-DD (default: last completed weekday)")
    p.add_argument("--week", action="store_true",
                   help="alias for the current week (Mon → today)")
    p.add_argument("--symbols", type=str, default=None,
                   help=f"comma-separated tickers (default: {len(DEFAULT_UNIVERSE)} liquid mega-caps + ETFs)")
    p.add_argument("--strategy", default="double_lock",
                   help="strategy YAML to use (default: double_lock)")
    p.add_argument("--refresh", action="store_true",
                   help="force refresh of cached bars (use when cache is stale)")
    return p


async def _amain(args: argparse.Namespace) -> int:
    today = date.today()
    if args.week or (args.since is None and args.until is None):
        # This Monday through today (clamped to last weekday)
        monday = today - timedelta(days=today.weekday())
        args.since = args.since or monday
        args.until = args.until or _last_completed_weekday(today)
    else:
        args.until = args.until or _last_completed_weekday(today)
        args.since = args.since or args.until

    if args.until < args.since:
        print(f"error: --until ({args.until}) is before --since ({args.since})")
        return 2

    syms = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else DEFAULT_UNIVERSE

    trades = await replay(syms, args.since, args.until, args.strategy, refresh=args.refresh)
    _print_table(trades)
    _print_summary(trades)
    return 0


def main() -> int:
    return asyncio.run(_amain(_argparser().parse_args()))


if __name__ == "__main__":
    sys.exit(main())
