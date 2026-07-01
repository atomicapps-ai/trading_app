"""tradingview.py — build TradingView deep-links for the trade-review UI.

Asset-aware: FX pairs open on OANDA at an intraday interval (matching how we trade
the FVG strategy); equities open at daily on their listing exchange (or bare symbol,
which TradingView resolves). Used by the 'Open in TradingView ↗' button on the
trade-detail / pending pages so a reviewer can investigate any signal in one click.
"""
from __future__ import annotations

# app interval token -> TradingView interval code
_TV_INTERVAL = {
    "1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "60m": "60",
    "2h": "120", "4h": "240", "1d": "D", "d": "D", "D": "D", "1w": "W", "W": "W", "M": "M",
}


def is_fx(symbol: str) -> bool:
    s = symbol.upper().replace("/", "").replace("_", "")
    return len(s) == 6 and s.isalpha()


def tv_symbol(symbol: str, asset_class: str | None = None, exchange: str | None = None) -> str:
    s = symbol.upper().replace("/", "").replace("_", "")
    if asset_class == "forex" or (asset_class is None and is_fx(s)):
        return f"OANDA:{s}"
    if exchange:
        return f"{exchange.upper()}:{s}"
    return s  # bare symbol — TradingView auto-resolves the listing


def tv_interval(interval: str | None) -> str:
    if not interval:
        return "D"
    return _TV_INTERVAL.get(str(interval), str(interval) if str(interval) in ("D", "W", "M") else "D")


def tv_url(symbol: str, *, asset_class: str | None = None,
           interval: str | None = None, exchange: str | None = None) -> str:
    """Deep link that opens the symbol+interval on a TradingView chart."""
    sym = tv_symbol(symbol, asset_class, exchange)
    return f"https://www.tradingview.com/chart/?symbol={sym}&interval={tv_interval(interval)}"


def tv_for_trade(symbol: str, strategy_name: str | None = None) -> str:
    """Pick a sensible asset class + interval from the symbol and strategy.
    FX / FVG-continuation → OANDA 30m; everything else → daily."""
    fx = is_fx(symbol) or (strategy_name or "").startswith(("fvg", "e3mc"))
    return tv_url(symbol, asset_class=("forex" if fx else "equity"),
                  interval=("30m" if fx else "1d"))
