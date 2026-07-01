"""chart_fvg_trade — render an FVG-Continuation trade as an annotated chart (evidence).

Draws the NY-session window with: the displacement Fair-Value-Gap shaded, the market
entry (next bar after the gap), stop (far gap edge), and the 3R target — so each FVG
trade can be shown as a picture for review, not just a table row.

Run:  python -m scripts.chart_fvg_trade [PAIR] [--date YYYY-MM-DD] [--out PATH]
Defaults to the most recent qualifying setup for the pair (EURUSD).
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.dates as mdates

from services.fvg_service import detect_fvgs

HIST = Path(__file__).resolve().parent.parent / "data" / "historical"


def _pip(s): return 0.01 if s.upper().endswith("JPY") else 0.0001


def _load(sym):
    d = pd.read_csv(HIST / f"{sym.upper()}_30m.csv"); dc = d.columns[0]
    d[dc] = pd.to_datetime(d[dc], utc=True, errors="coerce")
    d = d.dropna(subset=[dc]).set_index(dc).sort_index(); d.columns = [c.lower() for c in d.columns]
    return d


def _find(sym, want_date=None, disp=1.5):
    d = _load(sym); PIP = _pip(sym)
    et = d.index.tz_convert("America/New_York"); eth = et.hour + et.minute / 60.0
    cyc = pd.DatetimeIndex([dt + pd.Timedelta(days=1) if h >= 19 else dt for dt, h in zip(pd.DatetimeIndex(et.date), eth)])
    d = d.assign(eth=eth, cyc=cyc)
    found = None
    for cy, day in d.groupby("cyc"):
        if want_date and str(cy.date()) != want_date:
            continue
        asia = day[day.eth >= 19]; london = day[(day.eth >= 2) & (day.eth < 7)]
        orb = day[(day.eth >= 9.5) & (day.eth < 9.75)]; ny = day[(day.eth >= 9.75) & (day.eth < 16)]
        if len(asia) < 2 or len(london) < 2 or len(orb) < 1 or len(ny) < 6:
            continue
        ah, al = asia["high"].max(), asia["low"].min()
        sh = london["high"].max() > ah; sl = london["low"].min() < al
        ldir = 1 if london["close"].iloc[-1] > london["open"].iloc[0] else -1
        bias = ldir if (sh and sl) else -ldir
        h = ny["high"].values; l = ny["low"].values; c = ny["close"].values; o = ny["open"].values; ts = list(ny.index)
        orbh = orb["high"].max(); orbl = orb["low"].min()
        zs = detect_fvgs(ny, min_size=2 * PIP, disp_mult=disp); pos = {t: i for i, t in enumerate(ts)}
        for z in zs:
            j = pos.get(pd.Timestamp(z.ts_formed))
            if j is None or j + 1 >= len(ny): continue
            d_ = 1 if z.direction == "bullish" else -1
            if (d_ == 1 and not c[j] > orbh) or (d_ == -1 and not c[j] < orbl) or d_ != bias: continue
            found = (cy, ny, j, z, d_, bias)
            break
    return found, _pip(sym)


def render(sym="EURUSD", want_date=None, out=None):
    res, PIP = _find(sym, want_date)
    if res is None:
        print("no FVG-continuation setup found"); return None
    cy, ny, j, z, d_, bias = res
    o = ny["open"].values; h = ny["high"].values; l = ny["low"].values; c = ny["close"].values; ts = list(ny.index)
    en = o[j + 1]; st = z.bottom if d_ == 1 else z.top
    rk = (en - st) if d_ == 1 else (st - en); tg = en + 3 * rk if d_ == 1 else en - 3 * rk
    a = max(0, j - 5); b = min(len(ny), j + 16); win = ny.iloc[a:b]
    fig, ax = plt.subplots(figsize=(13, 7))
    x = mdates.date2num(win.index.to_pydatetime()); w = (x[1] - x[0]) * 0.6
    for xi, (oo, hh, ll, cc) in zip(x, win[["open", "high", "low", "close"]].values):
        col = "#26a69a" if cc >= oo else "#ef5350"
        ax.plot([xi, xi], [ll, hh], color=col, lw=1, zorder=2)
        ax.add_patch(plt.Rectangle((xi - w / 2, min(oo, cc)), w, abs(cc - oo) or 1e-6, facecolor=col, edgecolor=col, zorder=3))
    ax.axhspan(z.bottom, z.top, facecolor=("#26a69a" if d_ == 1 else "#ef5350"), alpha=0.18, zorder=1)
    xent = x[(j + 1) - a]; word = "LONG" if d_ == 1 else "SHORT"
    ax.annotate(f"ENTER {word}\n(next bar, market)", (xent, en),
                xytext=(xent, en + (z.top - z.bottom) * (2.4 if d_ == 1 else -3.0)),
                ha="center", color="#fff", fontsize=10, fontweight="bold",
                arrowprops=dict(color="#fff", arrowstyle="->", lw=2))
    for y, lab, col in [(st, "STOP (far gap edge)", "#ef5350"), (en, "ENTRY", "#fff"), (tg, "TARGET 3R", "#26a69a")]:
        ax.axhline(y, ls="--", lw=1.2, color=col, zorder=4)
        ax.text(x[-1], y, f"  {lab}", va="center", color=col, fontsize=9, fontweight="bold")
    ax.annotate("FVG (displacement)", (x[j - a], z.top if d_ == 1 else z.bottom),
                xytext=(x[j - a], (z.top if d_ == 1 else z.bottom) + (z.top - z.bottom) * (3 if d_ == 1 else -3)),
                ha="center", color="#ffd54f", fontsize=9, arrowprops=dict(color="#ffd54f", arrowstyle="->"))
    ax.set_title(f"FVG-Continuation {word} — {sym.upper()} 30m — {cy.date()} NY session (bias {'long' if bias==1 else 'short'})", color="white")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M")); plt.xticks(rotation=20)
    ax.set_facecolor("#0e1117"); fig.patch.set_facecolor("#0e1117"); ax.tick_params(colors="white")
    [s.set_color("#444") for s in ax.spines.values()]
    plt.tight_layout()
    out = out or f"/sessions/relaxed-cool-faraday/mnt/trading_app/fvg_trade_{sym.upper()}_{cy.date()}.png"
    plt.savefig(out, dpi=110, facecolor=fig.get_facecolor())
    print(f"saved {out} | {word} {sym.upper()} {cy.date()} entry {en:.5f} stop {st:.5f} target {tg:.5f}")
    return out


if __name__ == "__main__":
    pair = next((a for a in sys.argv[1:] if not a.startswith("--")), "EURUSD")
    wd = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else None
    render(pair, wd)
