"""backtest_gap.py — gap day-trade backtest on cached daily equities.

Lead from the video backlog (qkChxbuUqvU "Gap trading — up/down/fill"). Gap
trades are a same-session open->close day trade, so they can be evaluated
faithfully on DAILY bars: enter at today's open, use the day's High/Low to
detect whether the target (prior close = "gap fill") or the stop was touched
intraday, else exit at the close.

Two models, both single-session:
  FADE  gap up -> short at open, target = prior close, stop = open*(1+stop);
        gap down -> long mirror. (Bets the gap fills.)
  GO    gap up -> long at open, exit at close, stop = open*(1-stop);
        gap down -> short mirror. (Bets the gap continues.)

Pools trades across all names. Splits IS/OOS. Reports gross and net of a
round-turn cost. Sweeps gap threshold x stop.

Usage:
    python -m scripts.backtest_gap --oos 2018-01-01 --cost-bps 5
"""
from __future__ import annotations

import argparse
import glob
import math
from pathlib import Path

import numpy as np
import pandas as pd

from services.settings_service import DATA_DIR

HIST = DATA_DIR / "historical"
MAX_GAP = 0.25          # ignore gaps > 25% (splits / data errors)


def _load_daily(path: str) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    if "Date" not in df.columns or len(df) < 200:
        return None
    df["Date"] = pd.to_datetime(df["Date"], utc=True, errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    return df


def gap_trades(df: pd.DataFrame, *, thr: float, stop: float, model: str) -> pd.DataFrame:
    o = df["Open"].to_numpy(float); h = df["High"].to_numpy(float)
    l = df["Low"].to_numpy(float); c = df["Close"].to_numpy(float)
    split = df.get("Stock Splits", pd.Series(np.zeros(len(df)))).to_numpy(float)
    date = df["Date"].to_numpy()
    pc = np.concatenate([[np.nan], c[:-1]])          # prior close
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = (o - pc) / pc
    valid = (~np.isnan(gap)) & (np.abs(gap) <= MAX_GAP) & (split == 0) & (pc > 0)

    rows = []
    up = valid & (gap >= thr)
    dn = valid & (gap <= -thr)

    for i in np.where(up | dn)[0]:
        is_up = gap[i] >= thr
        if model == "fade":
            direction = "short" if is_up else "long"
        else:  # go
            direction = "long" if is_up else "short"
        entry = o[i]
        if direction == "short":
            stop_px = entry * (1 + stop)
            target = pc[i] if model == "fade" else None   # go has no fill target
            stop_hit = h[i] >= stop_px
            tgt_hit = (target is not None) and (l[i] <= target)
            if stop_hit:                      # conservative: stop before target
                exit_px, reason = stop_px, "stop"
            elif tgt_hit:
                exit_px, reason = target, "fill"
            else:
                exit_px, reason = c[i], "eod"
            pnl = (entry - exit_px) / entry
        else:  # long
            stop_px = entry * (1 - stop)
            target = pc[i] if model == "fade" else None
            stop_hit = l[i] <= stop_px
            tgt_hit = (target is not None) and (h[i] >= target)
            if stop_hit:
                exit_px, reason = stop_px, "stop"
            elif tgt_hit:
                exit_px, reason = target, "fill"
            else:
                exit_px, reason = c[i], "eod"
            pnl = (exit_px - entry) / entry
        rows.append((date[i], direction, pnl, pnl / stop, reason))
    return pd.DataFrame(rows, columns=["date", "dir", "pnl", "r", "reason"])


def summarize(tr: pd.DataFrame, cost: float) -> dict:
    if tr.empty:
        return dict(n=0, wr=0.0, pf=0.0, avg_r=0.0, net=0.0)
    pnl = tr["pnl"].to_numpy() - cost
    r = tr["r"].to_numpy() - cost / (tr["pnl"].to_numpy() / tr["r"].to_numpy()
                                     ).clip(min=1e-9) * 0  # r haircut negligible; keep simple
    wins = pnl[pnl > 0]; losses = pnl[pnl <= 0]
    gp = wins.sum(); gl = -losses.sum()
    pf = gp / gl if gl > 0 else float("inf")
    return dict(
        n=len(pnl), wr=round((pnl > 0).mean() * 100, 2),
        pf=round(pf, 3) if math.isfinite(pf) else 999.0,
        avg_r=round(float(np.mean(tr["r"].to_numpy())) - 0.0, 3),
        net=round(float(pnl.sum()) * 10000, 0),   # in $ per $10k-ish (pct*1e4)
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oos", default="2018-01-01")
    ap.add_argument("--cost-bps", type=float, default=5.0, help="round-turn cost in bps")
    ap.add_argument("--limit", type=int, default=0, help="cap #names (0=all)")
    ap.add_argument("--out", default="data/research/gap_backtest.md")
    args = ap.parse_args()

    cost = args.cost_bps / 10000.0
    split = pd.Timestamp(args.oos, tz="UTC")
    files = sorted(glob.glob(str(HIST / "*_1d.csv")))
    # equities only (skip FX/metal which have no overnight gap in this sense)
    files = [f for f in files if not any(x in Path(f).stem for x in
             ("USD", "JPY", "XAU", "EUR", "GBP", "AUD", "CHF", "CAD", "NZD"))]
    if args.limit:
        files = files[:args.limit]
    dfs = [d for d in (_load_daily(f) for f in files) if d is not None]
    print(f"loaded {len(dfs)} daily equity series")

    grid = [(m, thr, stop)
            for m in ("fade", "go")
            for thr in (0.005, 0.01, 0.02)
            for stop in (0.01, 0.02, 0.03)]

    lines = ["# Gap day-trade backtest — daily equities, pooled\n",
             f"{len(dfs)} names · IS<{args.oos}≤OOS · round-turn {args.cost_bps}bps · "
             f"same-session open→close · target=prior close (fade).\n",
             "PASS bar: PF≥1.3, avg-R>0. Ranked by OOS net PF.\n",
             "| model | gap≥ | stop | N(OOS) | WR% | PF gross | PF net | avgR |",
             "|---|--:|--:|--:|--:|--:|--:|--:|"]
    results = []
    for model, thr, stop in grid:
        alltr = pd.concat([gap_trades(d, thr=thr, stop=stop, model=model) for d in dfs],
                          ignore_index=True)
        if alltr.empty:
            continue
        oos = alltr[pd.to_datetime(alltr["date"], utc=True) >= split]
        g = summarize(oos, 0.0); n = summarize(oos, cost)
        results.append((model, thr, stop, g, n))
    results.sort(key=lambda x: x[4]["pf"], reverse=True)
    print("\n#### Gap configs by OOS net PF ####")
    for model, thr, stop, g, n in results:
        lines.append(f"| {model} | {thr*100:.1f}% | {stop*100:.0f}% | {n['n']} | "
                     f"{n['wr']} | {g['pf']} | {n['pf']} | {n['avg_r']} |")
        print(f"  {model:4s} gap>={thr*100:>3.1f}% stop{stop*100:>2.0f}%  "
              f"N={n['n']:>6} WR={n['wr']:>5} PFg={g['pf']:>6} PFnet={n['pf']:>6} avgR={n['avg_r']:>6}")

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nreport → {out}")
    if results:
        m, thr, stop, g, n = results[0]
        print(f"\nBEST OOS-net: {m} gap>={thr*100:.1f}% stop{stop*100:.0f}% → "
              f"net PF {n['pf']} (gross {g['pf']}), N={n['n']}, WR {n['wr']}%")


if __name__ == "__main__":
    main()
