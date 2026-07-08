"""bt_intraday_research — sweep multiple intraday day-trade kernels on 30m US-stock bars.

The intraday analog of strategy_suite's multi-strategy rig. Each kernel is an inline function that
scans a session and returns Trades; every trade opens and closes the SAME day (stop / target /
flat at 15:00 ET). Reports n / win% / expectancy-R / profit-factor with a chronological IS/OOS
split and a random-direction control, per kernel + variant.

  python scripts/bt_intraday_research.py [--symbols N]

Winners (OOS PF >= 1.2, avg-R > 0, >= ~100 trades, beats control) get promoted to real detectors.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from datetime import time
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from strategy_suite import Trade, summarize, random_control  # noqa: E402

HIST = ROOT / "data" / "historical"
OUT = ROOT / "data" / "research" / "strategy_results"
OUT.mkdir(parents=True, exist_ok=True)
RTH_OPEN, RTH_CLOSE, FLAT = time(9, 30), time(16, 0), time(15, 0)
MIN_RF = 0.001   # floor: skip unrealistically tiny stops (they blow up R)
FX = {"EURUSD","USDJPY","EURJPY","GBPJPY","AUDJPY","EURAUD","EURCAD","GBPUSD","AUDUSD","XAUUSD"}


def _load_et(sym, interval):
    f = HIST / f"{sym}_{interval}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f); dc = df.columns[0]
    df[dc] = pd.to_datetime(df[dc], utc=True, errors="coerce")
    df = df.dropna(subset=[dc]).set_index(dc).sort_index()
    df.columns = [c.lower() for c in df.columns]
    if interval != "1d":
        df = df.tz_convert("America/New_York")
    return df


def stock_symbols():
    out = []
    for p in HIST.glob("*_30m.csv"):
        s = p.name.replace("_30m.csv", "")
        if s not in FX and (HIST / f"{s}_1d.csv").exists():
            out.append(s)
    return sorted(out)


def _rsi(c, n=2):
    d = pd.Series(c).diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d).clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100/(1 + up/dn.replace(0, np.nan))).fillna(50).values


def _exit(o, h, l, c, times, i, entry, stop, tgt, direction=1):
    """Simulate a same-day exit from entry (open of bar i) — stop / target / 15:00 flat."""
    n = len(c)
    for j in range(i, n):
        if direction == 1:
            if l[j] <= stop: return stop, "STOP"
            if h[j] >= tgt: return tgt, "TARGET"
        else:
            if h[j] >= stop: return stop, "STOP"
            if l[j] <= tgt: return tgt, "TARGET"
        if times[j] >= FLAT: return float(c[j]), "EOD"
    return float(c[-1]), "EOD"


def _sess_arrays(sess):
    o = sess["open"].values.astype(float); h = sess["high"].values.astype(float)
    l = sess["low"].values.astype(float); c = sess["close"].values.astype(float)
    v = sess["volume"].values.astype(float)
    times = [t.time() for t in sess.index]
    tp = (h + l + c) / 3.0
    cum_pv = np.cumsum(tp * np.where(v > 0, v, np.nan))
    cum_v = np.cumsum(np.where(v > 0, v, np.nan))
    vwap = cum_pv / cum_v
    vwap = pd.Series(vwap).ffill().values
    return o, h, l, c, v, times, vwap


# ---------------------------------------------------------------- kernels
# Each: kernel(sess, prior) -> list[Trade].  prior = {"close":..,"sma200":..,"atrpct":..}
# Long-biased mean-reversion unless noted. Entry = next bar open; one trade/session.
# Mean-reversion stops are WIDE (a fraction of the stock's DAILY ATR) so intraday noise doesn't
# stop you before the VWAP magnet / EOD; a time gate keeps runway to flatten by 15:00.

AFTER, BEFORE = time(10, 30), time(14, 0)   # enter only in this window


def _wide_stop(entry, prior, mult):
    ap = prior.get("atrpct") or 0.02
    return entry * (1 - mult * ap)


def k_vwap_revert(sess, prior, stretch=0.7, stop_mult=0.6, trend=True):
    o, h, l, c, v, times, vwap = _sess_arrays(sess)
    n = len(c)
    if trend and not (prior["sma200"] and prior["close"] > prior["sma200"]):
        return []
    for i in range(2, n - 1):
        if not (AFTER <= times[i] <= BEFORE) or vwap[i] <= 0 or np.isnan(vwap[i]):
            continue
        if (vwap[i] - c[i]) / vwap[i] * 100 >= stretch and c[i] < vwap[i]:
            entry = o[i+1]; stop = _wide_stop(entry, prior, stop_mult); risk = entry - stop
            if risk <= 0 or risk/entry < MIN_RF:
                return []
            tgt = vwap[i]
            if tgt <= entry:
                return []
            ex, _ = _exit(o, h, l, c, times, i+1, entry, stop, tgt, 1)
            return [Trade(sess.index[i], (ex-entry)/risk, risk/entry, 1)]
    return []


def k_rsi2_bounce(sess, prior, lo=10.0, stop_mult=0.6, trend=True):
    o, h, l, c, v, times, vwap = _sess_arrays(sess)
    n = len(c); r = _rsi(c, 2)
    if trend and not (prior["sma200"] and prior["close"] > prior["sma200"]):
        return []
    for i in range(2, n - 1):
        if not (AFTER <= times[i] <= BEFORE):
            continue
        if r[i] < lo and c[i] < vwap[i]:
            entry = o[i+1]; stop = _wide_stop(entry, prior, stop_mult); risk = entry - stop
            if risk <= 0 or risk/entry < MIN_RF:
                return []
            tgt = vwap[i] if vwap[i] > entry else entry * 1.005
            ex, _ = _exit(o, h, l, c, times, i+1, entry, stop, tgt, 1)
            return [Trade(sess.index[i], (ex-entry)/risk, risk/entry, 1)]
    return []


def k_gap_fill(sess, prior, min_gap=0.5, max_gap=4.0, stop_mult=0.6,
               target_frac=1.0, trend=False):
    """Fade a morning gap DOWN back toward the prior close (long).
    target_frac = fraction of the gap to target (1.0 = full prior close; 0.5 = halfway)."""
    o, h, l, c, v, times, vwap = _sess_arrays(sess)
    n = len(c)
    if not prior["close"]:
        return []
    if trend and not (prior["sma200"] and prior["close"] > prior["sma200"]):
        return []
    gap = (prior["close"] - o[0]) / prior["close"] * 100      # >0 = gapped down
    if not (min_gap <= gap <= max_gap):
        return []
    for i in range(0, min(2, n - 1)):
        if c[i] < prior["close"]:
            entry = o[i+1]; stop = _wide_stop(entry, prior, stop_mult); risk = entry - stop
            if risk <= 0 or risk/entry < MIN_RF:
                return []
            tgt = entry + target_frac * (prior["close"] - entry)
            if tgt <= entry:
                return []
            ex, _ = _exit(o, h, l, c, times, i+1, entry, stop, tgt, 1)
            return [Trade(sess.index[i], (ex-entry)/risk, risk/entry, 1)]
    return []


def k_orb_fade(sess, prior, or_bars=2):
    """Failed breakdown of the opening range -> long back into the range (mean-rev)."""
    o, h, l, c, v, times, vwap = _sess_arrays(sess)
    n = len(c)
    if n < or_bars + 3:
        return []
    or_lo = min(l[:or_bars]); or_hi = max(h[:or_bars])
    broke = False
    for i in range(or_bars, n - 1):
        if c[i] < or_lo:
            broke = True; ext = min(l[or_bars:i+1])
        elif broke and c[i] > or_lo:                    # re-entered the range
            entry = o[i+1]; stop = ext * 0.999; risk = entry - stop
            if risk <= 0 or risk/entry < MIN_RF:
                return []
            tgt = or_hi
            if tgt <= entry:
                return []
            ex, _ = _exit(o, h, l, c, times, i+1, entry, stop, tgt, 1)
            return [Trade(sess.index[i], (ex-entry)/risk, risk/entry, 1)]
    return []


def k_orb_breakout(sess, prior, or_bars=2, trend=True):
    """Momentum contrast: break ABOVE the opening range, target = range height, EOD."""
    o, h, l, c, v, times, vwap = _sess_arrays(sess)
    n = len(c)
    if n < or_bars + 3:
        return []
    if trend and not (prior["sma200"] and prior["close"] > prior["sma200"]):
        return []
    or_lo = min(l[:or_bars]); or_hi = max(h[:or_bars]); rng = or_hi - or_lo
    if rng <= 0:
        return []
    for i in range(or_bars, n - 1):
        if c[i] > or_hi:
            entry = o[i+1]; stop = or_lo; risk = entry - stop
            if risk <= 0 or risk/entry < MIN_RF:
                return []
            tgt = entry + rng
            ex, _ = _exit(o, h, l, c, times, i+1, entry, stop, tgt, 1)
            return [Trade(sess.index[i], (ex-entry)/risk, risk/entry, 1)]
    return []


KERNELS = {
    "vwap_revert_base": lambda s, p: k_vwap_revert(s, p, 0.7, 0.6, True),
    "gap_fade_1_3_full": lambda s, p: k_gap_fill(s, p, 1.0, 3.0, 0.6, 1.0, False),
    "gap_fade_1_3_half": lambda s, p: k_gap_fill(s, p, 1.0, 3.0, 0.6, 0.5, False),
    "gap_fade_1_3_full_trend": lambda s, p: k_gap_fill(s, p, 1.0, 3.0, 0.6, 1.0, True),
    "gap_fade_1_3_half_trend": lambda s, p: k_gap_fill(s, p, 1.0, 3.0, 0.6, 0.5, True),
    "gap_fade_05_2_half": lambda s, p: k_gap_fill(s, p, 0.5, 2.0, 0.6, 0.5, False),
    "gap_fade_2_5_full": lambda s, p: k_gap_fill(s, p, 2.0, 5.0, 0.6, 1.0, False),
}


def run(symlist):
    books = {k: [] for k in KERNELS}
    for s in symlist:
        m30 = _load_et(s, "30m"); daily = _load_et(s, "1d")
        if m30 is None or daily is None or len(m30) < 100 or len(daily) < 210:
            continue
        m30 = m30.between_time(RTH_OPEN, RTH_CLOSE, inclusive="left")
        dc = daily["close"].values.astype(float)
        dh = daily["high"].values.astype(float); dl = daily["low"].values.astype(float)
        sma200 = pd.Series(dc).rolling(200).mean().values
        pc = np.roll(dc, 1); pc[0] = dc[0]
        tr = np.maximum(dh - dl, np.maximum(np.abs(dh - pc), np.abs(dl - pc)))
        atr14 = pd.Series(tr).rolling(14).mean().values
        atrpct = atr14 / dc
        d_dates = (daily.index.date)
        prior_close = {}; prior_sma = {}
        for i in range(len(daily)):
            prior_close[d_dates[i]] = dc[i]; prior_sma[d_dates[i]] = sma200[i]
        d_list = list(d_dates)
        for day, sess in m30.groupby(m30.index.date):
            if len(sess) < 5:
                continue
            # prior trading day's daily row
            idx = np.searchsorted(d_list, day) - 1
            if idx < 205:
                continue
            prior = {"close": dc[idx], "sma200": sma200[idx],
                     "atrpct": (atrpct[idx] if not np.isnan(atrpct[idx]) else 0.02)}
            if np.isnan(prior["sma200"]):
                continue
            for k, fn in KERNELS.items():
                try:
                    books[k].extend(fn(sess, prior))
                except Exception:
                    pass
    return books


if __name__ == "__main__":
    cap = 120
    if "--symbols" in sys.argv:
        cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = stock_symbols()[:cap]
    books = run(sl)
    out = {"n_symbols": len(sl), "results": {}}
    for k, trades in books.items():
        out["results"][k] = summarize(trades, random_control(trades))
    (OUT / "intraday_research.json").write_text(json.dumps(out, indent=2, default=str))
    def _gross_pf(trades):
        rs = [t.r for t in trades]                      # GROSS R (no cost)
        g = sum(x for x in rs if x > 0); ln = -sum(x for x in rs if x <= 0)
        return round(g / ln, 2) if ln > 0 else float("inf")

    print(f"symbols={len(sl)}\n")
    for k, v in out["results"].items():
        a = v["all"]; oo = v.get("out_sample", {}); rc = v.get("random_control", {})
        if a.get("n", 0) == 0:
            print(f"{k:24} n=0"); continue
        print(f"{k:24} n={a['n']:6} winALL={a['win_pct']}%  OOS PF={oo.get('profit_factor')} "
              f"avgR={oo.get('expectancy_R')}  IS_PF={v['in_sample'].get('profit_factor')}  "
              f"ctrlPF={rc.get('profit_factor')}  GROSS_PF(all)={_gross_pf(books[k])}")
