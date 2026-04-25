#!/usr/bin/env python
"""
Round 3 — explicit selective-RSI strategy + VIX/ADX layering.

Hypothesis from round 2:
  The signal is continuation-prediction, not exhaustion, BUT it fails at RSI
  extremes. Specifically:
    LONG  wins when RSI is mild/neutral (roughly Q2-Q3)
    SHORT wins when RSI is oversold  (roughly Q1)
    Both fail in the wrong regime.

This round:
  1. Scan RSI ranges for LONG and SHORT independently to find best WR slices.
  2. Layer VIX floor and ADX ceiling on the best slice.
  3. Find the highest-WR joint rule with n >= 15.
  4. Also report what fraction of original trades each rule keeps.

Reads claude_trades_dump.csv.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DUMP = ROOT / "claude_trades_dump.csv"


def stat(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return dict(n=0, wr=float("nan"), pf=float("nan"), avg=float("nan"), sum=0.0)
    wr = df["win"].mean() * 100
    pf_num = df.loc[df["pnl_pct"] > 0, "pnl_pct"].sum()
    pf_den = -df.loc[df["pnl_pct"] < 0, "pnl_pct"].sum()
    pf = pf_num / pf_den if pf_den > 0 else float("inf")
    return dict(n=len(df), wr=wr, pf=pf, avg=df["pnl_pct"].mean(), sum=df["pnl_pct"].sum())


def line(tag: str, s: dict) -> None:
    if s["n"] == 0:
        print(f"  {tag:<72} n=  0")
        return
    print(f"  {tag:<72} n={s['n']:3d}  WR={s['wr']:5.1f}%  "
          f"PF={s['pf']:5.2f}  avg={s['avg']:+.2f}%  sum={s['sum']:+6.2f}%")


def main() -> None:
    df = pd.read_csv(DUMP)
    long_df  = df[df["dir"] == "LONG"].copy()
    short_df = df[df["dir"] == "SHORT"].copy()
    print(f"Dataset: {len(df)} trades  ({len(long_df)} LONG, {len(short_df)} SHORT)")
    print(f"Base WR: {df['win'].mean()*100:.1f}%    LONG WR: {long_df['win'].mean()*100:.1f}%    "
          f"SHORT WR: {short_df['win'].mean()*100:.1f}%\n")

    # ── 1. RSI-range scan for LONG ─────────────────────────────────────────
    print("=" * 92)
    print("  1. BEST RSI RANGE FOR LONG  (sliding windows)")
    print("=" * 92)
    best_long: list[tuple] = []
    for lo in range(20, 71, 5):
        for hi in range(lo + 10, 91, 5):
            sub = long_df[(long_df["rsi14_d"] >= lo) & (long_df["rsi14_d"] <= hi)]
            if len(sub) < 8:
                continue
            s = stat(sub)
            best_long.append((lo, hi, s))
    best_long.sort(key=lambda x: -x[2]["wr"])
    for lo, hi, s in best_long[:15]:
        line(f"LONG  RSI in [{lo}, {hi}]", s)

    # ── 2. RSI-range scan for SHORT ────────────────────────────────────────
    print("\n" + "=" * 92)
    print("  2. BEST RSI RANGE FOR SHORT  (sliding windows)")
    print("=" * 92)
    best_short: list[tuple] = []
    for lo in range(10, 61, 5):
        for hi in range(lo + 10, 81, 5):
            sub = short_df[(short_df["rsi14_d"] >= lo) & (short_df["rsi14_d"] <= hi)]
            if len(sub) < 8:
                continue
            s = stat(sub)
            best_short.append((lo, hi, s))
    best_short.sort(key=lambda x: -x[2]["wr"])
    for lo, hi, s in best_short[:15]:
        line(f"SHORT  RSI in [{lo}, {hi}]", s)

    # ── 3. Combined selective strategy ─────────────────────────────────────
    print("\n" + "=" * 92)
    print("  3. COMBINED SELECTIVE STRATEGY  (top single-leg filters union'd)")
    print("=" * 92)
    # Take several candidate cutoffs from sections 1 & 2 and combine
    configs = [
        ("L:[40,65]  S:[20,40]",  (40, 65, 20, 40)),
        ("L:[40,60]  S:[20,40]",  (40, 60, 20, 40)),
        ("L:[40,65]  S:[25,45]",  (40, 65, 25, 45)),
        ("L:[40,70]  S:[20,45]",  (40, 70, 20, 45)),
        ("L:[35,65]  S:[20,40]",  (35, 65, 20, 40)),
        ("L:[45,60]  S:[25,40]",  (45, 60, 25, 40)),
        ("L:[45,65]  S:[20,40]",  (45, 65, 20, 40)),
        ("L:[40,60]  S:[25,45]",  (40, 60, 25, 45)),
    ]
    combined_results = []
    for tag, (llo, lhi, slo, shi) in configs:
        mask_l = (df["dir"] == "LONG")  & (df["rsi14_d"] >= llo) & (df["rsi14_d"] <= lhi)
        mask_s = (df["dir"] == "SHORT") & (df["rsi14_d"] >= slo) & (df["rsi14_d"] <= shi)
        sub = df[mask_l | mask_s]
        s = stat(sub)
        combined_results.append((tag, (llo, lhi, slo, shi), s))
        line(tag, s)

    # ── 4. Layer VIX floor on top of the best combined ─────────────────────
    print("\n" + "=" * 92)
    print("  4. BEST COMBINED + VIX FLOOR")
    print("=" * 92)
    combined_results.sort(key=lambda x: -x[2]["wr"])
    best_tag, (llo, lhi, slo, shi), _ = combined_results[0]
    print(f"  Base rule: {best_tag}")
    for vix_thr in (0, 12, 14, 15, 16, 18, 20, 22, 25):
        mask_l = (df["dir"] == "LONG")  & (df["rsi14_d"] >= llo) & (df["rsi14_d"] <= lhi)
        mask_s = (df["dir"] == "SHORT") & (df["rsi14_d"] >= slo) & (df["rsi14_d"] <= shi)
        sub = df[(mask_l | mask_s) & (df["vix_level"] >= vix_thr)]
        line(f"{best_tag}  +  VIX>={vix_thr}", stat(sub))

    # ── 5. Layer ADX ceiling ───────────────────────────────────────────────
    print("\n" + "=" * 92)
    print("  5. BEST COMBINED + ADX CEILING")
    print("=" * 92)
    for adx_thr in (100, 40, 35, 30, 28, 25, 22, 20):
        mask_l = (df["dir"] == "LONG")  & (df["rsi14_d"] >= llo) & (df["rsi14_d"] <= lhi)
        mask_s = (df["dir"] == "SHORT") & (df["rsi14_d"] >= slo) & (df["rsi14_d"] <= shi)
        sub = df[(mask_l | mask_s) & (df["adx14_d"] <= adx_thr)]
        line(f"{best_tag}  +  ADX<={adx_thr}", stat(sub))

    # ── 6. Full triple-layer: RSI + VIX + ADX ──────────────────────────────
    print("\n" + "=" * 92)
    print("  6. FULL TRIPLE-LAYER GRID  (target WR >= 75% with n >= 12)")
    print("=" * 92)
    # Explore a compact grid, keep only rows WR >= 65% AND n >= 10
    hits = []
    rsi_configs = [
        ("L:[40,65] S:[20,40]", 40, 65, 20, 40),
        ("L:[45,60] S:[25,40]", 45, 60, 25, 40),
        ("L:[40,60] S:[20,40]", 40, 60, 20, 40),
        ("L:[35,65] S:[20,45]", 35, 65, 20, 45),
    ]
    for rsi_tag, llo, lhi, slo, shi in rsi_configs:
        for vix_thr in (0, 14, 16, 18, 20):
            for adx_thr in (100, 35, 30, 25, 22):
                mask_l = (df["dir"] == "LONG")  & (df["rsi14_d"] >= llo) & (df["rsi14_d"] <= lhi)
                mask_s = (df["dir"] == "SHORT") & (df["rsi14_d"] >= slo) & (df["rsi14_d"] <= shi)
                sub = df[(mask_l | mask_s) &
                         (df["vix_level"] >= vix_thr) &
                         (df["adx14_d"]   <= adx_thr)]
                if len(sub) < 10:
                    continue
                s = stat(sub)
                tag = f"{rsi_tag}  VIX>={vix_thr}  ADX<={adx_thr}"
                hits.append((tag, s))
    hits.sort(key=lambda x: (-x[1]["wr"], -x[1]["n"]))
    print("  Top 20 by WR (n>=10):")
    for tag, s in hits[:20]:
        line(tag, s)

    # ── 7. Same grid requiring higher n for robustness ────────────────────
    print("\n" + "=" * 92)
    print("  7. SAME GRID, n>=15 (more robust)")
    print("=" * 92)
    for tag, s in [x for x in hits if x[1]["n"] >= 15][:15]:
        line(tag, s)

    # ── 8. Break-even vs cherry-pick check ─────────────────────────────────
    print("\n" + "=" * 92)
    print("  8. FINAL CANDIDATES  (plain-language recipes)")
    print("=" * 92)
    if hits:
        t, s = hits[0]
        print(f"\n  Highest WR with n>=10:  {t}")
        print(f"    WR {s['wr']:.1f}%  n={s['n']}  PF={s['pf']:.2f}  avg={s['avg']:+.2f}%  sum={s['sum']:+.2f}%")
    filt = [x for x in hits if x[1]["n"] >= 15]
    if filt:
        t, s = filt[0]
        print(f"\n  Highest WR with n>=15:  {t}")
        print(f"    WR {s['wr']:.1f}%  n={s['n']}  PF={s['pf']:.2f}  avg={s['avg']:+.2f}%  sum={s['sum']:+.2f}%")


if __name__ == "__main__":
    main()
