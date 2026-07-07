"""bt_4hrange_fade — first-4H-range false-breakout fade, video O5eC5lY7ZXY.

Spec (both directions, FX 5-minute, NY session):
  * Mark the high/low of the **first 4-hour candle of the NY day** (00:00-04:00 ET ~ 04:00-08:00
    UTC). That is the range.
  * On the 5-minute chart, a candle must **close outside** the range (wicks don't count):
      - close above range_high -> arm a SHORT (failed-breakout fade)
      - close below range_low  -> arm a LONG
  * Then wait for price to **re-enter and close back inside** the range -> enter at that close.
  * Stop = the exact extreme of the breakout move (max high / min low during the excursion).
  * Target = 2 x stop distance (2R). Same-day only; multiple setups per day allowed.
  * strategy_suite rig (metrics/cost/control). FX pairs on 5m.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, Trade, summarize, random_control

FX = ["EURUSD","USDJPY","EURJPY","GBPJPY","AUDJPY","EURAUD","EURCAD","GBPUSD","AUDUSD","XAUUSD"]


def run(symlist, interval="5m"):
    trades = []
    for s in symlist:
        df = load(s, interval)
        if df is None or len(df) < 500:
            continue
        idx = df.index
        o = df["open"].values; c = df["close"].values; l = df["low"].values; h = df["high"].values
        # NY day key: shift UTC by -4h so NY midnight (04:00 UTC EDT) maps to 00:00
        ny = (idx - pd.Timedelta(hours=4))
        ny_day = ny.date
        hours = ny.hour  # hours since NY midnight
        n = len(df)
        # group indices by ny_day
        day_start = {}
        for i in range(n):
            day_start.setdefault(ny_day[i], []).append(i)
        for day, rows in day_start.items():
            # first 4H candle = NY hours 0..3
            first4 = [i for i in rows if hours[i] < 4]
            if len(first4) < 6:
                continue
            rhi = max(h[i] for i in first4); rlo = min(l[i] for i in first4)
            if rhi <= rlo:
                continue
            scan = [i for i in rows if hours[i] >= 4]
            armed = 0; extreme = None  # +1 armed-long(broke low), -1 armed-short(broke high)
            for i in scan:
                if i + 1 >= n:
                    break
                if armed == 0:
                    if c[i] > rhi:
                        armed = -1; extreme = h[i]
                    elif c[i] < rlo:
                        armed = +1; extreme = l[i]
                else:
                    if armed == -1:
                        extreme = max(extreme, h[i])
                        if c[i] < rhi:  # re-entered
                            entry = c[i]; stop = extreme; risk = stop - entry
                            if risk > 0:
                                tgt = entry - 2*risk; rf = risk/entry; exitp = None
                                for j in range(i+1, min(i+1+96, n)):
                                    if ny_day[j] != day: exitp = c[j]; break
                                    if h[j] >= stop: exitp = stop; break
                                    if l[j] <= tgt: exitp = tgt; break
                                if exitp is None: exitp = c[min(i+96, n-1)]
                                trades.append(Trade(idx[i], (entry-exitp)/risk, rf, -1))
                            armed = 0; extreme = None
                    else:  # armed long (broke low)
                        extreme = min(extreme, l[i])
                        if c[i] > rlo:
                            entry = c[i]; stop = extreme; risk = entry - stop
                            if risk > 0:
                                tgt = entry + 2*risk; rf = risk/entry; exitp = None
                                for j in range(i+1, min(i+1+96, n)):
                                    if ny_day[j] != day: exitp = c[j]; break
                                    if l[j] <= stop: exitp = stop; break
                                    if h[j] >= tgt: exitp = tgt; break
                                if exitp is None: exitp = c[min(i+96, n-1)]
                                trades.append(Trade(idx[i], (exitp-entry)/risk, rf, +1))
                            armed = 0; extreme = None
    return trades


if __name__ == "__main__":
    res = {"universe": "FX 10 pairs, 5m, first-NY-4H-range false-breakout fade", "results": {}}
    t = run(FX, "5m")
    res["results"]["fourhr_range_fade_5m"] = summarize(t, random_control(t))
    Path("data/research/strategy_results/fourhr_range_fade_video.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
