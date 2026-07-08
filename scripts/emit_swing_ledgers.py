"""emit_swing_ledgers — run the real swing detectors (via replay_swing) and dump per-trade LEDGERS
that scripts/render_backtest_images.py turns into winner/loser PNGs.

For each live/candidate daily-swing strategy, runs replay() over a liquid symbol set + date window and
writes data/research/strategy_results/<strategy>_swing_ledger.json with the fields the renderer needs
(symbol, date=entry bar, direction, entry, stop, target, r_gross/r_net).

  python scripts/emit_swing_ledgers.py --since 2010-01-01 --until 2024-12-31
"""
from __future__ import annotations
import argparse, asyncio, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.replay_swing import replay, HIST  # noqa: E402

OUT = ROOT / "data" / "research" / "strategy_results"; OUT.mkdir(parents=True, exist_ok=True)
LIVE_SWING = ["momentum_breakout", "fear_dip_reversion", "macd_run", "coil_breakout"]
CANDIDATES = ["rsi_pullback", "band_extreme_fade", "hidden_divergence", "turn_of_month"]
LIQUID = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA", "GOOGL", "AMD", "AVGO", "NFLX",
          "JPM", "BAC", "XOM", "CVX", "WMT", "HD", "COST", "UNH", "SPY", "QQQ"]


def _to_ledger(trades):
    led = []
    for t in trades:
        entry, stop = t.entry, t.stop
        risk_frac = (entry - stop) / entry if entry and entry > stop else 0.02
        cost_r = 0.001 / max(risk_frac, 1e-4)          # ~10bps round-trip in R units
        led.append({
            "symbol": t.symbol, "date": t.entry_date or t.date_str, "direction": t.direction,
            "entry": round(entry, 2), "stop": round(stop, 2), "target": t.tp,
            "r_gross": round(t.pnl_r, 3), "r_net": round(t.pnl_r - cost_r, 3),
            "exit_date": t.exit_date, "exit_reason": t.exit_reason,
            "mfe_r": t.mfe_r, "mae_r": t.mae_r, "hold_days": t.hold_days,
        })
    return led


async def run(strategies, symbols, since, until):
    syms = [s for s in symbols if (HIST / f"{s}_1d.csv").exists()]
    print(f"symbols with daily data: {len(syms)}/{len(symbols)}")
    for strat in strategies:
        try:
            trades = await replay(syms, since, until, strategy=strat)
        except Exception as e:  # noqa: BLE001
            print(f"{strat}: FAILED ({e})"); continue
        led = _to_ledger(trades)
        (OUT / f"{strat}_swing_ledger.json").write_text(json.dumps(led, indent=2))
        wins = sum(1 for t in led if t["r_gross"] > 0)
        print(f"{strat}: {len(led)} trades ({wins} win / {len(led)-wins} loss) -> {strat}_swing_ledger.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategies", nargs="*", default=LIVE_SWING + CANDIDATES)
    ap.add_argument("--symbols", nargs="*", default=LIQUID)
    ap.add_argument("--since", default="2010-01-01")
    ap.add_argument("--until", default="2024-12-31")
    args = ap.parse_args()
    asyncio.run(run(args.strategies, args.symbols, args.since, args.until))


if __name__ == "__main__":
    main()
