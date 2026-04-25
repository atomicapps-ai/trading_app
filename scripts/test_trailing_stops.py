#!/usr/bin/env python
"""
Compare exit-logic variants for the filtered DL-S2 strategy.

Re-fetches 15-min data for the 9 symbols that produce the filtered trades,
re-runs the strategy with the locked-in filter, then walks each trade
through six different exit policies bar-by-bar:

  1. Baseline           : 3% cat stop or 15:00 close, no trail
  2. Tight cat (1%)     : 1% cat stop or 15:00 close, no trail
  3. % trail immediate  : 3% cat + trail at peak +/- 0.5%, active from entry
  4. % trail post +0.5R : 3% cat + trail at peak +/- 0.5%, only after +0.5R
  5. Structural         : 3% cat + trail to previous 30m bar's low/high
  6. ATR trail          : 3% cat + trail at peak - 1.0 * 30m ATR (long)
  7. Tight + structural : 1% cat + structural trail

For each policy: WR, PF, avg PnL, total sum, avg hold time, exit-reason
breakdown. Pick the best policy and we'll ship it.

Filter recipe (from cross-validation):
    LONG  : rsi14_d in [40, 65], vix_prev >= 20, adx14_d <= 35
    SHORT : rsi14_d in [20, 40], vix_prev >= 20, adx14_d <= 35
    + DL-S2 candle structure (c1 conviction + c2 confirmation)
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
pd.set_option("display.width", 200)


# ── Filter recipe (locked from round 3 + cross-val) ──────────────────────────
RECIPE = dict(
    body_thr=0.5, hprs_thr=0.5, lprs_thr=0.5, vol_mult=1.2,
    rsi_long_lo=40, rsi_long_hi=65,
    rsi_short_lo=20, rsi_short_hi=40,
    vix_min=20.0, adx_max=35.0,
)

# Symbols that produced filtered trades in the dump
SYMBOLS = ["AMD", "AMZN", "BA", "COST", "GS", "HD", "INTC", "IWM", "META",
           "ORCL", "SPY", "TSLA", "XLF"]


# ── Indicator helpers (re-implemented locally to avoid coupling) ─────────────
def rsi14(close: pd.Series) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def adx14(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    down = -l.diff()
    plus_dm  = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    tr_n = pd.Series(tr).ewm(alpha=1/14, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / tr_n
    minus_di= 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / tr_n
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/14, adjust=False).mean()


def atr14_30m(df30: pd.DataFrame) -> pd.Series:
    h, l, c = df30["high"], df30["low"], df30["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/14, adjust=False).mean()


# ── Data loaders ─────────────────────────────────────────────────────────────
def load_15m(sym: str) -> pd.DataFrame | None:
    df = yf.download(sym, period="60d", interval="15m", progress=False, auto_adjust=True)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert("America/New_York")
    return df


def load_daily(sym: str) -> pd.DataFrame | None:
    df = yf.download(sym, period="400d", interval="1d", progress=False, auto_adjust=True)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    return df


def resample_30m(df15: pd.DataFrame) -> pd.DataFrame:
    return (df15.resample("30min", closed="left", label="left")
            .agg(open=("open","first"), high=("high","max"),
                 low=("low","min"), close=("close","last"),
                 volume=("volume","sum"))
            .dropna(subset=["open"]))


def slot_med_vol(df: pd.DataFrame) -> dict:
    out = {}
    for t in set(df.index.time):
        sub = df[df.index.time == t]
        if len(sub):
            out[t] = float(sub["volume"].median() or 1.0)
    return out


# ── Trade detection (matches round-1 logic) ──────────────────────────────────
def body(o, h, l, c):
    r = h - l
    return abs(c - o) / r if r > 1e-9 else 0.0


def cp(h, l, c):
    r = h - l
    return (c - l) / r if r > 1e-9 else 0.5


@dataclass
class Trade:
    sym: str; date: str; dir: str
    entry_ts: pd.Timestamp
    entry: float
    cat_stop_3pct: float
    cat_stop_1pct: float
    atr30: float


def find_trades_for(sym: str, df15: pd.DataFrame, df30: pd.DataFrame,
                    daily: pd.DataFrame, vix_by_day: dict) -> list[Trade]:
    daily = daily.copy()
    daily["rsi14"] = rsi14(daily["close"])
    daily["adx14"] = adx14(daily)
    slot_avg = slot_med_vol(df30)
    atr_30m = atr14_30m(df30)
    out: list[Trade] = []

    for day in sorted(set(df15.index.date)):
        df15_day = df15[df15.index.date == day].between_time("09:30", "15:59")
        df30_day = df30[df30.index.date == day].between_time("09:30", "15:59")
        if len(df15_day) < 5 or len(df30_day) < 2:
            continue
        c1 = df30_day.iloc[0]; c2 = df30_day.iloc[1]
        if c1.name.time().hour != 9 or c1.name.time().minute != 30:  continue
        if c2.name.time().hour != 10 or c2.name.time().minute != 0:   continue

        o1, h1, l1, cl1, v1 = [float(c1[k]) for k in ("open","high","low","close","volume")]
        o2, h2, l2, cl2     = [float(c2[k]) for k in ("open","high","low","close")]
        c1_body = body(o1, h1, l1, cl1) >= RECIPE["body_thr"]
        c2_body = body(o2, h2, l2, cl2) >= RECIPE["body_thr"]
        c1_cp   = cp(h1, l1, cl1)
        c1_hvol = v1 >= slot_avg.get(c1.name.time(), 0.0) * RECIPE["vol_mult"]

        bull = (cl1 > o1 and c1_body and c1_cp >= RECIPE["hprs_thr"] and c1_hvol
                and cl2 > o2 and c2_body)
        bear = (cl1 < o1 and c1_body and c1_cp <= RECIPE["lprs_thr"] and c1_hvol
                and cl2 < o2 and c2_body)
        if not (bull or bear):
            continue
        direction = "LONG" if bull else "SHORT"

        # Daily-context lookup for filter
        day_ts = pd.Timestamp(day)
        prev_idx = daily.index[daily.index < day_ts]
        if len(prev_idx) == 0:
            continue
        prev = daily.loc[prev_idx[-1]]
        rsi_v = float(prev["rsi14"]) if pd.notna(prev["rsi14"]) else None
        adx_v = float(prev["adx14"]) if pd.notna(prev["adx14"]) else None
        vix_v = vix_by_day.get(day, None)
        if rsi_v is None or adx_v is None or vix_v is None:
            continue

        # Apply the filter
        if vix_v < RECIPE["vix_min"]: continue
        if adx_v > RECIPE["adx_max"]: continue
        if direction == "LONG":
            if not (RECIPE["rsi_long_lo"] <= rsi_v <= RECIPE["rsi_long_hi"]): continue
        else:
            if not (RECIPE["rsi_short_lo"] <= rsi_v <= RECIPE["rsi_short_hi"]): continue

        entry_ts = c2.name
        entry    = cl2
        cat3     = entry * (1 - 0.03) if direction == "LONG" else entry * (1 + 0.03)
        cat1     = entry * (1 - 0.01) if direction == "LONG" else entry * (1 + 0.01)
        atr30v   = float(atr_30m.loc[atr_30m.index <= entry_ts].iloc[-1]) if len(atr_30m.loc[atr_30m.index <= entry_ts]) else 0.0
        out.append(Trade(sym, str(day), direction, entry_ts, entry, cat3, cat1, atr30v))
    return out


# ── Exit policies ────────────────────────────────────────────────────────────
def walk(trade: Trade, df15: pd.DataFrame, df30: pd.DataFrame,
         policy: str) -> tuple[float, str]:
    """Walk 15-min bars after entry through to 15:00 close, simulating exit."""
    post15 = df15[(df15.index > trade.entry_ts) &
                  (df15.index.time <= pd.Timestamp("15:59").time()) &
                  (df15.index.date == trade.entry_ts.date())]
    if post15.empty:
        return trade.entry, "no_data"

    sign = 1 if trade.dir == "LONG" else -1

    cat = trade.cat_stop_3pct if policy not in ("tight_cat", "tight_struct") else trade.cat_stop_1pct

    peak = trade.entry  # peak-favorable price reached
    trail = None  # current trail level
    activated = False  # for "post +XR" policies
    # R = 3% of entry. Activation thresholds & trail offsets per policy:
    #   pct_post_05r        : activate at +0.5R (1.5%), trail offset 0.5%
    #   pct_post_1r_loose   : activate at +1.0R (3.0%), trail offset 1.0%
    #   pct_post_15r_wide   : activate at +1.5R (4.5%), trail offset 1.5%
    activation_thr = {
        "pct_post_05r":     trade.entry * 0.015,
        "pct_post_1r_loose":  trade.entry * 0.030,
        "pct_post_15r_wide":  trade.entry * 0.045,
    }.get(policy, trade.entry * 0.015)
    trail_offset_pct = {
        "pct_immediate":     0.005,
        "pct_post_05r":       0.005,
        "pct_post_1r_loose":  0.010,
        "pct_post_15r_wide":  0.015,
    }.get(policy, 0.005)

    last_close = trade.entry
    exit_px = None
    exit_rsn = None

    # 30-min bar lookup for structural trail (last completed 30m bar's low/high)
    df30_post = df30[(df30.index > trade.entry_ts) &
                     (df30.index.time <= pd.Timestamp("15:59").time()) &
                     (df30.index.date == trade.entry_ts.date())]

    for ts, b in post15.iterrows():
        h, l, c = float(b["high"]), float(b["low"]), float(b["close"])

        # Update peak
        if trade.dir == "LONG":
            peak = max(peak, h)
        else:
            peak = min(peak, l)

        # Activate trail when policy needs it
        if policy in ("pct_post_05r", "pct_post_1r_loose", "pct_post_15r_wide"):
            if not activated:
                fav = (peak - trade.entry) * sign
                if fav >= activation_thr:
                    activated = True

        # Compute trail level for this bar
        new_trail = None
        if policy == "pct_immediate":
            new_trail = peak * (1 - trail_offset_pct) if trade.dir == "LONG" else peak * (1 + trail_offset_pct)
        elif policy in ("pct_post_05r", "pct_post_1r_loose", "pct_post_15r_wide") and activated:
            new_trail = peak * (1 - trail_offset_pct) if trade.dir == "LONG" else peak * (1 + trail_offset_pct)
        elif policy == "atr_trail":
            if trade.atr30 > 0:
                new_trail = peak - 1.0 * trade.atr30 if trade.dir == "LONG" else peak + 1.0 * trade.atr30
        elif policy in ("structural", "tight_struct"):
            # Trail to most recent COMPLETED 30m bar's low (long) or high (short)
            completed = df30_post[df30_post.index < ts]
            if len(completed):
                last30 = completed.iloc[-1]
                new_trail = float(last30["low"]) if trade.dir == "LONG" else float(last30["high"])

        if new_trail is not None:
            if trail is None:
                trail = new_trail
            elif trade.dir == "LONG":
                trail = max(trail, new_trail)  # only ratchet up
            else:
                trail = min(trail, new_trail)  # only ratchet down

        # Check exits in priority order: cat stop, then trail, then continue
        if trade.dir == "LONG":
            if l <= cat:
                exit_px, exit_rsn = cat, "cat_stop"; break
            if trail is not None and l <= trail:
                exit_px, exit_rsn = trail, "trail"; break
        else:
            if h >= cat:
                exit_px, exit_rsn = cat, "cat_stop"; break
            if trail is not None and h >= trail:
                exit_px, exit_rsn = trail, "trail"; break
        last_close = c

    if exit_px is None:
        exit_px, exit_rsn = float(post15.iloc[-1]["close"]), "eod"

    return exit_px, exit_rsn


def pnl_pct(trade: Trade, exit_px: float) -> float:
    raw = (exit_px - trade.entry) / trade.entry * 100
    return raw if trade.dir == "LONG" else -raw


# ── Reporting ────────────────────────────────────────────────────────────────
def summarize(trades: list[Trade], policy: str, df15_by_sym: dict,
              df30_by_sym: dict) -> dict:
    pnls = []
    reasons = {"cat_stop": 0, "trail": 0, "eod": 0, "no_data": 0}
    for t in trades:
        ex, rsn = walk(t, df15_by_sym[t.sym], df30_by_sym[t.sym], policy)
        pnls.append(pnl_pct(t, ex))
        reasons[rsn] = reasons.get(rsn, 0) + 1
    pnls = np.array(pnls)
    wins = pnls[pnls > 0].sum()
    losses = -pnls[pnls < 0].sum()
    pf = wins / losses if losses > 0 else float("inf")
    return dict(
        policy=policy, n=len(pnls),
        wr=float((pnls > 0).mean() * 100) if len(pnls) else float("nan"),
        pf=pf,
        avg=float(pnls.mean()) if len(pnls) else float("nan"),
        sum=float(pnls.sum()),
        cat=reasons["cat_stop"], trail=reasons["trail"], eod=reasons["eod"],
    )


def line(s: dict) -> None:
    print(f"  {s['policy']:<22} n={s['n']:3d}  WR={s['wr']:5.1f}%  PF={s['pf']:5.2f}  "
          f"avg={s['avg']:+.2f}%  sum={s['sum']:+6.2f}%  "
          f"[cat:{s['cat']:2d}  trail:{s['trail']:2d}  eod:{s['eod']:2d}]")


def main() -> None:
    print(f"Fetching 15m + daily data for {len(SYMBOLS)} symbols (+ ^VIX)...")
    df15_by_sym: dict = {}
    df30_by_sym: dict = {}
    daily_by_sym: dict = {}
    for s in SYMBOLS:
        d15 = load_15m(s)
        if d15 is None: continue
        df15_by_sym[s] = d15
        df30_by_sym[s] = resample_30m(d15)
        daily_by_sym[s] = load_daily(s)

    vix_daily = load_daily("^VIX")
    vix_by_day: dict = {ts.date(): float(row["close"])
                        for ts, row in vix_daily.iterrows()} if vix_daily is not None else {}

    # Find filtered trades
    trades: list[Trade] = []
    for s in SYMBOLS:
        if s not in df15_by_sym or daily_by_sym.get(s) is None:
            continue
        ts = find_trades_for(s, df15_by_sym[s], df30_by_sym[s], daily_by_sym[s], vix_by_day)
        trades.extend(ts)

    print(f"\nFiltered trades found: {len(trades)}")
    if not trades:
        return

    print("\n" + "=" * 92)
    print("  EXIT POLICY COMPARISON")
    print("=" * 92)
    for policy in ("baseline", "pct_post_05r",
                   "pct_post_1r_loose", "pct_post_15r_wide"):
        s = summarize(trades, policy, df15_by_sym, df30_by_sym)
        line(s)

    print("\nPolicy descriptions:")
    print("  baseline           : 3% cat stop + 15:00 EOD close (no trail)")
    print("  pct_post_05r       : 3% cat + 0.5% trail, activates at +0.5R (+1.5%)")
    print("  pct_post_1r_loose  : 3% cat + 1.0% trail, activates at +1.0R (+3.0%)")
    print("  pct_post_15r_wide  : 3% cat + 1.5% trail, activates at +1.5R (+4.5%)")


if __name__ == "__main__":
    main()
