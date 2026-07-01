"""find_fvg_example — detect a real 3-candle Fair Value Gap on EURUSD 5m during the NY
session, print its exact parameters, and render a labelled candlestick screenshot so the
FVG definition can be visually verified before we trust any detector.

3-candle bullish FVG: high[i-1] < low[i+1]  -> gap zone [high[i-1], low[i+1]], big green middle.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "data" / "historical"
OUT = Path("/sessions/relaxed-cool-faraday/mnt/outputs")
OUT.mkdir(parents=True, exist_ok=True)
PIP = 0.0001

def load(sym, iv):
    f = HIST / f"{sym.upper()}_{iv}.csv"
    d = pd.read_csv(f); dc = d.columns[0]
    d[dc] = pd.to_datetime(d[dc], utc=True, errors="coerce")
    d = d.dropna(subset=[dc]).set_index(dc).sort_index()
    d.columns = [c.lower() for c in d.columns]
    return d[["open", "high", "low", "close", "volume"]]

df = load("eurusd", "5m")
df = df[df.index >= pd.Timestamp("2024-06-01", tz="UTC")]   # recent slice = fast
o = df["open"].values; h = df["high"].values; l = df["low"].values; c = df["close"].values
body = np.abs(c - o)
mbody = pd.Series(body).rolling(20).mean().values
hour = df.index.hour.values
n = len(df)

# vectorized 3-candle bullish FVG: gap[i] = low[i+1] - high[i-1]
gap = np.full(n, -1.0); gap[1:-1] = l[2:] - h[:-2]
green_disp = (c > o) & (body >= 1.5 * mbody)
ny = (hour >= 13) & (hour < 21)
gp = gap / PIP
seq = np.zeros(n, bool); seq[1:-1] = (c[:-2] < c[1:-1]) & (c[1:-1] < c[2:])
ok = (gap > 0) & green_disp & ny & (gp >= 6) & (gp <= 25) & seq
idxs = np.where(ok)[0]
if len(idxs) == 0:
    sys.exit("no clean FVG found")
best = int(idxs[0])     # first clean example in the recent window

i = best
gap_lo, gap_hi = float(h[i - 1]), float(l[i + 1])
gap_pips = (gap_hi - gap_lo) / PIP
mid = (gap_lo + gap_hi) / 2

print("=== Bullish Fair Value Gap (EURUSD 5m, NY session) ===")
for k, lbl in [(i - 1, "candle-1 (pre)"), (i, "candle-2 (displacement)"), (i + 1, "candle-3 (post)")]:
    print(f"  {lbl:24s} {df.index[k]}  O={o[k]:.5f} H={h[k]:.5f} L={l[k]:.5f} C={c[k]:.5f}")
print(f"  --> FVG zone (gap): [{gap_lo:.5f}, {gap_hi:.5f}]   size={gap_pips:.1f} pips")
print(f"  --> 50% midline (consequent encroachment): {mid:.5f}")
print(f"  --> rule satisfied: candle1.high ({gap_lo:.5f}) < candle3.low ({gap_hi:.5f})  [TRUE]")
print(f"  --> middle body {body[i]/PIP:.1f} pips vs 20-bar avg {mbody[i]/PIP:.1f} pips (displacement)")

# ---- render ----
a, b = i - 10, i + 16
win = df.iloc[a:b]
fig, ax = plt.subplots(figsize=(13, 7))
x = mdates.date2num(win.index.to_pydatetime())
w = (x[1] - x[0]) * 0.6
for xi, (oo, hh, ll, cc) in zip(x, win[["open", "high", "low", "close"]].values):
    col = "#26a69a" if cc >= oo else "#ef5350"
    ax.plot([xi, xi], [ll, hh], color=col, lw=1, zorder=2)
    ax.add_patch(plt.Rectangle((xi - w / 2, min(oo, cc)), w, abs(cc - oo) or 1e-6,
                               facecolor=col, edgecolor=col, zorder=3))
# FVG zone shaded across to the right edge
ax.axhspan(gap_lo, gap_hi, xmin=(x[10] - x[0]) / (x[-1] - x[0]), xmax=1.0,
           facecolor="#f4d03f", alpha=0.30, zorder=1)
ax.axhline(mid, ls="--", lw=1, color="#b7950b", zorder=4)
for off, lab in [(-1, "1"), (0, "2 (displacement)"), (1, "3")]:
    xi = x[10 + off]
    ax.annotate(lab, (xi, win["high"].iloc[10 + off]), textcoords="offset points",
                xytext=(0, 8), ha="center", fontsize=10, color="white",
                bbox=dict(boxstyle="round,pad=0.2", fc="#333", ec="none"))
ax.text(x[-1], gap_hi, f"  FVG [{gap_lo:.5f}, {gap_hi:.5f}]  {gap_pips:.1f} pips",
        va="bottom", ha="right", color="#b7950b", fontsize=10, fontweight="bold")
ax.text(x[-1], mid, "  50% midline (entry)", va="bottom", ha="right", color="#b7950b", fontsize=9)
ax.set_title(f"Bullish Fair Value Gap — EURUSD 5m — {df.index[i]:%Y-%m-%d %H:%M} UTC (NY session)",
             color="white")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
ax.set_facecolor("#0e1117"); fig.patch.set_facecolor("#0e1117")
ax.tick_params(colors="white"); [s.set_color("#444") for s in ax.spines.values()]
ax.set_ylabel("EURUSD", color="white")
plt.tight_layout()
png = OUT / "fvg_eurusd_example.png"
plt.savefig(png, dpi=110, facecolor=fig.get_facecolor())
print(f"\nsaved chart: {png}")
