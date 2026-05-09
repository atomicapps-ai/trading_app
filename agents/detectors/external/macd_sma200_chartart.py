"""macd_sma200_chartart — MACD histogram cross with SMA200 regime filter.

Pine source: strategies/external/macd_sma200_chartart/source.pine
Author: ChartArt (TradingView), v1.0, Nov 2015
Family: Trend-following

Entry rule (long): histogram crosses up through 0 AND macd > 0 AND
fastMA > slowMA AND price slowLength bars ago was > very-slow MA.
Entry rule (short): mirror.

Translation notes:
- Pine uses SMA for ALL three averages (fast/slow/very-slow). We honor that
  even though textbook MACD uses EMA — the strategy author chose SMA.
- The `close[slowLength]` lookback for the SMA200 filter is preserved
  faithfully (idx - slow_length, not idx - 1). This may be intentional
  (lag the trend filter by ~1 month of daily bars to avoid false dawns) or
  a typo by the author — only the optimizer can tell.
- Stop placement uses the bar's low (long) / high (short) at signal time,
  matching the Pine `stop=buyprice`/`stop=sellprice` semantic.
- No TP — exit only on opposite signal or regime cancel (slowMA crosses
  back through very-slow MA the wrong way). Implemented as opposite_signal.
"""
from __future__ import annotations

import pandas as pd

from agents.detectors.external._base import Signal


META = {
    "slug": "macd_sma200_chartart",
    "family": "trend_following",
    "natural_interval": "1d",
    "long_only": False,
    "source_url": None,
    "primitives": ["macd", "sma_regime_filter", "bar_relative_stop"],
}


PARAMETER_SPEC = {
    "fast_length": {
        "default": 12, "type": int,
        "sweep": [8, 12, 21],
        "reasoning": "Standard MACD uses 12. Faster (8) for choppier names; "
                     "21 = Elder/Vegas variant for slower trends.",
    },
    "slow_length": {
        "default": 26, "type": int,
        "sweep": [21, 26, 34, 50],
        "reasoning": "Standard 26. Longer values reduce whip on TSLA-style names.",
    },
    "signal_length": {
        "default": 9, "type": int,
        "sweep": [6, 9, 14],
        "reasoning": "Faster signal MA = earlier entry, more whips. Standard 9.",
    },
    "very_slow_length": {
        "default": 200, "type": int,
        "sweep": [100, 150, 200, 300],
        "reasoning": "Regime filter horizon. 200 = canonical 10-mo trend; "
                     "100/150 catch faster regime shifts.",
    },
}


def detect(bars: pd.DataFrame, params: dict) -> list[Signal]:
    fast = int(params.get("fast_length", 12))
    slow = int(params.get("slow_length", 26))
    signal_n = int(params.get("signal_length", 9))
    vslow = int(params.get("very_slow_length", 200))

    close = bars["close"]
    fast_ma = close.rolling(fast).mean()
    slow_ma = close.rolling(slow).mean()
    vslow_ma = close.rolling(vslow).mean()
    macd = fast_ma - slow_ma
    signal_line = macd.rolling(signal_n).mean()
    hist = macd - signal_line
    hist_prev = hist.shift(1)

    # close[slowLength] — close from `slow` bars ago — Pine semantics
    close_lag = close.shift(slow)

    # Regime gates
    above_vslow = close_lag > vslow_ma
    below_vslow = close_lag < vslow_ma
    fast_above_slow = fast_ma > slow_ma
    fast_below_slow = fast_ma < slow_ma

    # Signals
    hist_xover_zero = (hist > 0) & (hist_prev <= 0)
    hist_xunder_zero = (hist < 0) & (hist_prev >= 0)

    long_trig = hist_xover_zero & (macd > 0) & fast_above_slow & above_vslow
    short_trig = hist_xunder_zero & (macd < 0) & fast_below_slow & below_vslow

    high = bars["high"]
    low = bars["low"]
    signals: list[Signal] = []
    for i in range(len(bars)):
        if pd.isna(vslow_ma.iloc[i]) or pd.isna(close_lag.iloc[i]):
            continue
        c = float(close.iloc[i])
        if long_trig.iloc[i]:
            stop = float(low.iloc[i])
            if stop < c:
                signals.append(Signal(
                    bar_idx=i, direction="long",
                    entry_price=c, stop_price=stop,
                    note=f"macd={macd.iloc[i]:.2f} hist={hist.iloc[i]:.3f}",
                ))
        elif short_trig.iloc[i]:
            stop = float(high.iloc[i])
            if stop > c:
                signals.append(Signal(
                    bar_idx=i, direction="short",
                    entry_price=c, stop_price=stop,
                    note=f"macd={macd.iloc[i]:.2f} hist={hist.iloc[i]:.3f}",
                ))
    return signals
