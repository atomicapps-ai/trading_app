#!/usr/bin/env python
"""
Strategy 2 (Double Lock) — Round 2 indicator analysis.

Round 1 finding: broader universe baseline WR = 43%, NOT 60%.
The real edge: rsi14_d (-0.20) and vix_level (+0.22) suggest the pattern is
actually an EXHAUSTION signal — it works best as a fade in high-VIX regimes
on extended names, not as trend continuation.

This round tests:
  1. WR by direction (LONG vs SHORT)
  2. Direction x RSI interaction
  3. Direction x VIX interaction
  4. "Flip on extreme RSI" variant: take the opposite side when RSI is extreme
  5. Grid search over RSI / VIX / ADX thresholds for WR >= 75-80%
  6. Full signal-reversal variants (always fade)

Reads the trade dump from round 1; does not re-download.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DUMP = ROOT / "claude_trades_dump.csv"


def describe(df: pd.DataFrame, tag: str) -> None:
    if len(df) == 0:
        print(f"  {tag:<70} n=  0")
        return
    wr = df["win"].mean() * 100
    pf_num = df.loc[df["pnl_pct"] > 0, "pnl_pct"].sum()
    pf_den = -df.loc[df["pnl_pct"] < 0, "pnl_pct"].sum()
    pf = pf_num / pf_den if pf_den > 0 else float("inf")
    avg = df["pnl_pct"].mean()
    total = df["pnl_pct"].sum()
    print(f"  {tag:<70} n={len(df):3d}  WR={wr:5.1f}%  PF={pf:5.2f}  avg={avg:+.2f}%  sum={total:+6.2f}%")


def flip(df: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    """Return a copy where rows matching mask have pnl_pct and win flipped."""
    out = df.copy()
    out.loc[mask, "pnl_pct"] = -out.loc[mask, "pnl_pct"]
    out.loc[mask, "win"] = (out.loc[mask, "pnl_pct"] > 0).astype(int)
    # Also flip dir label for readability
    out.loc[mask, "dir"] = out.loc[mask, "dir"].map({"LONG": "SHORT", "SHORT": "LONG"})
    return out


def main() -> None:
    if not DUMP.exists():
        print(f"Missing {DUMP}. Run scripts/backtest_strategy2_indicators.py first.")
        return
    df = pd.read_csv(DUMP)
    print(f"Loaded {len(df)} trades from {DUMP.name}")
    print(f"Base WR: {df['win'].mean()*100:.1f}%   sum PnL: {df['pnl_pct'].sum():+.2f}%\n")

    # ── 1. Direction breakdown ──────────────────────────────────────────────
    print("=" * 92)
    print("  1. DIRECTION BREAKDOWN")
    print("=" * 92)
    describe(df, "ALL")
    describe(df[df["dir"] == "LONG"],  "LONG only")
    describe(df[df["dir"] == "SHORT"], "SHORT only")

    # ── 2. Direction x RSI interaction ──────────────────────────────────────
    print("\n" + "=" * 92)
    print("  2. DIRECTION x RSI14 (yesterday's daily RSI)")
    print("=" * 92)
    df["rsi_q"] = pd.qcut(df["rsi14_d"], 4, labels=["Q1","Q2","Q3","Q4"], duplicates="drop")
    for d in ("LONG", "SHORT"):
        print(f"\n  -- {d} signals --")
        for q in ("Q1","Q2","Q3","Q4"):
            sub = df[(df["dir"] == d) & (df["rsi_q"] == q)]
            describe(sub, f"{d} + RSI {q}")

    # ── 3. Direction x VIX interaction ──────────────────────────────────────
    print("\n" + "=" * 92)
    print("  3. DIRECTION x VIX (yesterday's VIX close)")
    print("=" * 92)
    df["vix_q"] = pd.qcut(df["vix_level"], 4, labels=["Q1","Q2","Q3","Q4"], duplicates="drop")
    for d in ("LONG", "SHORT"):
        print(f"\n  -- {d} signals --")
        for q in ("Q1","Q2","Q3","Q4"):
            sub = df[(df["dir"] == d) & (df["vix_q"] == q)]
            describe(sub, f"{d} + VIX {q}")

    # ── 4. Flip-on-extreme-RSI variants ─────────────────────────────────────
    print("\n" + "=" * 92)
    print("  4. FLIP-ON-EXTREME-RSI  (take the opposite side when RSI is extreme)")
    print("=" * 92)
    # Variant A: always fade LONG signals above RSI 70; always fade SHORT signals below 30.
    for rsi_hi in (65, 70, 75):
        for rsi_lo in (25, 30, 35):
            mask = ((df["dir"] == "LONG")  & (df["rsi14_d"] >= rsi_hi)) | \
                   ((df["dir"] == "SHORT") & (df["rsi14_d"] <= rsi_lo))
            flipped = flip(df, mask)
            describe(flipped, f"flip LONG@RSI>={rsi_hi} | SHORT@RSI<={rsi_lo}  (flipped {int(mask.sum())})")

    # ── 5. Always-fade (pure contrarian) ────────────────────────────────────
    print("\n" + "=" * 92)
    print("  5. ALWAYS-FADE  (take the opposite side of every signal)")
    print("=" * 92)
    fade = df.copy()
    fade["pnl_pct"] = -fade["pnl_pct"]
    fade["win"] = (fade["pnl_pct"] > 0).astype(int)
    describe(fade, "FADE all signals")
    describe(fade[fade["dir"] == "LONG"],  "FADE LONG-signals (i.e. short them)")
    describe(fade[fade["dir"] == "SHORT"], "FADE SHORT-signals (i.e. long them)")

    # ── 6. Joint filter grid: VIX >= x, ADX <= y, RSI-aligned ───────────────
    print("\n" + "=" * 92)
    print("  6. JOINT-FILTER GRID (VIX >= v, ADX <= a, RSI-aligned with direction)")
    print("     RSI-aligned = LONG when RSI low (<= rsi_long) OR SHORT when RSI high (>= rsi_short)")
    print("=" * 92)
    for vix_thr in (15, 18, 20, 22, 25):
        for adx_thr in (20, 25, 30, 35, 100):
            for rsi_long_hi, rsi_short_lo in [(50, 50), (55, 45), (60, 40), (65, 35)]:
                rsi_ok = ((df["dir"] == "LONG")  & (df["rsi14_d"] <= rsi_long_hi)) | \
                         ((df["dir"] == "SHORT") & (df["rsi14_d"] >= rsi_short_lo))
                sub = df[(df["vix_level"] >= vix_thr) &
                         (df["adx14_d"]   <= adx_thr) &
                         rsi_ok]
                if len(sub) < 8: continue
                tag = f"VIX>={vix_thr}  ADX<={adx_thr}  RSI: L<={rsi_long_hi}/S>={rsi_short_lo}"
                describe(sub, tag)

    # ── 7. Same grid but on the FADE variant ────────────────────────────────
    print("\n" + "=" * 92)
    print("  7. SAME GRID ON THE FADE VARIANT  (reverse the signal)")
    print("=" * 92)
    for vix_thr in (15, 18, 20, 22, 25):
        for adx_thr in (20, 25, 30, 35, 100):
            for rsi_long_hi, rsi_short_lo in [(50, 50), (55, 45), (60, 40), (65, 35)]:
                # After fading: original LONG signals become SHORT trades (win when price drops).
                # So "RSI-aligned" for the FADE means: original LONG when RSI HIGH, original SHORT when RSI LOW.
                rsi_ok = ((df["dir"] == "LONG")  & (df["rsi14_d"] >= rsi_short_lo)) | \
                         ((df["dir"] == "SHORT") & (df["rsi14_d"] <= rsi_long_hi))
                sub = df[(df["vix_level"] >= vix_thr) &
                         (df["adx14_d"]   <= adx_thr) &
                         rsi_ok].copy()
                if len(sub) < 8: continue
                sub["pnl_pct"] = -sub["pnl_pct"]
                sub["win"] = (sub["pnl_pct"] > 0).astype(int)
                tag = f"FADE + VIX>={vix_thr}  ADX<={adx_thr}  RSI: origL>={rsi_short_lo}/origS<={rsi_long_hi}"
                describe(sub, tag)


if __name__ == "__main__":
    main()
