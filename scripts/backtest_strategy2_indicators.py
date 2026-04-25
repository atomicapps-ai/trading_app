#!/usr/bin/env python
"""
Strategy 2 (Double Lock) + indicator correlation analysis.

For every DL-S2 trade the strategy takes, compute a feature vector at the
moment of entry (10:00 bar close). Then measure which features correlate
with win/loss and whether top-ranked features, used as a filter, can push
WR into the 75-80% range.

Indicator list (see notes at top of file for ranking logic):
  1. spy_aligned      : 1 if SPY's 10:00 30-min candle direction == signal direction
  2. vwap_side        : 1 if entry price on favourable side of session VWAP
  3. rs_vs_spy        : stock's 10:00 % move - SPY's 10:00 % move (signed by signal)
  4. above_sma50_d    : 1 if daily close yesterday > 50-SMA  (LONG) / < 50-SMA (SHORT)
  5. vix_level        : ^VIX daily close yesterday (lower = trend regime)
  6. adx14_d          : 14-period ADX from daily bars (higher = trend)
  7. rsi14_d          : 14-period RSI from daily bars
  8. gap_pct          : (today's open - yesterday's close) / yesterday's close * 100,
                        signed by signal (positive = continuation gap)
  9. prior_day_match  : 1 if yesterday's day direction matches signal direction
 10. or_size_vs_atr   : 9:30 candle range / 14-day ATR

Outputs to stdout (redirected by cmds.py).
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
pd.set_option("display.width", 220)


SYMBOLS = [
    # Mega-cap tech
    "AAPL", "MSFT", "GOOGL", "GOOG", "META", "AMZN", "NVDA", "TSLA",
    "AVGO", "NFLX", "AMD", "INTC", "CRM", "ORCL", "ADBE",
    # Index ETFs
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV",
    # Other liquid
    "JPM", "BAC", "GS", "V", "MA", "JNJ", "UNH", "HD", "COST",
    "WMT", "BA", "CAT", "XOM", "CVX",
]

CONFIG = dict(
    body_thr  = 0.5,
    hprs_thr  = 0.5,
    lprs_thr  = 0.5,
    vol_mult  = 1.2,
    stop_pct  = 5.0,
)


# ── Data layer ───────────────────────────────────────────────────────────────
def fetch_15m(sym: str) -> pd.DataFrame | None:
    df = yf.download(sym, period="60d", interval="15m",
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert("America/New_York")
    return df


def fetch_daily(sym: str, days: int = 400) -> pd.DataFrame | None:
    df = yf.download(sym, period=f"{days}d", interval="1d",
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    return df


def resample_30m(df15: pd.DataFrame) -> pd.DataFrame:
    return (df15.resample("30min", closed="left", label="left")
            .agg(open=("open", "first"), high=("high", "max"),
                 low=("low", "min"), close=("close", "last"),
                 volume=("volume", "sum"))
            .dropna(subset=["open"]))


def slot_med_vol(df: pd.DataFrame) -> dict:
    out = {}
    for t in set(df.index.time):
        sub = df[df.index.time == t]
        if len(sub):
            out[t] = float(sub["volume"].median() or 1.0)
    return out


# ── Daily indicators ─────────────────────────────────────────────────────────
def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    up   = h.diff()
    down = -l.diff()
    plus_dm  = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    tr_n    = pd.Series(tr).ewm(alpha=1/n, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1/n, adjust=False).mean() / tr_n
    minus_di= 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/n, adjust=False).mean() / tr_n
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False).mean()


# ── Trade & feature types ────────────────────────────────────────────────────
@dataclass
class Trade:
    sym:      str
    date:     str
    dir:      str
    entry:    float
    exit:     float
    pnl_pct:  float
    win:      bool
    feats:    dict[str, Any] = field(default_factory=dict)


# ── Strategy evaluation w/ feature extraction ────────────────────────────────
def vwap_series(df15_day: pd.DataFrame) -> pd.Series:
    tp   = (df15_day["high"] + df15_day["low"] + df15_day["close"]) / 3.0
    cumv = df15_day["volume"].cumsum()
    return (tp * df15_day["volume"]).cumsum() / cumv.replace(0, np.nan)


def eval_day(sym: str, day, df15_day: pd.DataFrame, df30_day: pd.DataFrame,
             slot_avg: dict, daily_ctx: dict, spy_ctx: dict) -> Trade | None:
    if len(df30_day) < 2:
        return None
    c1, c2 = df30_day.iloc[0], df30_day.iloc[1]
    if c1.name.time().hour != 9 or c1.name.time().minute != 30:  return None
    if c2.name.time().hour != 10 or c2.name.time().minute != 0:   return None

    o1, h1, l1, cl1, v1 = [float(c1[k]) for k in ("open", "high", "low", "close", "volume")]
    o2, h2, l2, cl2     = [float(c2[k]) for k in ("open", "high", "low", "close")]

    def _body(o, h, l, c):
        r = h - l
        return abs(c - o) / r if r > 1e-9 else 0.0
    def _cp(h, l, c):
        r = h - l
        return (c - l) / r if r > 1e-9 else 0.5

    p = CONFIG
    c1_body = _body(o1, h1, l1, cl1) >= p["body_thr"]
    c2_body = _body(o2, h2, l2, cl2) >= p["body_thr"]
    c1_cp   = _cp(h1, l1, cl1)
    c1_hvol = v1 >= slot_avg.get(c1.name.time(), 0.0) * p["vol_mult"]

    bull = cl1 > o1 and c1_body and c1_cp >= p["hprs_thr"] and c1_hvol and cl2 > o2 and c2_body
    bear = cl1 < o1 and c1_body and c1_cp <= p["lprs_thr"] and c1_hvol and cl2 < o2 and c2_body

    if bull:    direction = "LONG"
    elif bear:  direction = "SHORT"
    else:       return None

    entry   = cl2
    stop_px = (entry * (1 - p["stop_pct"]/100) if direction == "LONG"
               else entry * (1 + p["stop_pct"]/100))

    post = df15_day[(df15_day.index > c2.name) &
                    (df15_day.index.time <= pd.Timestamp("15:59").time())]
    if post.empty: return None

    exit_px = None
    for _, b in post.iterrows():
        if direction == "LONG" and float(b["low"]) <= stop_px:
            exit_px = stop_px; break
        if direction == "SHORT" and float(b["high"]) >= stop_px:
            exit_px = stop_px; break
    if exit_px is None:
        exit_px = float(post.iloc[-1]["close"])

    raw = (exit_px - entry) / entry * 100
    pnl = raw if direction == "LONG" else -raw

    sign = 1 if direction == "LONG" else -1

    # ── Features ────────────────────────────────────────────────────────────
    # 1. SPY aligned: SPY 10:00 candle direction same as signal?
    spy_day = spy_ctx.get("df30_by_day", {}).get(day, None)
    spy_aligned = np.nan
    rs_vs_spy   = np.nan
    if spy_day is not None and len(spy_day) >= 2:
        spy_c1 = spy_day.iloc[0]; spy_c2 = spy_day.iloc[1]
        spy_open_1000 = float(spy_c1["open"])
        spy_close_1000 = float(spy_c2["close"])
        spy_dir = 1 if spy_close_1000 > spy_open_1000 else -1
        spy_aligned = 1 if spy_dir == sign else 0
        spy_pct = (spy_close_1000 - spy_open_1000) / spy_open_1000 * 100
        stock_pct = (cl2 - o1) / o1 * 100  # move from 9:30 open to 10:00 close
        rs_vs_spy = (stock_pct - spy_pct) * sign  # positive = stock beating SPY on signal day

    # 2. VWAP side at entry
    vwap = vwap_series(df15_day[df15_day.index <= c2.name])
    vwap_at_entry = float(vwap.iloc[-1]) if len(vwap) else np.nan
    vwap_side = 1 if (direction == "LONG" and entry > vwap_at_entry) or \
                     (direction == "SHORT" and entry < vwap_at_entry) else 0

    # 3-9. Daily context (yesterday's close)
    d = daily_ctx
    ds = d.get("slice")
    if ds is not None and len(ds):
        # Use the daily row immediately BEFORE `day` (avoids lookahead)
        day_ts   = pd.Timestamp(day)
        prev_idx = ds.index[ds.index < day_ts]
        if len(prev_idx):
            prev = ds.loc[prev_idx[-1]]
            sma50 = float(ds["sma50"].loc[prev_idx[-1]]) if pd.notna(ds["sma50"].loc[prev_idx[-1]]) else np.nan
            rsi14 = float(ds["rsi14"].loc[prev_idx[-1]]) if pd.notna(ds["rsi14"].loc[prev_idx[-1]]) else np.nan
            adx14 = float(ds["adx14"].loc[prev_idx[-1]]) if pd.notna(ds["adx14"].loc[prev_idx[-1]]) else np.nan
            atr14 = float(ds["atr14"].loc[prev_idx[-1]]) if pd.notna(ds["atr14"].loc[prev_idx[-1]]) else np.nan
            prev_close = float(prev["close"])
            prev_open  = float(prev["open"])

            above_sma50 = np.nan
            if pd.notna(sma50):
                above_sma50 = 1 if (direction == "LONG" and prev_close > sma50) or \
                                   (direction == "SHORT" and prev_close < sma50) else 0
            gap_pct = (o1 - prev_close) / prev_close * 100 * sign
            prior_day_match = 1 if ((prev_close > prev_open) and direction == "LONG") or \
                                   ((prev_close < prev_open) and direction == "SHORT") else 0
            or_size = h1 - l1
            or_vs_atr = or_size / atr14 if (pd.notna(atr14) and atr14 > 0) else np.nan
        else:
            above_sma50 = gap_pct = prior_day_match = or_vs_atr = np.nan
            rsi14 = adx14 = np.nan
    else:
        above_sma50 = gap_pct = prior_day_match = or_vs_atr = np.nan
        rsi14 = adx14 = np.nan

    vix = spy_ctx.get("vix_by_day", {}).get(day, np.nan)

    feats = dict(
        spy_aligned     = spy_aligned,
        vwap_side       = vwap_side,
        rs_vs_spy       = rs_vs_spy,
        above_sma50_d   = above_sma50,
        vix_level       = vix,
        adx14_d         = adx14,
        rsi14_d         = rsi14,
        gap_pct         = gap_pct,
        prior_day_match = prior_day_match,
        or_size_vs_atr  = or_vs_atr,
    )

    return Trade(sym, str(day), direction, entry, exit_px, pnl, pnl > 0, feats)


# ── Orchestration ────────────────────────────────────────────────────────────
def build_daily_ctx(sym: str) -> dict:
    d = fetch_daily(sym)
    if d is None or d.empty:
        return {"slice": None}
    d = d.copy()
    d["sma50"] = sma(d["close"], 50)
    d["rsi14"] = rsi(d["close"], 14)
    d["adx14"] = adx(d, 14)
    d["atr14"] = atr(d, 14)
    return {"slice": d}


def run() -> None:
    print(f"Universe ({len(SYMBOLS)} symbols): {SYMBOLS}")
    print(f"Config: {CONFIG}")

    # SPY context — 30-min bars by day + VIX by day
    print("\nFetching SPY + VIX context...")
    spy_15 = fetch_15m("SPY")
    spy_30 = resample_30m(spy_15) if spy_15 is not None else None
    spy_30_by_day: dict = {}
    if spy_30 is not None:
        for day in sorted(set(spy_30.index.date)):
            d_slice = spy_30[spy_30.index.date == day].between_time("09:30", "15:59")
            spy_30_by_day[day] = d_slice

    vix_daily = fetch_daily("^VIX")
    vix_by_day: dict = {}
    if vix_daily is not None:
        for ts, row in vix_daily.iterrows():
            vix_by_day[ts.date()] = float(row["close"])

    spy_ctx = {"df30_by_day": spy_30_by_day, "vix_by_day": vix_by_day}

    # Per-symbol 15m + daily, evaluate
    trades: list[Trade] = []
    for i, sym in enumerate(SYMBOLS, 1):
        print(f"  [{i:2d}/{len(SYMBOLS)}] {sym}", end=" ", flush=True)
        df15 = fetch_15m(sym)
        if df15 is None or df15.empty:
            print("no 15m"); continue
        df30 = resample_30m(df15)
        slot_avg = slot_med_vol(df30)
        dctx = build_daily_ctx(sym)
        n_before = len(trades)
        for day in sorted(set(df15.index.date)):
            df15_day = df15[df15.index.date == day].between_time("09:30", "15:59")
            df30_day = df30[df30.index.date == day].between_time("09:30", "15:59")
            if len(df15_day) < 5 or len(df30_day) < 2: continue
            t = eval_day(sym, day, df15_day, df30_day, slot_avg, dctx, spy_ctx)
            if t is not None:
                trades.append(t)
        print(f"+{len(trades) - n_before}")

    print(f"\nTotal trades: {len(trades)}")
    if not trades:
        print("No trades — abort.")
        return

    df = pd.DataFrame([{**{"sym": t.sym, "date": t.date, "dir": t.dir,
                            "pnl_pct": t.pnl_pct, "win": int(t.win)}, **t.feats}
                       for t in trades])

    base_wr = df["win"].mean() * 100
    print(f"\nBaseline win-rate (no filter): {base_wr:.1f}%  (n={len(df)})")

    # ── Correlation analysis ─────────────────────────────────────────────────
    feat_cols = ["spy_aligned", "vwap_side", "rs_vs_spy", "above_sma50_d",
                 "vix_level", "adx14_d", "rsi14_d", "gap_pct",
                 "prior_day_match", "or_size_vs_atr"]

    print("\n" + "=" * 88)
    print(f"  INDICATOR CORRELATION  (point-biserial vs win=1/loss=0, N={len(df)})")
    print("=" * 88)
    print(f"  {'feature':<18} {'corr':>8} {'n_valid':>8}   WR by quartile (Q1 ... Q4)")
    print("  " + "-" * 86)

    rows = []
    for f in feat_cols:
        s = df[f].dropna()
        w = df.loc[s.index, "win"]
        if len(s) < 10 or s.std() == 0:
            print(f"  {f:<18} {'n/a':>8} {len(s):>8}")
            continue
        corr = float(np.corrcoef(s, w)[0, 1])

        # Quartile breakdown. For binary features just bucket by value.
        if set(s.unique()).issubset({0.0, 1.0}):
            wr0 = w[s == 0].mean() * 100 if (s == 0).any() else float("nan")
            wr1 = w[s == 1].mean() * 100 if (s == 1).any() else float("nan")
            n0 = int((s == 0).sum()); n1 = int((s == 1).sum())
            quartile_str = f"=0 WR={wr0:.0f}% n={n0:3d}  |  =1 WR={wr1:.0f}% n={n1:3d}"
        else:
            try:
                q = pd.qcut(s, 4, labels=False, duplicates="drop")
                wrs = [w[q == i].mean() * 100 for i in range(q.max() + 1)]
                ns  = [int((q == i).sum()) for i in range(q.max() + 1)]
                quartile_str = "  ".join(f"Q{i+1}={wr:.0f}%(n={n})"
                                           for i, (wr, n) in enumerate(zip(wrs, ns)))
            except Exception:
                quartile_str = "—"
        rows.append((f, corr, len(s), quartile_str))
        print(f"  {f:<18} {corr:+8.3f} {len(s):>8}   {quartile_str}")

    # ── Joint filter: top 3 positive-correlation features ───────────────────
    print("\n" + "=" * 88)
    print("  JOINT FILTERS — top positively-correlated features combined")
    print("=" * 88)

    positives = sorted([(r[0], r[1]) for r in rows if r[1] == r[1]],
                        key=lambda x: -x[1])
    print(f"  Ranked features by |corr|: {[(f, round(c,3)) for f,c in positives]}")

    # Try filter combos: require all listed features to be 'favourable'
    # Binary features must be 1; continuous features thresholded at median/Q3/etc.
    def apply_filter(df: pd.DataFrame, recipe: list[tuple[str, Any]]) -> pd.DataFrame:
        out = df.copy()
        for f, rule in recipe:
            if isinstance(rule, tuple):
                op, thr = rule
                if op == ">":   out = out[out[f] >  thr]
                elif op == ">=":out = out[out[f] >= thr]
                elif op == "<": out = out[out[f] <  thr]
                elif op == "<=":out = out[out[f] <= thr]
            else:
                out = out[out[f] == rule]
        return out

    def report(df: pd.DataFrame, tag: str) -> None:
        if len(df) == 0:
            print(f"  {tag:<68} n=  0"); return
        wr = df["win"].mean() * 100
        pf_num = df.loc[df["pnl_pct"] > 0, "pnl_pct"].sum()
        pf_den = -df.loc[df["pnl_pct"] < 0, "pnl_pct"].sum()
        pf = pf_num / pf_den if pf_den > 0 else float("inf")
        avg = df["pnl_pct"].mean()
        print(f"  {tag:<68} n={len(df):3d}  WR={wr:5.1f}%  PF={pf:5.2f}  avg={avg:+.2f}%")

    recipes = [
        ("spy_aligned=1",                               [("spy_aligned", 1)]),
        ("vwap_side=1",                                 [("vwap_side", 1)]),
        ("above_sma50_d=1",                             [("above_sma50_d", 1)]),
        ("spy_aligned=1 + vwap_side=1",                 [("spy_aligned", 1), ("vwap_side", 1)]),
        ("spy_aligned=1 + above_sma50_d=1",             [("spy_aligned", 1), ("above_sma50_d", 1)]),
        ("spy_aligned=1 + vwap_side=1 + above_sma50_d=1",
         [("spy_aligned", 1), ("vwap_side", 1), ("above_sma50_d", 1)]),
        ("spy_aligned=1 + rs_vs_spy>0",
         [("spy_aligned", 1), ("rs_vs_spy", (">", 0.0))]),
        ("spy_aligned=1 + vwap_side=1 + rs_vs_spy>0",
         [("spy_aligned", 1), ("vwap_side", 1), ("rs_vs_spy", (">", 0.0))]),
        ("all 4: spy_aligned + vwap_side + above_sma50_d + rs_vs_spy>0",
         [("spy_aligned", 1), ("vwap_side", 1), ("above_sma50_d", 1),
          ("rs_vs_spy", (">", 0.0))]),
    ]

    for tag, recipe in recipes:
        report(apply_filter(df, recipe), tag)

    # Save trade dump for further inspection
    df.to_csv("claude_trades_dump.csv", index=False)
    print("\nTrade dump -> claude_trades_dump.csv")


if __name__ == "__main__":
    run()
