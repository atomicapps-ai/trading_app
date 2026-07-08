"""cost_model — realistic per-symbol round-trip cost (bps) for intraday backtests.

The flat 10-bps cost we used for swing tests is far too high for liquid intraday day-trades and can
wrongly reject a real edge. Estimate a per-symbol round-trip cost from average dollar volume (ADV):
the more liquid the name, the tighter the spread + slippage. Rough, but far fairer than a flat 10bps.

Tiers (round-trip, spread + slippage + commission, in bps of notional):
  ADV > $5B  (SPY/QQQ/mega ETFs)      -> 1.5
  ADV $1-5B  (mega-cap stocks)        -> 3
  ADV $200M-1B                        -> 6
  ADV < $200M (thin)                  -> 12
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

HIST = Path(__file__).resolve().parent.parent / "data" / "historical"
_adv_cache: dict[str, float] = {}
_bps_cache: dict[str, float] = {}


def adv_usd(symbol: str) -> float:
    if symbol in _adv_cache:
        return _adv_cache[symbol]
    f = HIST / f"{symbol}_1d.csv"
    adv = 0.0
    if f.exists():
        df = pd.read_csv(f)
        df.columns = [c.lower() for c in df.columns]
        if {"close", "volume"}.issubset(df.columns):
            dv = (df["close"] * df["volume"]).tail(252)
            adv = float(dv.median()) if len(dv) else 0.0
    _adv_cache[symbol] = adv
    return adv


def roundtrip_bps(symbol: str) -> float:
    if symbol in _bps_cache:
        return _bps_cache[symbol]
    a = adv_usd(symbol)
    if a > 5e9:
        bps = 1.5
    elif a > 1e9:
        bps = 3.0
    elif a > 2e8:
        bps = 6.0
    elif a > 0:
        bps = 12.0
    else:
        bps = 8.0        # unknown ADV -> mid default
    _bps_cache[symbol] = bps
    return bps


def roundtrip_frac(symbol: str) -> float:
    """Round-trip cost as a fraction of notional (bps / 10000)."""
    return roundtrip_bps(symbol) / 10000.0


if __name__ == "__main__":
    for s in ["SPY", "QQQ", "IWM", "DIA", "AAPL", "NVDA", "TSLA", "XLRE", "ACAD"]:
        print(f"{s:6} ADV=${adv_usd(s)/1e9:6.2f}B  round-trip {roundtrip_bps(s):4.1f} bps")
