"""bt_intraday_families — validate the 4 intraday families (see strategy_docs/INTRADAY_STRATEGY_SPECS.md)
on the DEEP 20-year 1-min-derived bars, with fair per-symbol cost, IS/OOS split, and random control.

Families / strategies implemented:
  A (overnight/intraday split): A1 overnight_hold, A2 intraday_short, A3 overnight_conditional
  B (regime-conditioned):       B1 gapfade_highvol, B2 orb_trend_hvol
  C (opening range/first hour): C1 opening_conviction, C2 opening_double_lock, C3 orb_breakout
  D (time-of-day/last-hour):    D1 last_hour_momentum, D3 first30_to_last30, D4 power_hour_reversal

Trades are pooled across the symbol set, tagged by date; IS/OOS is a chronological half-split of the pool.
Each trade carries gross_r and net_r (fair per-symbol cost already subtracted). R units:
  no-stop strategies (A,D) -> R = 5% nominal notional;  C (3% cat stop) -> R = 3%.

  python scripts/bt_intraday_families.py [--symbols SPY QQQ ...] [--interval-c 30m] [--interval-d 5m]
Default symbol set = the 9 deep ETFs currently holding full 2005-2026 history.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import argparse, json, random, statistics, sys
from datetime import time
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import cost_model  # noqa: E402

random.seed(13)
HIST = ROOT / "data" / "historical"
OUT = ROOT / "data" / "research" / "strategy_results"; OUT.mkdir(parents=True, exist_ok=True)
RF = 0.05                       # nominal risk for no-stop strategies
CAT = 0.03                      # catastrophic stop for family C
DEEP_ETFS = ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI"]


# ---------- loaders ----------
def load_daily(sym: str) -> pd.DataFrame | None:
    f = HIST / f"{sym}_1d.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f); dc = df.columns[0]
    df[dc] = pd.to_datetime(df[dc], utc=True, errors="coerce")
    df = df.dropna(subset=[dc]).set_index(dc).sort_index()
    df.columns = [c.lower() for c in df.columns]
    return df


def load_intraday(sym: str, interval: str) -> pd.DataFrame | None:
    f = HIST / f"{sym}_{interval}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f); dc = df.columns[0]
    df[dc] = pd.to_datetime(df[dc], utc=True, errors="coerce")
    df = df.dropna(subset=[dc]).set_index(dc).sort_index()
    df.columns = [c.lower() for c in df.columns]
    return df.tz_convert("America/New_York").between_time(time(9, 30), time(16, 0), inclusive="left")


# ---------- family A: overnight vs intraday ----------
def run_A(sym, bucket):
    d = load_daily(sym)
    if d is None or len(d) < 220:
        return
    cbps = cost_model.roundtrip_frac(sym) * 1.5      # +auction premium
    o = d["open"].values.astype(float); c = d["close"].values.astype(float)
    dates = [x.tz_convert("America/New_York").date() for x in d.index]
    wd = [x.weekday() for x in dates]                 # 0=Mon
    ret = pd.Series(c).pct_change()
    rvpct = ret.rolling(20).std().rank(pct=True).values
    for i in range(1, len(c)):
        if o[i] <= 0 or c[i - 1] <= 0 or o[i - 1] <= 0:
            continue
        overnight = o[i] / c[i - 1] - 1.0
        intraday = c[i] / o[i] - 1.0
        prior_intraday = c[i - 1] / o[i - 1] - 1.0
        # A1 overnight hold (long close->open)
        g = overnight / RF
        bucket["A1_overnight_hold"].append((dates[i], g, g - cbps / RF))
        # A2 intraday short (falsification control)
        g = -intraday / RF
        bucket["A2_intraday_short"].append((dates[i], g, g - cbps / RF))
        # A3 conditional overnight: prior day down, low vol, not Fri->Mon
        if prior_intraday < 0 and not np.isnan(rvpct[i - 1]) and rvpct[i - 1] < 0.6 and wd[i] != 0:
            g = overnight / RF
            bucket["A3_overnight_conditional"].append((dates[i], g, g - cbps / RF))


# ---------- family D: time-of-day ----------
def run_D(sym, interval, bucket):
    m = load_intraday(sym, interval); d = load_daily(sym)
    if m is None or d is None or len(m) < 500:
        return
    cbps = cost_model.roundtrip_frac(sym)
    prior_close = {}
    dc = d["close"].values.astype(float)
    dd = [x.tz_convert("America/New_York").date() for x in d.index]
    for i in range(1, len(dd)):
        prior_close[dd[i]] = dc[i - 1]
    d4rows = []
    for day, sess in m.groupby(m.index.date):
        if len(sess) < 12:
            continue
        t = np.array([x.time() for x in sess.index])
        o = sess["open"].values.astype(float); c = sess["close"].values.astype(float)
        openp = o[0]; close = c[-1]
        if openp <= 0:
            continue
        before15 = t < time(15, 0); after15 = t >= time(15, 0)
        if not before15.any() or not after15.any():
            continue
        px1500 = c[before15][-1]
        day_ret = px1500 / openp - 1.0
        # D1 last-hour momentum
        if abs(day_ret) > 0.003:
            dirn = 1 if day_ret > 0 else -1
            g = dirn * (close / px1500 - 1.0) / RF
            bucket["D1_last_hour_momentum"].append((day, g, g - cbps / RF))
        # D3 first30 -> last30 (Gao), needs prior daily close
        first = t < time(10, 0); last = t >= time(15, 30)
        pc = prior_close.get(day)
        if first.any() and last.any() and pc and pc > 0:
            r1 = c[first][-1] / pc - 1.0
            if r1 != 0:
                dirn = 1 if r1 > 0 else -1
                entry = o[last][0]; exitp = c[last][-1]
                if entry > 0:
                    g = dirn * (exitp - entry) / entry / RF
                    bucket["D3_first30_to_last30"].append((day, g, g - cbps / RF))
        # D4 power-hour reversal (needs per-symbol |move| threshold -> collect then filter)
        before1530 = t < time(15, 30); after1530 = t >= time(15, 30)
        if before1530.any() and after1530.any():
            px1530 = c[before1530][-1]
            move = px1530 / openp - 1.0
            entry = o[after1530][0]; exitp = c[after1530][-1]
            if entry > 0:
                d4rows.append((day, abs(move), move, entry, exitp))
    if d4rows:
        thr = np.percentile([r[1] for r in d4rows], 66)   # top tercile |move|
        for day, amove, move, entry, exitp in d4rows:
            if amove >= thr and move != 0:
                dirn = -1 if move > 0 else 1               # REVERSE the day's move
                g = dirn * (exitp - entry) / entry / RF
                bucket["D4_power_hour_reversal"].append((day, g, g - cbps / RF))


# ---------- family C: opening range / first hour (30m bars) ----------
def _conviction(op, hi, lo, cl):
    rng = hi - lo
    if rng <= 0:
        return 0
    body = abs(cl - op); pos = (cl - lo) / rng
    strong = body >= 0.5 * rng
    if cl > op and strong and pos >= 0.6:
        return 1
    if cl < op and strong and pos <= 0.4:
        return -1
    return 0


def run_C(sym, interval, bucket):
    m = load_intraday(sym, interval); d = load_daily(sym)
    if m is None or d is None or len(m) < 500:
        return
    cbps = cost_model.roundtrip_frac(sym)
    # 20-day rolling median of the 09:30 bar volume (slot volume gate)
    slot_vol = {}
    b0 = m[m.index.time == time(9, 30)]
    if len(b0):
        sv = b0["volume"].rolling(20).median()
        slot_vol = {ts.date(): v for ts, v in sv.items()}
    for day, sess in m.groupby(m.index.date):
        if len(sess) < 6:
            continue
        t = np.array([x.time() for x in sess.index])
        o = sess["open"].values.astype(float); h = sess["high"].values.astype(float)
        l = sess["low"].values.astype(float); c = sess["close"].values.astype(float)
        v = sess["volume"].values.astype(float)
        close = c[-1]
        i0 = np.where(t == time(9, 30))[0]; i1 = np.where(t == time(10, 0))[0]
        if len(i0) == 0 or len(i1) == 0:
            continue
        i0 = i0[0]; i1 = i1[0]
        conv0 = _conviction(o[i0], h[i0], l[i0], c[i0])
        vgate = slot_vol.get(day)
        hvol0 = (vgate is None) or (v[i0] >= vgate)
        # entry price for a trade opening at 10:00 = open of the 10:00 bar
        entry1 = o[i1] if i1 < len(o) else None
        # C1 opening conviction (enter 10:00, exit EOD, 3% cat stop)
        if conv0 != 0 and hvol0 and entry1 and entry1 > 0:
            after = slice(i1, len(o))
            g = _eod_or_stop(conv0, entry1, h[after], l[after], close)
            bucket["C1_opening_conviction"].append((day, g, g - cbps / CAT))
        # C2 double lock (both 09:30 and 10:00 bars conviction same sign, enter 10:30)
        i2 = np.where(t == time(10, 30))[0]
        if len(i2):
            i2 = i2[0]
            conv1 = _conviction(o[i1], h[i1], l[i1], c[i1]) if i1 < len(o) else 0
            entry2 = o[i2] if i2 < len(o) else None
            if conv0 != 0 and conv0 == conv1 and entry2 and entry2 > 0:
                after = slice(i2, len(o))
                g = _eod_or_stop(conv0, entry2, h[after], l[after], close)
                bucket["C2_opening_double_lock"].append((day, g, g - cbps / CAT))
        # C3 ORB breakout of first 30-min range (target = range height, stop opposite edge, EOD)
        orh, orl = h[i0], l[i0]
        rng = orh - orl
        if rng > 0 and i1 < len(o):
            after = slice(i1, len(o))
            ha, la, ca = h[after], l[after], c[after]
            g = _orb_trade(orh, orl, rng, ha, la, ca)
            if g is not None:
                bucket["C3_orb_breakout"].append((day, g, g - cbps / (rng / ((orh + orl) / 2))))


def _eod_or_stop(direction, entry, highs, lows, close):
    """Long/short from entry, 3% cat stop, else exit at EOD close. Return R (R=3%)."""
    stop = entry * (1 - CAT) if direction == 1 else entry * (1 + CAT)
    if direction == 1:
        if lows.min() <= stop:
            return -1.0
        return (close - entry) / entry / CAT
    else:
        if highs.max() >= stop:
            return -1.0
        return (entry - close) / entry / CAT


def _orb_trade(orh, orl, rng, highs, lows, closes):
    """Stop-entry on first break of the opening range; target=range height, stop=opposite edge, EOD."""
    mid = (orh + orl) / 2
    for k in range(len(highs)):
        if highs[k] >= orh:                          # long breakout
            entry = orh; target = orh + rng; stop = orl
            for j in range(k, len(highs)):
                if lows[j] <= stop:
                    return (stop - entry) / (rng)     # R in range units
                if highs[j] >= target:
                    return (target - entry) / (rng)
            return (closes[-1] - entry) / rng
        if lows[k] <= orl:                            # short breakout
            entry = orl; target = orl - rng; stop = orh
            for j in range(k, len(lows)):
                if highs[j] >= stop:
                    return (entry - stop) / rng
                if lows[j] <= target:
                    return (entry - target) / rng
            return (entry - closes[-1]) / rng
    return None


# ---------- family B: regime-conditioned kernels ----------
def run_B(sym, interval, bucket):
    m = load_intraday(sym, interval); d = load_daily(sym)
    if m is None or d is None or len(d) < 220 or len(m) < 500:
        return
    cbps = cost_model.roundtrip_frac(sym)
    dc = d["close"].values.astype(float)
    dts = [x.tz_convert("America/New_York").date() for x in d.index]
    sma200 = pd.Series(dc).rolling(200).mean().values
    ret = pd.Series(dc).pct_change()
    rvpct = ret.rolling(20).std().rank(pct=True).values
    prior = {}
    for i in range(1, len(dts)):
        prior[dts[i]] = {"close": dc[i - 1], "sma200": sma200[i - 1], "rvpct": rvpct[i - 1]}
    slot_vol = {}
    b0 = m[m.index.time == time(9, 30)]
    if len(b0):
        sv = b0["volume"].rolling(20).median()
        slot_vol = {ts.date(): v for ts, v in sv.items()}
    for day, sess in m.groupby(m.index.date):
        pri = prior.get(day)
        if pri is None or np.isnan(pri["sma200"]):
            continue
        t = np.array([x.time() for x in sess.index])
        o = sess["open"].values.astype(float); h = sess["high"].values.astype(float)
        l = sess["low"].values.astype(float); c = sess["close"].values.astype(float)
        v = sess["volume"].values.astype(float); close = c[-1]
        openp = o[0]; pc = pri["close"]
        if openp <= 0 or pc <= 0:
            continue
        gap = openp / pc - 1.0
        uptrend = pc > pri["sma200"]
        highvol = (not np.isnan(pri["rvpct"])) and pri["rvpct"] >= 0.6
        # B1 gapfade_highvol: high vol + counter-trend gap 1-3%, fade toward prior close (target), EOD, stop 1.5x gap
        if highvol and 0.01 <= abs(gap) <= 0.03:
            counter = (gap < 0 and uptrend) or (gap > 0 and not uptrend)
            if counter:
                direction = 1 if gap < 0 else -1       # fade the gap
                risk = 0.015                            # ~1.5% stop
                g = _fade_trade(direction, openp, h, l, close, pc, risk)
                bucket["B1_gapfade_highvol"].append((day, g, g - cbps / risk))
        # B2 orb_trend_hvol: uptrend + opening volume >= slot median -> ORB long only
        i0 = np.where(t == time(9, 30))[0]; i1 = np.where(t == time(10, 0))[0]
        if uptrend and len(i0) and len(i1):
            i0i, i1i = i0[0], i1[0]
            vg = slot_vol.get(day)
            if (vg is None or v[i0i] >= vg) and i1i < len(o):
                orh, orl = h[i0i], l[i0i]; rng = orh - orl
                if rng > 0:
                    after = slice(i1i, len(o))
                    g = _orb_long_only(orh, rng, h[after], l[after], c[after])
                    if g is not None:
                        bucket["B2_orb_trend_hvol"].append((day, g, g - cbps / (rng / ((orh + orl) / 2))))


def _fade_trade(direction, entry, highs, lows, close, target_px, risk):
    stop = entry * (1 - risk) if direction == 1 else entry * (1 + risk)
    if direction == 1:
        if lows.min() <= stop:
            return -1.0
        if highs.max() >= target_px:
            return (target_px - entry) / entry / risk
        return (close - entry) / entry / risk
    else:
        if highs.max() >= stop:
            return -1.0
        if lows.min() <= target_px:
            return (entry - target_px) / entry / risk
        return (entry - close) / entry / risk


def _orb_long_only(orh, rng, highs, lows, closes):
    for k in range(len(highs)):
        if highs[k] >= orh:
            entry = orh; target = orh + rng; stop = orh - rng
            for j in range(k, len(highs)):
                if lows[j] <= stop:
                    return (stop - entry) / rng
                if highs[j] >= target:
                    return (target - entry) / rng
            return (closes[-1] - entry) / rng
    return None


# ---------- scoring ----------
def _stats(rs):
    if not rs:
        return {"n": 0}
    w = [x for x in rs if x > 0]; l = [x for x in rs if x <= 0]
    gp = sum(w); gl = -sum(l)
    return {"n": len(rs), "win": round(len(w) / len(rs) * 100, 1),
            "avgR": round(statistics.mean(rs), 4), "PF": round(gp / gl, 2) if gl > 0 else 0.0}


def summarize(trades):
    trades = sorted(trades, key=lambda x: x[0])
    gross = [t[1] for t in trades]; net = [t[2] for t in trades]
    mid = len(net) // 2
    ctrl = [x * random.choice([1, -1]) for x in gross]
    return {"n": len(net),
            "gross_all": _stats(gross), "net_all": _stats(net),
            "net_IS": _stats(net[:mid]), "net_OOS": _stats(net[mid:]),
            "control_OOS": _stats([x * random.choice([1, -1]) for x in net[mid:]])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--interval-c", default="30m")
    ap.add_argument("--interval-d", default="5m")
    ap.add_argument("--tag", default="deep_etfs")
    args = ap.parse_args()
    syms = args.symbols or DEEP_ETFS
    bucket: dict[str, list] = {k: [] for k in [
        "A1_overnight_hold", "A2_intraday_short", "A3_overnight_conditional",
        "B1_gapfade_highvol", "B2_orb_trend_hvol",
        "C1_opening_conviction", "C2_opening_double_lock", "C3_orb_breakout",
        "D1_last_hour_momentum", "D3_first30_to_last30", "D4_power_hour_reversal"]}
    used = []
    for s in syms:
        if not (HIST / f"{s}_1d.csv").exists():
            continue
        used.append(s)
        run_A(s, bucket)
        run_B(s, args.interval_c, bucket)
        run_C(s, args.interval_c, bucket)
        run_D(s, args.interval_d, bucket)
    out = {"tag": args.tag, "symbols": used, "results": {}}
    print(f"symbols({len(used)}): {used}\n")
    hdr = f"{'strategy':26} {'n':>6} {'grossPF':>7} {'netPF':>6} {'OOSnetPF':>8} {'OOSavgR':>8} {'ctrlPF':>6} {'win%':>5}"
    print(hdr); print("-" * len(hdr))
    for k, trades in bucket.items():
        s = summarize(trades)
        out["results"][k] = s
        if s["n"]:
            print(f"{k:26} {s['n']:>6} {s['gross_all']['PF']:>7} {s['net_all']['PF']:>6} "
                  f"{s['net_OOS']['PF']:>8} {s['net_OOS']['avgR']:>8} {s['control_OOS']['PF']:>6} {s['net_all']['win']:>5}")
    (OUT / f"intraday_families_{args.tag}.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {OUT / f'intraday_families_{args.tag}.json'}")


if __name__ == "__main__":
    main()
