"""replay_swing — daily-swing backtest engine for the History/replay UI.

Mirrors scripts/replay_dl.py's contract (returns trade objects with the same
attribute names the strategies router maps) but simulates the DAILY swing
detectors (momentum_breakout / fear_dip_reversion) instead of the intraday
double_lock. Pure offline: reads the cached daily CSVs in data/historical and
runs the REAL detectors with their real config + filters, so the UI shows
exactly what the live strategy would have done.

Public: async replay(symbols, since, until, strategy, refresh=False, ignore_regime=False)
        -> list[SwingTrade]
"""
from __future__ import annotations
import copy
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import pandas as pd

from agents.analyst import load_strategy_config
from agents.detectors import ALL_DETECTORS
from services.indicator_service import add_indicators

HIST = Path(__file__).resolve().parent.parent / "data" / "historical"
_EMPTY = pd.DataFrame()


@dataclass
class SwingTrade:
    date_str: str
    symbol: str
    direction: str
    entry: float
    stop: float
    tp: float | None
    exit_px: float
    exit_reason: str
    pnl_pct: float
    win: bool
    pqs: int
    notes: str
    hold_days: int
    pnl_dollars_per_100shr: float


def _load_daily(sym: str) -> pd.DataFrame | None:
    f = HIST / f"{sym}_1d.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f); dc = df.columns[0]
    df[dc] = pd.to_datetime(df[dc], utc=True, errors="coerce")
    df = df.dropna(subset=[dc]).set_index(dc).sort_index()
    df.columns = [c.lower() for c in df.columns]
    return df


def _macro_by_date() -> dict:
    out = {}
    spy = _load_daily("SPY"); vix = _load_daily("^VIX")
    if spy is not None:
        c = spy["close"]; sma200 = c.rolling(200).mean(); ret20 = c.pct_change(20)
        vmap = {}
        if vix is not None:
            for i in range(len(vix)):
                vmap[vix.index[i].normalize()] = float(vix["close"].iloc[i])
        for i in range(len(spy)):
            k = spy.index[i].normalize()
            out[k] = {
                "spy_above_sma200": (bool(c.iloc[i] > sma200.iloc[i]) if sma200.iloc[i] == sma200.iloc[i] else None),
                "spy_trend_20d": (round(float(ret20.iloc[i]), 4) if ret20.iloc[i] == ret20.iloc[i] else None),
                "vix_level": vmap.get(k),
            }
    return out


def _simulate(pattern, ei, entry, stop, tp2, h, l, c, sma50, n):
    """Per-strategy forward exit. Returns (exit_px, reason, exit_index)."""
    if pattern == "macd_run":
        # let winners run: exit when MACD line crosses back below signal (or stop / 6R / time)
        cs = pd.Series(c)
        macd = cs.ewm(span=12, adjust=False).mean() - cs.ewm(span=26, adjust=False).mean()
        sig = macd.ewm(span=9, adjust=False).mean()
        horizon = min(ei + 120, n)
        for j in range(ei, horizon):
            if l[j] <= stop: return stop, "STOP", j
            if h[j] >= tp2: return tp2, "TP", j
            if j > ei and macd.iloc[j] < sig.iloc[j] and macd.iloc[j - 1] >= sig.iloc[j - 1]:
                return float(c[j]), "MACD_EXIT", j
        return float(c[horizon - 1]), "TIME", horizon - 1
    if pattern == "coil_breakout":
        # validated exit: stop at range low, 3R fixed target, 120-bar horizon
        tgt = entry + 3.0 * (entry - stop)
        horizon = min(ei + 120, n)
        for j in range(ei, horizon):
            if l[j] <= stop: return stop, "STOP", j
            if h[j] >= tgt: return tgt, "TP_3R", j
        return float(c[horizon - 1]), "TIME", horizon - 1
    if pattern == "s7_breakout_continuation":
        horizon = min(ei + 120, n)
        for j in range(ei, horizon):
            if l[j] <= stop: return stop, "STOP", j
            if h[j] >= tp2: return tp2, "TP", j
            if sma50[j] == sma50[j] and c[j] < sma50[j]: return float(c[j]), "TRAIL_50SMA", j
        return float(c[horizon - 1]), "TIME", horizon - 1
    # s5_mean_reversion: stop / target=mean(tp2) / time 45
    horizon = min(ei + 45, n)
    for j in range(ei, horizon):
        if l[j] <= stop: return stop, "STOP", j
        if h[j] >= tp2: return tp2, "TARGET", j
    return float(c[horizon - 1]), "TIME", horizon - 1


def _note(r) -> str:
    fl = [e.get("ref", "") for e in r.evidence_items if e.get("type") == "filter"]
    return " | ".join(fl)[:240]


async def replay(symbols, since, until, strategy="momentum_breakout",
                 refresh=False, ignore_regime=False):
    if isinstance(since, str): since = date.fromisoformat(since)
    if isinstance(until, str): until = date.fromisoformat(until)
    cfg = copy.deepcopy(load_strategy_config(strategy))
    if ignore_regime:  # research toggle — strip the selection filters
        pt = cfg.setdefault("pattern_thresholds", {})
        pt.setdefault("s7_breakout_continuation", {})["require_breakout_volume"] = False
        pt.setdefault("s5_mean_reversion", {})["require_fear_regime"] = False
    wl = set(cfg.get("detectors") or [])
    dets = [(nm, fn) for nm, fn in ALL_DETECTORS.items() if (not wl or nm in wl)]
    macro = _macro_by_date()

    trades: list[SwingTrade] = []
    for sym in symbols:
        df = _load_daily(sym)
        if df is None or len(df) < 210:
            continue
        dfi = add_indicators(df)
        idx = dfi.index; n = len(dfi)
        o = dfi["open"].values; h = dfi["high"].values; l = dfi["low"].values; c = dfi["close"].values
        sma50 = dfi["sma_50"].values if "sma_50" in dfi.columns else pd.Series(c).rolling(50).mean().values
        i = 0
        while i < n and idx[i].date() < since: i += 1
        while i < n - 1 and idx[i].date() <= until:
            d = idx[i]; mc = macro.get(d.normalize(), {})
            sub = dfi.iloc[:i + 1]
            fired = None
            for nm, fn in dets:
                try:
                    r = fn(sub, _EMPTY, cfg, d, macro_context=mc)
                except Exception:
                    r = None
                if r is not None:
                    fired = (nm, r); break
            if fired:
                nm, r = fired; ei = i + 1
                entry = float(o[ei]); stop = float(r.stop_price)
                tp1 = float(r.tp1_price); tp2 = float(r.tp2_price)
                exit_px, reason, xj = _simulate(nm, ei, entry, stop, tp2, h, l, c, sma50, n)
                pnl = (exit_px - entry) / entry * 100.0 if entry else 0.0
                trades.append(SwingTrade(
                    date_str=d.date().isoformat(), symbol=sym, direction="long",
                    entry=round(entry, 2), stop=round(stop, 2), tp=round(tp1, 2),
                    exit_px=round(exit_px, 2), exit_reason=reason,
                    pnl_pct=round(pnl, 2), win=pnl > 0, pqs=r.pqs_total,
                    notes=_note(r), hold_days=xj - ei,
                    pnl_dollars_per_100shr=round((exit_px - entry) * 100, 2),
                ))
                i = xj + 1; continue
            i += 1
    return trades


if __name__ == "__main__":
    import asyncio, sys
    strat = sys.argv[1] if len(sys.argv) > 1 else "momentum_breakout"
    since = sys.argv[2] if len(sys.argv) > 2 else "2022-01-01"
    until = sys.argv[3] if len(sys.argv) > 3 else "2024-12-31"
    syms = ["AAPL", "NVDA", "MSFT", "JPM", "XOM", "WMT", "AMD", "META"]
    tr = asyncio.run(replay(syms, since, until, strat))
    wins = sum(1 for t in tr if t.win)
    print(f"{strat}: {len(tr)} trades, win {wins/len(tr)*100:.1f}%" if tr else f"{strat}: 0 trades")
    for t in tr[:6]:
        print(f"  {t.date_str} {t.symbol:5} entry {t.entry} stop {t.stop} exit {t.exit_px} {t.exit_reason:11} pnl {t.pnl_pct:+.2f}% pqs {t.pqs} hold {t.hold_days}d")
        if t.notes: print(f"       filter: {t.notes}")
