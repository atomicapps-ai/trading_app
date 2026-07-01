"""replay_fvg — replay engine for the FVG-Continuation (FX intraday) strategy.

Mirrors replay_swing/replay_dl's contract (returns SwingTrade objects the strategies
router renders) but runs the VALIDATED FVG displacement-continuation on FX 30m bars:
DST-correct ET sessions → NY bias (Asia ranges / London sweeps / NY reverses) → enter
the displacement FVG at MARKET (next bar open, realistic fill) → ride to 3R / stop / EOD.

Each trade's `notes` carries the FVG zone (FVG=bottom..top@mid) so the chart layer can
draw the gap as evidence (services/fvg_service.fvg_zone_from_notes parses it).

Public: async replay(symbols, since, until, strategy="fvg_continuation",
        refresh=False, ignore_regime=False) -> list[SwingTrade]
"""
from __future__ import annotations
from datetime import date
from pathlib import Path
import pandas as pd

from scripts.replay_swing import SwingTrade
from services.fvg_service import detect_fvgs

HIST = Path(__file__).resolve().parent.parent / "data" / "historical"

# FX pairs the strategy trades (FVG-continuation is FX; ignore any equity symbols passed in).
FX_PAIRS = ["EURUSD", "USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "EURAUD", "EURCAD", "GBPUSD", "AUDUSD"]


def _pip(sym: str) -> float:
    return 0.01 if sym.upper().endswith("JPY") else 0.0001


def _load_30m(sym: str) -> pd.DataFrame | None:
    f = HIST / f"{sym.upper()}_30m.csv"
    if not f.exists():
        return None
    d = pd.read_csv(f); dc = d.columns[0]
    d[dc] = pd.to_datetime(d[dc], utc=True, errors="coerce")
    d = d.dropna(subset=[dc]).set_index(dc).sort_index()
    d.columns = [c.lower() for c in d.columns]
    return d


def _run_pair(sym: str, since: date, until: date, tR: float = 3.0, disp: float = 1.5) -> list[SwingTrade]:
    d = _load_30m(sym)
    if d is None or len(d) < 300:
        return []
    PIP = _pip(sym); cost = 2 * PIP
    et = d.index.tz_convert("America/New_York"); eth = et.hour + et.minute / 60.0
    cyc = pd.DatetimeIndex([dt + pd.Timedelta(days=1) if h >= 19 else dt
                            for dt, h in zip(pd.DatetimeIndex(et.date), eth)])
    d = d.assign(eth=eth, cyc=cyc)
    out: list[SwingTrade] = []
    for cy, day in d.groupby("cyc"):
        cyd = cy.date() if hasattr(cy, "date") else cy
        if cyd < since or cyd > until:
            continue
        asia = day[day.eth >= 19]; london = day[(day.eth >= 2) & (day.eth < 7)]
        orb = day[(day.eth >= 9.5) & (day.eth < 9.75)]; ny = day[(day.eth >= 9.75) & (day.eth < 16)]
        if len(asia) < 2 or len(london) < 2 or len(orb) < 1 or len(ny) < 6:
            continue
        ah, al = asia["high"].max(), asia["low"].min()
        swept_hi = london["high"].max() > ah; swept_lo = london["low"].min() < al
        ldir = 1 if london["close"].iloc[-1] > london["open"].iloc[0] else -1
        bias = ldir if (swept_hi and swept_lo) else -ldir
        h = ny["high"].values; l = ny["low"].values; c = ny["close"].values; o = ny["open"].values
        ts = list(ny.index)
        orbh = orb["high"].max(); orbl = orb["low"].min()
        zs = detect_fvgs(ny, min_size=2 * PIP, disp_mult=disp)
        pos = {t: i for i, t in enumerate(ts)}
        done = False
        for z in zs:
            if done:
                break
            j = pos.get(pd.Timestamp(z.ts_formed))
            if j is None or j + 1 >= len(ny):
                continue
            d_ = 1 if z.direction == "bullish" else -1
            if (d_ == 1 and not c[j] > orbh) or (d_ == -1 and not c[j] < orbl) or d_ != bias:
                continue
            en = o[j + 1]; st = z.bottom if d_ == 1 else z.top
            rk = (en - st) if d_ == 1 else (st - en)
            if rk <= 0:
                continue
            tg = en + tR * rk if d_ == 1 else en - tR * rk
            R = None; xpx = c[-1]; reason = "EOD"
            for m in range(j + 1, len(ny)):
                if d_ == 1:
                    if l[m] <= st: R, xpx, reason = -1.0, st, "STOP"; break
                    if h[m] >= tg: R, xpx, reason = tR, tg, "TP_3R"; break
                else:
                    if h[m] >= st: R, xpx, reason = -1.0, st, "STOP"; break
                    if l[m] <= tg: R, xpx, reason = tR, tg, "TP_3R"; break
            if R is None:
                R = ((c[-1] - en) / rk) if d_ == 1 else ((en - c[-1]) / rk)
            pnl_pct = (xpx - en) / en * 100.0 if d_ == 1 else (en - xpx) / en * 100.0
            notes = (f"NY-bias {'LONG' if d_ == 1 else 'SHORT'} (London {'swept both' if (swept_hi and swept_lo) else 'reversal'}); "
                     f"displacement FVG, market entry next bar | FVG={z.bottom:.5f}..{z.top:.5f}@{z.mid:.5f}")
            out.append(SwingTrade(
                date_str=ts[j].date().isoformat(), symbol=sym.upper(),
                direction="long" if d_ == 1 else "short",
                entry=round(en, 5), stop=round(st, 5), tp=round(tg, 5),
                exit_px=round(xpx, 5), exit_reason=reason,
                pnl_pct=round(pnl_pct - (cost / en * 100.0), 3), win=R > 0,
                pqs=70, notes=notes, hold_days=0,
                pnl_dollars_per_100shr=round((xpx - en) * (100 if d_ == 1 else -100), 2),
            ))
            done = True
    return out


async def replay(symbols, since, until, strategy="fvg_continuation",
                 refresh=False, ignore_regime=False):
    if isinstance(since, str): since = date.fromisoformat(since)
    if isinstance(until, str): until = date.fromisoformat(until)
    trades: list[SwingTrade] = []
    for sym in FX_PAIRS:                      # FX strategy — uses FX pairs, not the equity universe
        trades += _run_pair(sym, since, until)
    trades.sort(key=lambda t: t.date_str)
    return trades


if __name__ == "__main__":
    import asyncio, sys
    since = sys.argv[1] if len(sys.argv) > 1 else "2025-01-01"
    until = sys.argv[2] if len(sys.argv) > 2 else "2026-06-26"
    tr = asyncio.run(replay([], since, until))
    wins = sum(1 for t in tr if t.win)
    print(f"fvg_continuation: {len(tr)} trades, win {wins/len(tr)*100:.1f}%" if tr else "0 trades")
    for t in tr[:6]:
        print(f"  {t.date_str} {t.symbol} {t.direction:5} entry {t.entry} stop {t.stop} exit {t.exit_px} {t.exit_reason:6} {t.pnl_pct:+.2f}% | {t.notes[-40:]}")
