"""Pattern detectors — one file per pattern.

Each detector is a PURE FUNCTION of (daily, hourly, config, as_of_ts).
No wall-clock calls, no network calls, no module-level mutable state.
The caller (``analyst.run_lens_technical``) supplies everything the
detector needs.

This contract is the foundation of Phase 5 backtesting — the same
detector runs live and across 10+ years of historical bars.

Implemented in Phase 4 (this session):
  * volatility_squeeze  — uses indicator_service squeeze columns
  * inside_bar_nr7      — narrowest range of last 7 + inside prior bar
  * bull_flag           — flagpole / flag / breakout detection

Remaining (follow-up sessions):
  * bear_flag (mirror of bull_flag)
  * double_bottom_top
  * rsi_divergence
  * ascending_descending_triangle
  * cup_and_handle
  * vwap_reclaim
  * wyckoff_accumulation
"""
from agents.detectors.bull_flag import detect_bull_flag
from agents.detectors.inside_bar_nr7 import detect_inside_bar_nr7
from agents.detectors.volatility_squeeze import detect_volatility_squeeze

# Map name -> callable for the analyst to iterate
ALL_DETECTORS = {
    "volatility_squeeze": detect_volatility_squeeze,
    "inside_bar_nr7": detect_inside_bar_nr7,
    "bull_flag": detect_bull_flag,
}

__all__ = [
    "ALL_DETECTORS",
    "detect_bull_flag",
    "detect_inside_bar_nr7",
    "detect_volatility_squeeze",
]
