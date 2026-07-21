"""build_daytrade_universe — screen the local daily cache for names that are actually
day-tradeable, and emit both the symbol list and an Alpha-Vantage fetch plan.

Target profile (what a discretionary day trader means by "tradeable"): priced low enough
to size properly, liquid enough that a market order doesn't move it, and with enough
daily range that a realistic stop is a small fraction of the day's movement — while not
being so volatile it's a lottery ticket.

Filters (defaults follow Zarattini/Barbon/Aziz, "A Profitable Day Trading Strategy for
the U.S. Equity Market", SSRN 4729284, plus a price ceiling and a volatility band):

  * price in [--min-price, --max-price]           default $5-$100
  * 60-day average volume >= --min-volume         default 1,000,000 shares
  * ATR(14) > --min-atr                           default $0.50   (paper's floor)
  * ATR(14)/price in [--min-atrpct, --max-atrpct] default 1.5%-8%  (range without lottery)
  * >= --min-days of daily history                default 250

The ATR band is the "relatively stable" term: below ~1.5% a $30 stock doesn't move enough
in a session to pay for spread plus commission; above ~8% you are trading news and gaps,
not a repeatable intraday setup.

    python -m scripts.build_daytrade_universe                       # screen + report
    python -m scripts.build_daytrade_universe --top 300 --write     # persist the list

⚠ Survivorship: this screens instruments that exist *today*, so it excludes names that
delisted or were acquired. Any cross-sectional backtest on it will overstate returns. The
source paper deliberately includes delisted names; see the printed warning.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from services.settings_service import DATA_DIR

HIST = DATA_DIR / "historical"
HIST_1M = DATA_DIR / "historical_1m"
OUT = DATA_DIR / "research"


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    return float(pd.Series(tr).ewm(span=period, adjust=False).mean().iloc[-1])


def profile_symbols(min_days: int) -> pd.DataFrame:
    rows = []
    for f in glob.glob(str(HIST / "*_1d.csv")):
        sym = os.path.basename(f)[:-7]
        try:
            df = pd.read_csv(f).tail(300)
            if len(df) < min_days:
                continue
            df.columns = [c.lower() for c in df.columns]
            if not {"high", "low", "close", "volume"} <= set(df.columns):
                continue
            price = float(df["close"].iloc[-1])
            advol = float(df["volume"].tail(60).mean())
            dollar_vol = price * advol
            atr = _atr(df)
            if price <= 0 or atr <= 0:
                continue
            rows.append({"symbol": sym, "price": round(price, 2),
                         "avg_volume": int(advol), "dollar_volume": int(dollar_vol),
                         "atr": round(atr, 2), "atr_pct": round(atr / price * 100, 2),
                         "has_1m": (HIST_1M / f"{sym}.parquet").exists()})
        except Exception:  # noqa: BLE001 — a malformed cache file shouldn't kill the screen
            continue
    return pd.DataFrame(rows)


def screen(df: pd.DataFrame, a) -> pd.DataFrame:
    m = ((df.price >= a.min_price) & (df.price <= a.max_price)
         & (df.avg_volume >= a.min_volume)
         & (df.atr > a.min_atr)
         & (df.atr_pct >= a.min_atrpct) & (df.atr_pct <= a.max_atrpct))
    out = df[m].copy()
    # rank by dollar volume — the practical proxy for "I can get filled without slipping"
    return out.sort_values("dollar_volume", ascending=False).reset_index(drop=True)


def fetch_plan(symbols: list[str], years: int, rpm: int) -> dict:
    """Alpha Vantage serves ONE symbol-month per call, so cost is linear in both."""
    missing = [s for s in symbols if not (HIST_1M / f"{s}.parquet").exists()]
    calls = len(missing) * years * 12
    return {"symbols_total": len(symbols), "symbols_missing_1m": len(missing),
            "years": years, "api_calls": calls,
            "hours_at_rpm": round(calls / max(rpm, 1) / 60, 1), "missing": missing}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-price", type=float, default=5.0)
    ap.add_argument("--max-price", type=float, default=100.0)
    ap.add_argument("--min-volume", type=float, default=1_000_000)
    ap.add_argument("--min-atr", type=float, default=0.50)
    ap.add_argument("--min-atrpct", type=float, default=1.5)
    ap.add_argument("--max-atrpct", type=float, default=8.0)
    ap.add_argument("--min-days", type=int, default=250)
    ap.add_argument("--top", type=int, default=0, help="keep only the top N by dollar volume")
    ap.add_argument("--years", type=int, default=10, help="history depth for the fetch plan")
    ap.add_argument("--rpm", type=int, default=int(os.getenv("ALPHAVANTAGE_RPM", "75")))
    ap.add_argument("--write", action="store_true", help="persist the universe json")
    ap.add_argument("--name", default="daytrade_sub100")
    a = ap.parse_args()

    prof = profile_symbols(a.min_days)
    sel = screen(prof, a)
    if a.top:
        sel = sel.head(a.top)

    print(f"profiled {len(prof)} symbols with >= {a.min_days}d history")
    print(f"screen: ${a.min_price:g}-${a.max_price:g} · vol>={a.min_volume/1e6:g}M · "
          f"ATR>${a.min_atr:g} · ATR% {a.min_atrpct}-{a.max_atrpct}")
    print(f"-> {len(sel)} symbols\n")

    print(f"{'symbol':<8}{'price':>8}{'avgvol':>12}{'$vol(M)':>10}{'ATR':>7}{'ATR%':>7}  1m")
    for _, r in sel.head(25).iterrows():
        print(f"{r.symbol:<8}{r.price:>8.2f}{r.avg_volume:>12,}{r.dollar_volume/1e6:>10.0f}"
              f"{r.atr:>7.2f}{r.atr_pct:>7.2f}  {'Y' if r.has_1m else '-'}")
    if len(sel) > 25:
        print(f"... and {len(sel)-25} more")

    print(f"\nprice buckets: " + " · ".join(
        f"${lo}-{hi}: {len(sel[(sel.price>=lo)&(sel.price<hi)])}"
        for lo, hi in [(5, 20), (20, 50), (50, 100)]))
    print(f"median ATR%: {sel.atr_pct.median():.2f} · already have 1m: "
          f"{int(sel.has_1m.sum())}/{len(sel)}")

    plan = fetch_plan(sel.symbol.tolist(), a.years, a.rpm)
    print(f"\nAlpha Vantage fetch plan ({a.years}y of 1-minute bars):")
    print(f"  {plan['symbols_missing_1m']} symbols missing 1m × {a.years*12} months "
          f"= {plan['api_calls']:,} calls")
    print(f"  at {a.rpm} req/min -> ~{plan['hours_at_rpm']} hours")

    print("\n!! SURVIVORSHIP: this screens instruments trading TODAY. Names that delisted or "
          "were acquired are absent, so any cross-sectional backtest on this universe will "
          "overstate returns. SSRN 4729284 deliberately includes delisted names.")

    if a.write:
        OUT.mkdir(parents=True, exist_ok=True)
        p = OUT / f"universe_{a.name}.json"
        p.write_text(json.dumps({
            "name": a.name,
            "filters": {k: getattr(a, k) for k in
                        ("min_price", "max_price", "min_volume", "min_atr",
                         "min_atrpct", "max_atrpct", "min_days")},
            "symbols": sel.symbol.tolist(),
            "detail": sel.to_dict(orient="records"),
            "fetch_plan": {k: v for k, v in plan.items() if k != "missing"},
        }, indent=2), encoding="utf-8")
        (OUT / f"universe_{a.name}_missing_1m.txt").write_text(
            "\n".join(plan["missing"]), encoding="utf-8")
        print(f"\nwrote {p}  (+ _missing_1m.txt for the fetcher)")


if __name__ == "__main__":
    main()
