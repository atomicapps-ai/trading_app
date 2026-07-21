"""build_equity_review.py — render the equity-RTH re-tests into /backtest-review.

Writes a ledger in the render format for a detector from `scripts.bt_equity_open_setups`
and draws winners/losers so the setups can be verified visually. Unlike
`build_candidate_review.py` this one carries `entry_time` / `exit_time` (so the ENTRY box
and EXIT marker actually land on the chart), the opening-range box, and a genuinely net
`r_net` — the trade R already has the round-turn cost deducted.

    python -m scripts.build_equity_review --strategy orb_retest --per-side 8
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from scripts.bt_equity_open_setups import backtest, load_rth, summarize
from services.settings_service import DATA_DIR

LEDGER_DIR = DATA_DIR / "research" / "strategy_results"


def or_box(sym: str, date: str, since: str, or_bars: int = 3) -> tuple[float | None, float | None]:
    """The opening range the detector actually used, for the chart overlay."""
    try:
        bars = load_rth(sym, since)      # cached per (symbol, since)
    except FileNotFoundError:
        return None, None
    day = bars[[str(d) == date for d in bars.index.date]]
    if len(day) < or_bars:
        return None, None
    return float(day["high"][:or_bars].max()), float(day["low"][:or_bars].min())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="orb_retest")
    ap.add_argument("--symbols", default="SPY,QQQ")
    ap.add_argument("--since", default="2018-01-01")
    ap.add_argument("--cost-bps", type=float, default=2.0)
    ap.add_argument("--per-side", type=int, default=8)
    ap.add_argument("--name", default="", help="output name (defaults to <strategy>_eq)")
    a = ap.parse_args()

    syms = [s.strip().upper() for s in a.symbols.split(",")]
    name = a.name or f"{a.strategy}_eq"
    trades = backtest(syms, a.since, a.strategy, a.cost_bps)
    print(f"{name}: {summarize(trades)}")

    rows = []
    for t in trades:
        hi, lo = or_box(t.symbol, t.date, a.since)
        rows.append({
            "symbol": t.symbol, "date": t.date, "direction": t.direction,
            "entry": round(t.entry, 4), "stop": round(t.stop, 4),
            "target": round(t.target, 4), "exit": round(t.exit_price, 4),
            "entry_time": t.entry_ts.strftime("%H:%M"),
            "exit_time": t.exit_ts.strftime("%H:%M"),
            "box_high": hi, "box_low": lo,
            "r_gross": round(t.r + a.cost_bps / 10_000 * t.entry / abs(t.entry - t.stop), 2),
            "r_net": round(t.r, 2),
            "exit_reason": t.reason,
            "outcome": "win" if t.r > 0 else "loss",
        })
    rows.sort(key=lambda r: (r["date"], r["entry_time"]))
    out = LEDGER_DIR / f"{name}_ledger.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows), encoding="utf-8")
    w = sum(1 for r in rows if r["outcome"] == "win")
    print(f"  {len(rows)} trades ({w} win / {len(rows)-w} loss) -> {out.name}")

    cmd = [sys.executable, "-m", "scripts.render_backtest_images",
           "--strategy", name, "--ledger", str(out), "--interval", "5m",
           "--max-per-side", str(a.per_side),
           "--source-note", f"{a.strategy} re-tested on equity RTH 5m, {a.cost_bps}bp cost"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print("  render:", (r.stdout or r.stderr).strip().splitlines()[-1:] or [""])


if __name__ == "__main__":
    main()
