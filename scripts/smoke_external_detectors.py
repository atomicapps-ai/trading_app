"""Smoke test all external detectors on AAPL_1d to confirm translations work.

Each detector should produce a non-trivial number of signals (at least a
few dozen over 14 years of daily bars) and trades should have sane PnL %.
This is a quick sanity check before kicking off the optimizer.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")                            # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from agents.detectors.external import (
    bollinger_rsi_chartart,
    macd_sma200_chartart,
    pmax_explorer,
    supertrend_kivanc,
)
from agents.detectors.external._base import simulate_trades, summarize_trades


SYMBOLS = ["AAPL", "SPY", "TSLA", "MSFT"]
DETECTORS = [
    bollinger_rsi_chartart,
    macd_sma200_chartart,
    supertrend_kivanc,
    pmax_explorer,
]


def load_daily(symbol: str) -> pd.DataFrame:
    p = ROOT / "data" / "historical" / f"{symbol}_1d.csv"
    if not p.exists():
        raise FileNotFoundError(p)
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    df.columns = [c.strip().lower() for c in df.columns]
    if "adj_close" in df.columns and "close" in df.columns:
        df["close"] = df["adj_close"]
    cols = ["open", "high", "low", "close", "volume"]
    df = df[[c for c in cols if c in df.columns]].dropna()
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


def main() -> int:
    print(f"smoke test: {len(DETECTORS)} detectors x {len(SYMBOLS)} symbols on 1d")
    print("-" * 96)
    print(f"{'detector':<30} {'symbol':<6} {'sigs':>6} {'trades':>7} "
          f"{'wr%':>6} {'pf':>6} {'net$':>10} {'score':>7}")
    print("-" * 96)

    for det in DETECTORS:
        params = {n: spec["default"] for n, spec in det.PARAMETER_SPEC.items()}
        for sym in SYMBOLS:
            try:
                bars = load_daily(sym)
            except FileNotFoundError:
                print(f"{det.META['slug']:<30} {sym:<6} (no bars)")
                continue
            sigs = det.detect(bars, params)
            trades = simulate_trades(bars, sigs)
            s = summarize_trades(trades)
            print(f"{det.META['slug']:<30} {sym:<6} {len(sigs):>6d} "
                  f"{s['n_trades']:>7d} {s['wr_pct']:>6.1f} "
                  f"{s['profit_factor']:>6.2f} {s['net_pnl_usd']:>10.0f} "
                  f"{s['score']:>7.3f}")
    print("-" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
