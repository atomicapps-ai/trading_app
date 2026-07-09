"""render_backtest_images — turn a backtest trade ledger into per-trade PNG chart images.

Renders each trade as a candlestick chart (with the strategy's entry / stop / target levels, and an
opening-range box if present), sorted into winners/ and losers/ folders, plus a manifest.json the app's
Backtest Review can read. Works for intraday (1-min parquet) or swing (daily CSV) ledgers.

Output: data/backtest_images/<strategy>/{winners,losers}/<SYM>__<date>__<dir>__<WIN|LOSS>__<R>.png
        data/backtest_images/<strategy>/manifest.json

  python scripts/render_backtest_images.py --strategy one_box_scalper \
      --ledger data/research/strategy_results/one_box_scalper_ledger.json \
      --interval 1m --max-per-side 40
"""
from __future__ import annotations
import argparse, json
from datetime import time
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parent.parent
SRC_1M = ROOT / "data" / "historical_1m"
HIST = ROOT / "data" / "historical"
IMG_ROOT = ROOT / "data" / "backtest_images"
_CACHE: dict[str, pd.DataFrame | None] = {}
_INTRADAY = {"1m", "5m", "15m", "30m", "1h", "60min"}


def _load(sym: str, interval: str) -> pd.DataFrame | None:
    key = f"{sym}:{interval}"
    if key in _CACHE:
        return _CACHE[key]
    if interval == "1m":
        p = SRC_1M / f"{sym}.parquet"
        if not p.exists():
            _CACHE[key] = None; return None
        df = pd.read_parquet(p)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df = df.tz_convert("America/New_York")
    else:
        f = HIST / f"{sym}_{interval}.csv"
        if not f.exists():
            _CACHE[key] = None; return None
        df = pd.read_csv(f); dc = df.columns[0]
        df[dc] = pd.to_datetime(df[dc], utc=True, errors="coerce")
        df = df.dropna(subset=[dc]).set_index(dc).sort_index()
        df.columns = [c.lower() for c in df.columns]
        if interval in _INTRADAY:      # intraday CSVs are UTC -> convert to ET (daily left as-is)
            df = df.tz_convert("America/New_York")
    df["_d"] = df.index.date
    _CACHE[key] = df
    return df


_INTRADAY = {"1m", "5m", "15m", "30m", "1h", "60min"}


def _window(sym, date, interval, pad_days):
    df = _load(sym, interval)
    if df is None:
        return None
    d = pd.Timestamp(date).date()
    if interval in _INTRADAY:
        # render the trade's own session (RTH), not a multi-day window
        s = df[df["_d"] == d].between_time(time(9, 30), time(16, 0), inclusive="left")
        return s if len(s) else None
    dates = sorted(set(df["_d"]))
    if d not in dates:
        return None
    i = dates.index(d)
    lo = dates[max(0, i - pad_days)]; hi = dates[min(len(dates) - 1, i + pad_days)]
    return df[(df["_d"] >= lo) & (df["_d"] <= hi)]


def _draw(t, bars, out_path, interval):
    o = bars["open"].values; h = bars["high"].values; l = bars["low"].values; c = bars["close"].values
    n = len(bars)
    fig, ax = plt.subplots(figsize=(5.2, 3.0), dpi=110)
    fig.patch.set_facecolor("#0d1117"); ax.set_facecolor("#0d1117")
    for i in range(n):
        up = c[i] >= o[i]; col = "#3fb950" if up else "#f85149"
        ax.plot([i, i], [l[i], h[i]], color=col, linewidth=0.6, zorder=2)
        ax.add_patch(Rectangle((i - 0.3, min(o[i], c[i])), 0.6, max(abs(c[i] - o[i]), 1e-9),
                               facecolor=col, edgecolor=col, zorder=3))
    # opening-range box (intraday) spanning the whole window
    if t.get("box_high") is not None and t.get("box_low") is not None:
        ax.add_patch(Rectangle((0, t["box_low"]), n - 1, t["box_high"] - t["box_low"],
                               facecolor="#388bfd", alpha=0.10, edgecolor="#388bfd", zorder=1))
    # entry index — match by TIME for any intraday interval, by DATE for daily
    ei = None
    if interval in _INTRADAY and t.get("entry_time"):
        times = [ts.strftime("%H:%M") for ts in bars.index]
        if t["entry_time"] in times:
            ei = times.index(t["entry_time"])
    elif interval not in _INTRADAY:
        ds = [str(x) for x in bars["_d"]]
        if str(t["date"]) in ds:
            ei = ds.index(str(t["date"]))
    for key, col in (("entry", "#e3b341"), ("stop", "#f85149"), ("target", "#3fb950")):
        if t.get(key) is not None:
            ax.axhline(t[key], color=col, linewidth=0.8, linestyle="--", zorder=4)
    if ei is not None:
        # rectangle outline around the ENTRY candle (its high-low, full candle width)
        cw = 0.46
        y0, y1 = float(l[ei]), float(h[ei])
        ax.add_patch(Rectangle((ei - cw, y0), 2 * cw, (y1 - y0) or 1e-9, fill=False,
                               edgecolor="#e3b341", linewidth=1.6, zorder=8))
        ax.annotate("ENTRY", (ei, y1), textcoords="offset points", xytext=(0, 5),
                    ha="center", color="#e3b341", fontsize=6.5, fontweight="bold", zorder=8)
    r = t.get("r_gross", t.get("r", 0)); rn = t.get("r_net", r)
    won = r > 0
    # time (intraday) or date (daily) labels on the x-axis
    if n > 2:
        tk = list(range(0, n, max(1, n // 6)))
        if interval in _INTRADAY:
            labs = [bars.index[i].strftime("%H:%M") for i in tk]
        else:
            labs = [str(bars["_d"].iloc[i])[5:] for i in tk]
        ax.set_xticks(tk); ax.set_xticklabels(labs, fontsize=5.5)
    ax.set_title(f"{t['symbol']}  {t['date']}  {t['direction'].upper()}  ·  {interval}   "
                 f"{'+' if r>0 else ''}{r}R (net {rn})",
                 color="#3fb950" if won else "#f85149", fontsize=8)
    ax.tick_params(colors="#9da7b3", labelsize=6)
    for s in ax.spines.values():
        s.set_color("#30363d")
    ax.margins(x=0.01)
    fig.tight_layout(pad=0.4)
    fig.savefig(out_path, facecolor=fig.get_facecolor())
    plt.close(fig)


def _write_gallery(base: Path, manifest: dict):
    """Browsable one-page gallery: all winners grid + all losers grid, from the rendered PNGs."""
    wins = [t for t in manifest["trades"] if t["outcome"] == "win"]
    loss = [t for t in manifest["trades"] if t["outcome"] == "loss"]

    def cell(t):
        return (f'<figure><img loading="lazy" src="{t["image"]}">'
                f'<figcaption>{t["symbol"]} {t["date"]} {t["direction"]} '
                f'<b class="{ "w" if t["outcome"]=="win" else "l" }">{t["r_gross"]:+}R</b></figcaption></figure>')
    html = f"""<!doctype html><meta charset=utf-8><title>{manifest['strategy']} — backtest gallery</title>
<style>body{{background:#0d1117;color:#e6edf3;font-family:system-ui;margin:0;padding:18px}}
h1{{font-size:19px;margin:0 0 2px}}.sub{{color:#9da7b3;font-size:13px;margin-bottom:14px}}
h2{{font-size:15px;margin:18px 0 8px;border-bottom:1px solid #30363d;padding-bottom:4px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}}
figure{{margin:0;background:#161b22;border:1px solid #30363d;border-radius:6px;padding:5px}}
img{{width:100%;display:block;border-radius:4px}}figcaption{{font-size:11px;color:#9da7b3;padding:4px 2px}}
b.w{{color:#3fb950}}b.l{{color:#f85149}}</style>
<h1>{manifest['strategy']} — backtest trade gallery</h1>
<div class=sub>{manifest['interval']} · {manifest['n_total']} total trades ({manifest['n_win']} win / {manifest['n_loss']} loss)
· showing {len(wins)} winners + {len(loss)} losers spread across the full period · {manifest.get('source','')}</div>
<h2 class=w style="color:#3fb950">✓ Winners ({len(wins)})</h2><div class=grid>{''.join(cell(t) for t in wins)}</div>
<h2 class=l style="color:#f85149">✗ Losers ({len(loss)})</h2><div class=grid>{''.join(cell(t) for t in loss)}</div>"""
    (base / "gallery.html").write_text(html, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--interval", default="1m", help="1m (parquet) or 1d/5m/30m (csv)")
    ap.add_argument("--pad-days", type=int, default=25, help="daily window half-width around the trade")
    ap.add_argument("--max-per-side", type=int, default=40)
    ap.add_argument("--source-note", default="")
    args = ap.parse_args()

    ledger = json.loads(Path(args.ledger).read_text())
    for t in ledger:
        t.setdefault("r_gross", t.get("r", 0))
    wins = [t for t in ledger if t["r_gross"] > 0]
    losses = [t for t in ledger if t["r_gross"] <= 0]

    def spread(lst, k):
        if not lst:
            return []
        step = max(1, len(lst) // k)
        return lst[::step][:k]
    picks = [("winners", t) for t in spread(wins, args.max_per_side)] + \
            [("losers", t) for t in spread(losses, args.max_per_side)]

    base = IMG_ROOT / args.strategy
    for side in ("winners", "losers"):
        (base / side).mkdir(parents=True, exist_ok=True)
    manifest = {"strategy": args.strategy, "interval": args.interval, "source": args.source_note,
                "generated_at": pd.Timestamp.utcnow().isoformat(),
                "n_total": len(ledger), "n_win": len(wins), "n_loss": len(losses), "trades": []}
    done = 0
    for side, t in picks:
        bars = _window(t["symbol"], t["date"], args.interval, args.pad_days)
        if bars is None or len(bars) < 5:
            continue
        rsig = f"{t['r_gross']:+.2f}".replace("-", "m").replace("+", "p")
        name = f"{t['symbol']}__{t['date']}__{t['direction']}__{side[:-1].upper()}__{rsig}.png"
        out = base / side / name
        _draw(t, bars, out, args.interval)
        manifest["trades"].append({
            "symbol": t["symbol"], "date": t["date"], "direction": t["direction"],
            "outcome": "win" if t["r_gross"] > 0 else "loss",
            "r_gross": t["r_gross"], "r_net": t.get("r_net", t["r_gross"]),
            "entry": t.get("entry"), "stop": t.get("stop"), "target": t.get("target"),
            "image": f"{side}/{name}"})
        done += 1
    (base / "manifest.json").write_text(json.dumps(manifest, indent=2))
    _write_gallery(base, manifest)
    print(f"{args.strategy}: rendered {done} images -> {base}  (+ gallery.html)")
    print(f"  winners {len([p for p in picks if p[0]=='winners'])}  "
          f"losers {len([p for p in picks if p[0]=='losers'])}  manifest.json written")


if __name__ == "__main__":
    main()
