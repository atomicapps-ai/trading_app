"""run_quant_sentiment_backtest.py — CLI driver for the Alpha Score backtest.

Usage:
    python -m scripts.run_quant_sentiment_backtest \
        --symbols AAPL,MSFT,NVDA,SPY,QQQ \
        --start 2024-01-01 --end 2025-01-01 \
        --threshold 80 \
        --out data/quant_sentiment_report.json

If --symbols is omitted the script defaults to the bellwether 16 list.
The report is written as JSON; the script also prints the headline
expectancy table to stdout.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running as `python scripts/run_quant_sentiment_backtest.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env so ALPACA_API_KEY / FRED_API_KEY are visible to news_service
# and economic_calendar_service. The FastAPI app loads these via lifespan;
# CLI scripts have to do it themselves.
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:                                   # noqa: BLE001
    pass

from services.quant_sentiment_backtest import (   # noqa: E402
    backtest_universe,
    build_report,
)

BELLWETHER_16 = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO",
    "JPM", "V", "UNH", "XOM", "WMT", "COST", "HD", "LLY",
]


def _parse_date(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _print_report(report) -> None:
    print()
    print("ALPHA SCORE BACKTEST REPORT")
    print("=" * 60)
    print(f"Universe size : {report.universe_size}")
    print(f"Trades total  : {report.trades_total}")
    print(f"Weights       : {report.weights_used}")
    print()
    print(f"{'bucket':<8} {'n':>5} {'win%':>7} {'avg_w%':>8} {'avg_l%':>8} "
          f"{'avg_R':>7} {'exp%':>8} {'tot%':>9}")
    for bucket in ("high", "medium", "low"):
        s = report.by_bucket.get(bucket, {})
        print(
            f"{bucket:<8} {s.get('n', 0):>5} "
            f"{s.get('win_rate', 0)*100:>6.1f}% "
            f"{s.get('avg_win_pct', 0):>7.2f}% "
            f"{s.get('avg_loss_pct', 0):>7.2f}% "
            f"{s.get('avg_r', 0):>7.2f} "
            f"{s.get('expectancy_pct', 0):>7.2f}% "
            f"{s.get('total_pnl_pct', 0):>8.2f}%"
        )
    print()
    if report.tag_correlations:
        print("TOP TAGS BY LIFT (correlation with success)")
        print(f"{'tag':<26} {'n':>5} {'win%':>7} {'lift':>7} {'pnl%':>8}")
        for row in report.tag_correlations[:15]:
            print(
                f"{row['tag']:<26} {row['n']:>5} "
                f"{row['win_rate']*100:>6.1f}% "
                f"{row['lift_vs_baseline']:>6.2f} "
                f"{row['avg_pnl_pct']:>7.2f}%"
            )
    print()
    for note in report.notes:
        print(f"NOTE: {note}")


async def _amain(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    symbols = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.symbols else list(BELLWETHER_16)
    )
    start = _parse_date(args.start)
    end = _parse_date(args.end)

    print(
        f"Backtesting {len(symbols)} symbols from {start.date()} to {end.date()} "
        f"(threshold={args.threshold}, target={args.target_atr}xATR, stop={args.stop_atr}xATR, "
        f"step={args.step}d, concurrency={args.concurrency})",
        flush=True,
    )

    def _progress(done, total, sym, n_trades, elapsed_sym, elapsed_total):
        eta = (elapsed_total / done) * (total - done) if done else 0
        print(
            f"  [{done:>2}/{total}] {sym:<6} {n_trades:>3} trades "
            f"({elapsed_sym:5.1f}s/sym · "
            f"{int(elapsed_total // 60):>2}m elapsed · "
            f"~{int(eta // 60):>2}m ETA)",
            flush=True,
        )

    trades, scores = await backtest_universe(
        symbols,
        start=start, end=end,
        entry_threshold=args.threshold,
        target_atr_mult=args.target_atr,
        stop_atr_mult=args.stop_atr,
        max_hold_bars=args.max_hold,
        decision_step_days=args.step,
        concurrency=args.concurrency,
        progress_cb=_progress,
    )
    print(f"Computed {len(scores)} alpha scores; produced {len(trades)} trades", flush=True)

    report = build_report(trades, universe_size=len(symbols))
    _print_report(report)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "report": report.model_dump(mode="json"),
            "trades": [t.model_dump(mode="json") for t in trades],
        }
        out_path.write_text(json.dumps(payload, indent=2, default=str))
        print(f"Wrote {len(trades)} trades + report → {out_path}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Quant + sentiment Alpha Score backtest.")
    p.add_argument("--symbols", help="Comma-separated tickers (default: bellwether 16)")
    p.add_argument("--start", required=True, help="ISO date inclusive")
    p.add_argument("--end", required=True, help="ISO date inclusive")
    p.add_argument("--threshold", type=float, default=80.0,
                   help="Min adjusted_composite to enter (default 80)")
    p.add_argument("--target-atr", type=float, default=2.0, dest="target_atr")
    p.add_argument("--stop-atr", type=float, default=1.0, dest="stop_atr")
    p.add_argument("--max-hold", type=int, default=10, dest="max_hold")
    p.add_argument("--step", type=int, default=1, help="Decision cadence in bars")
    p.add_argument("--concurrency", type=int, default=6)
    p.add_argument("--out", help="Output JSON path (optional)")
    args = p.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
