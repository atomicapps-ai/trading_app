"""bt_intraday — same-day (day-trade) backtest harness for the INTRADAY lane.

The intraday analog of strategy_suite: it replays a real INTRADAY detector over the cached 30m
US-stock bars, session by session, with a same-day exit (stop / target / flat at the 15:00 ET
bar), and reports the same metric set (n / win% / expectancy-R / profit-factor, IS/OOS split, and
a random-direction control). Because it calls the actual app detector, its numbers ARE the in-app
numbers — this is the validation gate for day-trade candidates.

  python scripts/bt_intraday.py [--symbols N] [--detector intraday_reversion]

Data: data/historical/<SYM>_30m.csv (UTC), converted to ET and filtered to the regular session.
Trend context: <SYM>_1d.csv with indicators. Entry = next 30m open after a signal; exit within
the same session.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from datetime import time
from pathlib import Path
import numpy as np, pandas as pd, yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from strategy_suite import Trade, summarize, random_control  # noqa: E402
from agents.detectors import INTRADAY_DETECTORS              # noqa: E402
from services.indicator_service import add_indicators        # noqa: E402
from services.settings_service import STRATEGY_CONFIG_DIR     # noqa: E402

HIST = ROOT / "data" / "historical"
OUT = ROOT / "data" / "research" / "strategy_results"
OUT.mkdir(parents=True, exist_ok=True)
RTH_OPEN, RTH_CLOSE, FLAT = time(9, 30), time(16, 0), time(15, 0)
FX = {"EURUSD","USDJPY","EURJPY","GBPJPY","AUDJPY","EURAUD","EURCAD","GBPUSD","AUDUSD","XAUUSD"}


def _load_et(sym: str, interval: str) -> pd.DataFrame | None:
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


def stock_symbols() -> list[str]:
    out = []
    for p in HIST.glob("*_30m.csv"):
        s = p.name.replace("_30m.csv", "")
        if s not in FX and (HIST / f"{s}_1d.csv").exists():
            out.append(s)
    return sorted(out)


def _cfg(detector: str) -> dict:
    p = STRATEGY_CONFIG_DIR / f"{detector}.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


def run(symlist, detector="intraday_reversion"):
    fn = INTRADAY_DETECTORS[detector]
    cfg = _cfg(detector)
    trades = []
    for s in symlist:
        m30 = _load_et(s, "30m")
        daily = _load_et(s, "1d")
        if m30 is None or daily is None or len(m30) < 100 or len(daily) < 210:
            continue
        m30 = m30.between_time(RTH_OPEN, RTH_CLOSE, inclusive="left")
        daily = add_indicators(daily)
        d_dates = daily.index.tz_convert("America/New_York").date if daily.index.tz else daily.index.date
        for day, sess in m30.groupby(m30.index.date):
            if len(sess) < 5:
                continue
            prior = daily[d_dates < day]
            if len(prior) < 205:
                continue
            o = sess["open"].values; h = sess["high"].values; l = sess["low"].values; c = sess["close"].values
            times = [t.time() for t in sess.index]
            n = len(sess); entered = False
            for i in range(2, n - 1):
                r = fn(sess.iloc[:i+1], prior, None, cfg, as_of_ts=sess.index[i])
                if r is None:
                    continue
                entry = float(o[i+1]); stop = float(r.stop_price); tgt = float(r.tp2_price)
                risk = entry - stop
                if risk <= 0:
                    break
                rf = risk / entry
                if rf < 0.001:      # floor: skip unrealistically tiny stops (they blow up R)
                    break
                exitp = None
                for j in range(i+1, n):
                    if l[j] <= stop: exitp = stop; break
                    if h[j] >= tgt: exitp = tgt; break
                    if times[j] >= FLAT: exitp = float(c[j]); break   # flat by 15:00 ET
                if exitp is None: exitp = float(c[-1])                # session close fallback
                trades.append(Trade(sess.index[i], (exitp - entry) / risk, rf, +1))
                entered = True
                break   # one trade per session (scaffold)
    return trades


if __name__ == "__main__":
    cap = None; det = "intraday_reversion"
    if "--symbols" in sys.argv: cap = int(sys.argv[sys.argv.index("--symbols")+1])
    if "--detector" in sys.argv: det = sys.argv[sys.argv.index("--detector")+1]
    sl = stock_symbols()
    if cap: sl = sl[:cap]
    t = run(sl, det)
    res = {"detector": det, "n_symbols": len(sl), "results": {det: summarize(t, random_control(t))}}
    (OUT / f"intraday_{det}.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
