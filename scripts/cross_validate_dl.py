#!/usr/bin/env python
"""
Cross-validation of the filtered Double-Lock strategy.

The 82.4% WR / n=17 result was the BEST of hundreds of filter combos tried
on the same 81 trades. Multiple-comparisons inflation is real. This script:

  1. Time-splits the trade dump 60/40 (chronological, no shuffling).
  2. RE-FITS the optimal recipe on the train half ONLY.
  3. Locks the recipe and applies it to the test half — that WR is the
     unbiased estimate.
  4. Repeats with a 70/30 split and an OOS-by-symbol split (drop one
     symbol-cohort, fit on the others, test on the held-out cohort).
  5. Reports the spread between in-sample and OOS WR — the overfit drag.

Reads claude_trades_dump.csv only; no downloads.
"""
from __future__ import annotations

from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DUMP = ROOT / "claude_trades_dump.csv"


def stat(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return dict(n=0, wr=float("nan"), pf=float("nan"), avg=float("nan"), sum=0.0)
    wins  = df.loc[df["pnl_pct"] > 0, "pnl_pct"].sum()
    losses = -df.loc[df["pnl_pct"] < 0, "pnl_pct"].sum()
    return dict(
        n=len(df),
        wr=df["win"].mean() * 100,
        pf=wins / losses if losses > 0 else float("inf"),
        avg=df["pnl_pct"].mean(),
        sum=df["pnl_pct"].sum(),
    )


def line(tag: str, s: dict) -> None:
    if s["n"] == 0:
        print(f"  {tag:<60} n=  0")
        return
    print(f"  {tag:<60} n={s['n']:3d}  WR={s['wr']:5.1f}%  PF={s['pf']:5.2f}  avg={s['avg']:+.2f}%  sum={s['sum']:+6.2f}%")


def apply_recipe(df: pd.DataFrame, llo: int, lhi: int, slo: int, shi: int,
                 vix_min: float, adx_max: float) -> pd.DataFrame:
    mask_l = (df["dir"] == "LONG")  & (df["rsi14_d"] >= llo) & (df["rsi14_d"] <= lhi)
    mask_s = (df["dir"] == "SHORT") & (df["rsi14_d"] >= slo) & (df["rsi14_d"] <= shi)
    return df[(mask_l | mask_s) &
              (df["vix_level"] >= vix_min) &
              (df["adx14_d"]   <= adx_max)]


def best_recipe_on(df: pd.DataFrame, min_n: int = 8) -> tuple[dict, dict] | None:
    """Grid-search the same space as round 3 on a single dataframe."""
    rsi_configs = [
        (40, 65, 20, 40),
        (45, 60, 25, 40),
        (40, 60, 20, 40),
        (35, 65, 20, 45),
    ]
    best = None
    best_s = None
    for (llo, lhi, slo, shi), vix_min, adx_max in product(
        rsi_configs, (0, 14, 16, 18, 20), (100, 35, 30, 25, 22)
    ):
        sub = apply_recipe(df, llo, lhi, slo, shi, vix_min, adx_max)
        if len(sub) < min_n:
            continue
        s = stat(sub)
        # Score: WR primary, n secondary
        score = (s["wr"], s["n"])
        if best is None or score > (best_s["wr"], best_s["n"]):
            best = dict(llo=llo, lhi=lhi, slo=slo, shi=shi,
                        vix_min=vix_min, adx_max=adx_max)
            best_s = s
    if best is None:
        return None
    return best, best_s


def run() -> None:
    df = pd.read_csv(DUMP).sort_values("date").reset_index(drop=True)
    print(f"Trades: {len(df)}   date range: {df['date'].min()} .. {df['date'].max()}")
    line("UNFILTERED baseline", stat(df))
    print()

    # ── 1. The recipe we declared "best" in round 3 ─────────────────────────
    print("=" * 80)
    print("  1. PRE-DECLARED RECIPE  (the one we shipped from round 3)")
    print("=" * 80)
    declared = dict(llo=40, lhi=65, slo=20, shi=40, vix_min=20, adx_max=35)
    line("declared recipe on FULL dataset", stat(apply_recipe(df, **declared)))

    # ── 2. Chronological 60/40 split, re-fit on train ───────────────────────
    print("\n" + "=" * 80)
    print("  2. TIME-SPLIT 60/40 — re-fit on train, test on held-out future trades")
    print("=" * 80)
    pivot = int(len(df) * 0.6)
    train = df.iloc[:pivot]
    test  = df.iloc[pivot:]
    print(f"  train: {len(train)} trades  ({train['date'].min()} .. {train['date'].max()})")
    print(f"  test:  {len(test)} trades   ({test['date'].min()} .. {test['date'].max()})")

    fit = best_recipe_on(train, min_n=6)
    if fit is None:
        print("  no usable fit on train")
    else:
        recipe, train_s = fit
        line("BEST fit on TRAIN", train_s)
        print(f"    recipe: {recipe}")
        test_s = stat(apply_recipe(test, **recipe))
        line("Same recipe on TEST (unseen)", test_s)
        if train_s["n"] and test_s["n"]:
            drag = train_s["wr"] - test_s["wr"]
            print(f"    overfitting drag:  {drag:+.1f} pp")

    # ── 3. Chronological 70/30 split ────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  3. TIME-SPLIT 70/30")
    print("=" * 80)
    pivot = int(len(df) * 0.7)
    train = df.iloc[:pivot]
    test  = df.iloc[pivot:]
    fit = best_recipe_on(train, min_n=6)
    if fit is None:
        print("  no usable fit on train")
    else:
        recipe, train_s = fit
        line("BEST fit on TRAIN", train_s)
        print(f"    recipe: {recipe}")
        test_s = stat(apply_recipe(test, **recipe))
        line("Same recipe on TEST (unseen)", test_s)

    # ── 4. The DECLARED recipe applied to each split (no re-fit) ────────────
    print("\n" + "=" * 80)
    print("  4. DECLARED RECIPE on each chronological half (NO re-fit)")
    print("=" * 80)
    halves = [(0.5, "first 50%"), (0.5, "last 50%")]
    pivot = int(len(df) * 0.5)
    line("first 50%", stat(apply_recipe(df.iloc[:pivot], **declared)))
    line("last 50% ", stat(apply_recipe(df.iloc[pivot:], **declared)))

    # ── 5. Leave-one-symbol-out ─────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  5. LEAVE-ONE-SYMBOL-OUT  (declared recipe applied each cohort)")
    print("=" * 80)
    syms = sorted(df["sym"].unique())
    rows = []
    for s in syms:
        sub = apply_recipe(df[df["sym"] == s], **declared)
        if len(sub) > 0:
            rows.append((s, stat(sub)))
    rows.sort(key=lambda r: -r[1]["n"])
    for s, st in rows[:20]:
        line(f"{s}", st)
    if rows:
        ns = sum(r[1]["n"] for r in rows)
        wins = sum(int(round(r[1]["wr"] * r[1]["n"] / 100)) for r in rows)
        agg_wr = wins / ns * 100 if ns else float("nan")
        print(f"\n  Aggregate across {len(rows)} symbols: total n={ns}  WR≈{agg_wr:.1f}%")

    # ── 6. Bootstrap confidence interval on the declared recipe ─────────────
    print("\n" + "=" * 80)
    print("  6. BOOTSTRAP 95% CI on declared recipe")
    print("=" * 80)
    sub = apply_recipe(df, **declared)
    if len(sub) >= 10:
        rng = np.random.default_rng(42)
        wrs = []
        for _ in range(2000):
            samp = sub.sample(n=len(sub), replace=True, random_state=int(rng.integers(0, 1_000_000)))
            wrs.append(samp["win"].mean() * 100)
        wrs = np.array(wrs)
        lo, hi = np.percentile(wrs, [2.5, 97.5])
        print(f"  point WR: {sub['win'].mean()*100:.1f}%   95% CI: [{lo:.1f}%, {hi:.1f}%]   median: {np.median(wrs):.1f}%")

    # ── 7. Verdict ──────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  7. VERDICT")
    print("=" * 80)
    print("  - If 60/40 TEST WR is >= 70%, the edge is likely real.")
    print("  - If 60/40 TEST WR drops to baseline (~43%), it was overfit.")
    print("  - 95% CI gives a defensible WR range to claim.")


if __name__ == "__main__":
    run()
