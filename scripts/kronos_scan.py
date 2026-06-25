"""kronos_scan — the daily morning scan (DRY RUN: prints candidates, places nothing).

Loads the core_universe_100 tickers, forecasts each with Kronos, applies the
directional gate, builds a certainty-scaled plan, and prints the day's ranked
candidates. No broker, no pipeline — this is the "see the plans before trusting
them" step. Wiring to compliance/risk/pending + Alpaca paper is the next step.

USAGE:
    # quick test first (CPU is slow): 5 names, 30 paths
    python scripts/kronos_scan.py --limit 5 --paths 30

    # full universe (slow on CPU — consider running before market / overnight)
    python scripts/kronos_scan.py

    # ad-hoc symbol list
    python scripts/kronos_scan.py --symbols AAPL MSFT NVDA --paths 30
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("kronos_scan")


def load_universe(preset: str = "core_universe_100") -> list[str]:
    """Read the saved ticker list for a screener from the SQLite DB."""
    from services.settings_service import LOCAL_DB_PATH

    con = sqlite3.connect(str(LOCAL_DB_PATH))
    try:
        row = con.execute(
            "SELECT tickers_json FROM universe_presets WHERE name = ?", (preset,)
        ).fetchone()
    finally:
        con.close()
    if not row or not row[0]:
        raise ValueError(f"no saved tickers for screener '{preset}'")
    tickers = json.loads(row[0])
    return [t.upper() for t in tickers if t]


def main() -> None:
    ap = argparse.ArgumentParser(description="Kronos daily scan (dry run)")
    ap.add_argument("--preset", default="core_universe_100")
    ap.add_argument("--symbols", nargs="+", help="override the universe with an explicit list")
    ap.add_argument("--limit", type=int, default=0, help="cap number of symbols (0 = all)")
    ap.add_argument("--pred-len", type=int, default=10)
    ap.add_argument("--paths", type=int, default=30)
    ap.add_argument("--min-prob", type=float, default=0.60, help="gate on measured P(profit)")
    ap.add_argument("--min-er", type=float, default=0.0, help="gate on expected R")
    ap.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "cuda:0", "mps"],
                    help="where to run Kronos: auto-detect, local CPU, or a GPU")
    ap.add_argument("--gpu-rate", type=float, default=0.0,
                    help="cloud GPU $/hour; if >0, prints estimated run cost")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from scripts.kronos_poc import fetch_daily_bars
    from services import kronos_planner, kronos_service

    device = None if args.device == "auto" else args.device
    symbols = args.symbols or load_universe(args.preset)
    if args.limit:
        symbols = symbols[: args.limit]
    logger.info("Scanning %d symbols on %s (paths=%d, horizon=%d, gate: P>=%.0f%% & R>=%.2f)\n",
                len(symbols), args.device, args.paths, args.pred_len, args.min_prob * 100, args.min_er)

    plans = []
    t_start = time.time()
    for i, sym in enumerate(symbols, 1):
        try:
            bars = fetch_daily_bars(sym)
            dist = kronos_service.forecast(
                symbol=sym, interval="1d", bars=bars,
                pred_len=args.pred_len, n_paths=args.paths, device=device,
            )
            plan = kronos_planner.build_plan(symbol=sym, dist=dist, bars=bars)
            passed = plan is not None and plan.p_profit >= args.min_prob and plan.expected_r >= args.min_er
            logger.info("[%d/%d] %-6s %s", i, len(symbols), sym, "PASS" if passed else "skip")
            if passed:
                plans.append(plan)
        except Exception as exc:  # noqa: BLE001
            logger.error("[%d/%d] %-6s ERROR %s", i, len(symbols), sym, exc)

    plans.sort(key=lambda p: p.p_profit, reverse=True)

    logger.info("\n=== Candidates (gate %.0f%%, sorted by P(profit)) ===", args.min_prob * 100)
    logger.info("%-6s %-5s %9s %9s %9s %5s %8s %9s %7s",
                "sym", "dir", "entry", "stop", "TP", "RR", "convict", "P(profit)", "exp_R")
    logger.info("-" * 74)
    for p in plans:
        logger.info("%-6s %-5s %9.2f %9.2f %9.2f %5.1f %7.0f%% %8.0f%% %7.2f",
                    p.symbol, p.direction, p.entry, p.stop, p.take_profit, p.rr,
                    p.dir_conviction * 100, p.p_profit * 100, p.expected_r)

    elapsed = time.time() - t_start
    longs = sum(1 for p in plans if p.direction == "long")
    shorts = len(plans) - longs
    logger.info("-" * 74)
    logger.info("%d/%d passed (P>=%.0f%% & R>=%.2f) · %d long / %d short · %.0fs total · %.1fs/symbol",
                len(plans), len(symbols), args.min_prob * 100, args.min_er,
                longs, shorts, elapsed, elapsed / max(len(symbols), 1))

    # Cost visibility: local CPU is free; a cloud GPU bills by the hour.
    if args.gpu_rate > 0:
        cost = elapsed / 3600.0 * args.gpu_rate
        logger.info("Est. cloud cost this run @ $%.2f/hr: $%.2f (local CPU = $0, just slower)",
                    args.gpu_rate, cost)

    logger.info("\nDRY RUN — nothing was sent to a broker. Eyeball these, then we wire")
    logger.info("them into /pending for human approval on Alpaca paper.")
    logger.info("Reminder: P(profit) is RAW Kronos output, not yet calibrated.")


if __name__ == "__main__":
    main()
