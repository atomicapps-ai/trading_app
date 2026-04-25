"""Global indicator registry — single source of truth for technical indicators.

Anywhere in the app where a user picks indicators (chart overlays on the
trade detail page, configurable widgets, etc.), the picker reads from
``INDICATORS`` here. Each entry maps to the existing
``/api/indicators/{symbol}`` endpoint contract — registry IDs match the
API's ``indicators=`` query parameter so chip toggles can directly
request data without an extra translation layer.

v1 scope
--------
Single-series indicators only. Compound indicators (Bollinger bands,
MACD = line+signal+hist, Volume = vol+sma) need a multi-render path on
the chart side; we add them once the chart wiring proves out on simple
overlays. Skipping them now keeps the toggle / fetch / render loop
trivial.

Adding a new indicator
----------------------
1. Verify the API at ``routers/indicators.py`` returns it as a
   single-series in ``response["indicators"][<key>]``.
2. Append an IndicatorSpec entry below.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

IndicatorPane = Literal["overlay", "subplot"]
IndicatorCategory = Literal[
    "moving_average", "momentum", "volatility", "volume", "trend",
]


@dataclass(frozen=True)
class IndicatorSpec:
    """One togglable indicator.

    ``id`` doubles as the request param sent to /api/indicators and the
    response key read from ``indicators[<id>]`` — matching the endpoint
    contract avoids any mapping table.
    """

    id: str                  # API id == response key == saved-settings key
    label: str
    category: IndicatorCategory
    pane: IndicatorPane = "overlay"
    default_color: str = "#4a8bf4"
    description: str = ""


# IDs match the contract in routers/indicators.py.
INDICATORS: dict[str, IndicatorSpec] = {
    # ── Moving averages (overlay) ─────────────────────────────────────────
    "sma20":  IndicatorSpec("sma20",  "SMA 20",  "moving_average",
                            "overlay", "#60a5fa", "20-period simple moving average"),
    "sma50":  IndicatorSpec("sma50",  "SMA 50",  "moving_average",
                            "overlay", "#a78bfa", "50-period simple moving average"),
    "sma200": IndicatorSpec("sma200", "SMA 200", "moving_average",
                            "overlay", "#f59e0b", "200-period simple moving average"),
    "ema20":  IndicatorSpec("ema20",  "EMA 20",  "moving_average",
                            "overlay", "#22d3ee", "20-period exponential moving average"),

    # ── VWAP (overlay) ────────────────────────────────────────────────────
    "vwap":   IndicatorSpec("vwap",   "VWAP",    "volume",
                            "overlay", "#ec4899",
                            "Volume-weighted average price"),

    # ── Momentum / volatility (subplot) ───────────────────────────────────
    "rsi":    IndicatorSpec("rsi",    "RSI 14",  "momentum",
                            "subplot", "#a78bfa",
                            "14-period Wilder RSI"),
    "atr":    IndicatorSpec("atr",    "ATR 14",  "volatility",
                            "subplot", "#fbbf24",
                            "14-period Wilder ATR"),
}


# ── Helpers ─────────────────────────────────────────────────────────────────


def get_indicator(indicator_id: str) -> IndicatorSpec | None:
    return INDICATORS.get(indicator_id)


def indicators_by_category() -> dict[str, list[IndicatorSpec]]:
    out: dict[str, list[IndicatorSpec]] = {}
    for spec in INDICATORS.values():
        out.setdefault(spec.category, []).append(spec)
    for k in out:
        out[k].sort(key=lambda s: s.id)
    return out


def overlay_indicators() -> list[IndicatorSpec]:
    return [s for s in INDICATORS.values() if s.pane == "overlay"]


def subplot_indicators() -> list[IndicatorSpec]:
    return [s for s in INDICATORS.values() if s.pane == "subplot"]


# Sane defaults for the trade detail chart.
DEFAULT_OVERLAY_IDS: list[str] = ["sma20", "sma50", "vwap"]
DEFAULT_SUBPLOT_IDS: list[str] = ["rsi"]
