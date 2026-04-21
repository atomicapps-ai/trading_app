"""Pattern detectors — one file per pattern.

Each detector is a PURE FUNCTION of (daily, hourly, config, as_of_ts).
No wall-clock calls, no network calls, no module-level mutable state.
The caller (``analyst.run_lens_technical``) supplies everything the
detector needs.

This contract is the foundation of Phase 5 backtesting — the same
detector runs live and across 10+ years of historical bars.

Implemented:
  * volatility_squeeze              — indicator_service squeeze columns
  * inside_bar_nr7                  — narrowest range of last 7 + inside
  * bull_flag                       — flagpole / flag / breakout
  * rsi_divergence                  — bullish + bearish class A/B/C
  * vwap_reclaim                    — above → break → consolidate → reclaim
  * double_bottom_top               — two-pivot reversal with neckline break
  * ascending_descending_triangle   — flat level + rising/falling pivots

Remaining:
  * bear_flag (mirror of bull_flag)
  * cup_and_handle
  * wyckoff_accumulation
"""
from agents.detectors.ascending_triangle import detect_ascending_descending_triangle
from agents.detectors.bull_flag import detect_bull_flag
from agents.detectors.double_bottom_top import detect_double_bottom_top
from agents.detectors.inside_bar_nr7 import detect_inside_bar_nr7
from agents.detectors.rsi_divergence import detect_rsi_divergence
from agents.detectors.volatility_squeeze import detect_volatility_squeeze
from agents.detectors.vwap_reclaim import detect_vwap_reclaim

# Map name -> callable for the analyst to iterate
ALL_DETECTORS = {
    "volatility_squeeze": detect_volatility_squeeze,
    "inside_bar_nr7": detect_inside_bar_nr7,
    "bull_flag": detect_bull_flag,
    "rsi_divergence": detect_rsi_divergence,
    "vwap_reclaim": detect_vwap_reclaim,
    "double_bottom_top": detect_double_bottom_top,
    "ascending_descending_triangle": detect_ascending_descending_triangle,
}

__all__ = [
    "ALL_DETECTORS",
    "detect_ascending_descending_triangle",
    "detect_bull_flag",
    "detect_double_bottom_top",
    "detect_inside_bar_nr7",
    "detect_rsi_divergence",
    "detect_volatility_squeeze",
    "detect_vwap_reclaim",
]
