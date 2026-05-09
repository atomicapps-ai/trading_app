"""diagnose_mag7.py — figure out why specific Mag-7 names aren't passing.

For each name, refresh from yfinance to get today's bar, then compute:
  - ATR(14) / close as %
  - close / SMA50, close / SMA200
  - shows whether each Stage-2 filter passes
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")                            # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import pandas as pd

from services import hf_data_service


MAG7 = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
ATR_MIN = 0.015
ATR_MAX = 0.05


def compute(df: pd.DataFrame) -> dict | None:
    if len(df) < 200:
        return None
    high = df["high"]; low = df["low"]; close = df["close"]
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / 14, adjust=False).mean()
    last_close = float(close.iloc[-1])
    last_atr = float(atr.iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1])
    return dict(
        close=last_close,
        atr=last_atr,
        atr_pct=last_atr / last_close,
        sma50=sma50,
        sma200=sma200,
        above_sma50=last_close > sma50,
        above_sma200=last_close > sma200,
        last_bar=df.index[-1].strftime("%Y-%m-%d"),
    )


def load_bars(symbol: str) -> pd.DataFrame | None:
    p = ROOT / "data" / "historical" / f"{symbol}_1d.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    df.columns = [c.strip().lower() for c in df.columns]
    if "adj_close" in df.columns and "close" in df.columns:
        df["close"] = df["adj_close"]
    cols = ["open", "high", "low", "close", "volume"]
    df = df[[c for c in cols if c in df.columns]].dropna()
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


async def main() -> int:
    # Force fresh yfinance pull for each
    print(f"refreshing yfinance for {len(MAG7)} mag-7...")
    for sym in MAG7:
        r = await hf_data_service.fetch_and_save(
            sym, source="yfinance", start="2010-01-01", interval="1d",
        )
        print(f"  {sym}: {'ok' if r['ok'] else 'FAIL'}")

    print(f"\n{'sym':<6} {'close':>10} {'atr%':>6} {'>SMA50':>8} {'>SMA200':>8} "
          f"{'in band':>9} {'verdict':>15} {'last bar':>12}")
    print("-" * 90)

    for sym in MAG7:
        df = load_bars(sym)
        if df is None:
            print(f"{sym:<6} (no bars)")
            continue
        r = compute(df)
        if r is None:
            print(f"{sym:<6} (insufficient history)")
            continue
        in_band = ATR_MIN <= r["atr_pct"] <= ATR_MAX
        passes_all = in_band and r["above_sma50"] and r["above_sma200"]
        verdict = "PASS" if passes_all else "REJECT"

        # Why-rejected detail
        reasons = []
        if not in_band:
            reasons.append(
                "ATR% high" if r["atr_pct"] > ATR_MAX else "ATR% low"
            )
        if not r["above_sma50"]:
            reasons.append("below SMA50")
        if not r["above_sma200"]:
            reasons.append("below SMA200")
        why = ",".join(reasons) if reasons else "all-pass"

        print(f"{sym:<6} {r['close']:>10.2f} {r['atr_pct']*100:>5.2f}% "
              f"{'YES' if r['above_sma50'] else 'NO':>8} "
              f"{'YES' if r['above_sma200'] else 'NO':>8} "
              f"{'YES' if in_band else 'NO':>9} {verdict:>15} "
              f"{r['last_bar']:>12}  ({why})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
