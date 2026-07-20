"""build_candidate_review.py — make the backtested day-trade candidates reviewable
in the app's Backtest Review UI (/backtest-review).

For each candidate strategy it: runs the detector over cached bars, simulates trades,
writes a ledger JSON in the render format, then calls render_backtest_images to draw
~N winners + N losers spread across the years (entry/stop/target lines, EXIT marker) so
you can eyeball whether the mechanical setup matches the video's intent.

Artifacts land under data/ (gitignored) -> run this on the machine that serves the app,
then open /backtest-review. Needs matplotlib (`pip install matplotlib`).

    python scripts/build_candidate_review.py                 # all 6, ~5 trades/side
    python scripts/build_candidate_review.py --per-side 5 --since 2018-01-01
    python scripts/build_candidate_review.py --only false_break_fade
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from agents.detectors.external._base import simulate_trades
from scripts.backtest_prospects import (
    load_bars, PIP, three_line_strike, ema_reclaim_pullback,
    amd_session_reversal, orb_retest,
)
from scripts.backtest_fade_candidates import false_break_fade, opening_range_fade
from services.settings_service import DATA_DIR

LEDGER_DIR = DATA_DIR / "research" / "strategy_results"
ET = "America/New_York"

# (detector, symbols, kwargs) — all run on cached 5m bars.
FX3 = ["EURUSD", "GBPUSD", "AUDUSD"]
FX4 = ["EURUSD", "GBPUSD", "AUDUSD", "XAUUSD"]
STRATS = {
    "three_line_strike":     (three_line_strike,     FX3, {}),
    "ema_reclaim_pullback":  (ema_reclaim_pullback,  FX3, {}),
    "amd_session_reversal":  (amd_session_reversal,  FX3, {}),
    "orb_retest":            (orb_retest,            FX3, {}),
    "false_break_fade":      (false_break_fade,      FX4, {"open_hour": 13}),
    "opening_range_fade":    (opening_range_fade,    FX4, {"open_hour": 13}),
}


def build_ledger(name: str, since: str) -> Path:
    fn, syms, kw = STRATS[name]
    rows = []
    for sym in syms:
        try:
            bars = load_bars(sym, "5m", since)
        except FileNotFoundError:
            print(f"  {name}: no 5m csv for {sym}, skipping", file=sys.stderr)
            continue
        pip = PIP.get(sym, 0.0001)
        sigs = fn(bars, pip, **kw)
        trades = simulate_trades(bars, sigs)
        for t in trades:
            en = t.entry_ts.tz_convert(ET); ex = t.exit_ts.tz_convert(ET)
            rows.append({
                "symbol": sym,
                "date": en.date().isoformat(),
                "direction": t.direction,
                "entry": round(t.entry_price, 5),
                "stop": round(t.stop_price, 5),
                "target": (round(t.take_profit_price, 5)
                           if t.take_profit_price is not None else None),
                "exit": round(t.exit_price, 5),
                "entry_time": en.strftime("%H:%M"),
                "exit_time": ex.strftime("%H:%M"),
                "r_gross": round(t.pnl_r, 2),
                "r_net": round(t.pnl_r, 2),
                "exit_reason": t.exit_reason,
                "outcome": "win" if t.pnl_pct > 0 else "loss",
            })
    rows.sort(key=lambda r: (r["date"], r["entry_time"]))
    out = LEDGER_DIR / f"{name}_review_ledger.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows), encoding="utf-8")
    w = sum(1 for r in rows if r["outcome"] == "win")
    print(f"  {name}: {len(rows)} trades ({w} win / {len(rows)-w} loss) -> {out.name}")
    return out


def render(name: str, ledger: Path, per_side: int) -> None:
    cmd = [sys.executable, "-m", "scripts.render_backtest_images",
           "--strategy", name, "--ledger", str(ledger),
           "--interval", "5m", "--max-per-side", str(per_side),
           "--source-note", "video-mined day-trade candidate (review)"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    tail = (r.stdout or r.stderr).strip().splitlines()[-1:] or [""]
    print(f"    render {name}: {tail[0]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-side", type=int, default=5, help="winners + losers per strategy")
    ap.add_argument("--since", default="2018-01-01")
    ap.add_argument("--only", default="", help="one strategy name")
    a = ap.parse_args()
    names = [a.only] if a.only else list(STRATS)
    for name in names:
        if name not in STRATS:
            sys.exit(f"unknown strategy {name!r}; choices: {list(STRATS)}")
        ledger = build_ledger(name, a.since)
        render(name, ledger, a.per_side)
    print("\nDone. Open /backtest-review to review the galleries.")


if __name__ == "__main__":
    main()
