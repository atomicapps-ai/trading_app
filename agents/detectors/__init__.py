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
  * cup_and_handle                  — rounded base + small handle + pivot breakout
  * wyckoff_accumulation            — Spring entry off SC/AR trading range

Remaining:
  * bear_flag (mirror of bull_flag) — deferred; spec mostly handled by
    the short paths inside the implemented reversal/continuation detectors
"""
from agents.detectors.ascending_triangle import detect_ascending_descending_triangle
from agents.detectors.band_extreme_fade import detect_band_extreme_fade
from agents.detectors.bull_flag import detect_bull_flag
from agents.detectors.coil_breakout import detect_coil_breakout
from agents.detectors.cup_and_handle import detect_cup_and_handle
from agents.detectors.hidden_divergence import detect_hidden_divergence
from agents.detectors.double_bottom_top import detect_double_bottom_top
from agents.detectors.double_lock_filtered import detect_double_lock_filtered
from agents.detectors.inside_bar_nr7 import detect_inside_bar_nr7
from agents.detectors.intraday_reversion import detect_intraday_reversion
from agents.detectors.macd_run import detect_macd_run
from agents.detectors.rsi_divergence import detect_rsi_divergence
from agents.detectors.rsi_pullback import detect_rsi_pullback
from agents.detectors.s5_mean_reversion import detect_s5_mean_reversion
from agents.detectors.s7_breakout_continuation import detect_s7_breakout_continuation
from agents.detectors.turn_of_month import detect_turn_of_month
from agents.detectors.volatility_squeeze import detect_volatility_squeeze
from agents.detectors.vwap_reclaim import detect_vwap_reclaim
from agents.detectors.wyckoff_accumulation import detect_wyckoff_accumulation

# Map name -> callable for the SWING analyst to iterate. The analyst
# invokes each as fn(daily, hourly, config, as_of_ts, macro_context=...).
# Detectors that need a different signature (e.g. intraday 30m bars +
# VIX context for double_lock_filtered) live in INTRADAY_DETECTORS and
# are dispatched by the workflow that knows how to feed them.
ALL_DETECTORS = {
    "volatility_squeeze": detect_volatility_squeeze,
    "inside_bar_nr7": detect_inside_bar_nr7,
    "bull_flag": detect_bull_flag,
    "rsi_divergence": detect_rsi_divergence,
    "vwap_reclaim": detect_vwap_reclaim,
    "double_bottom_top": detect_double_bottom_top,
    "ascending_descending_triangle": detect_ascending_descending_triangle,
    "cup_and_handle": detect_cup_and_handle,
    "wyckoff_accumulation": detect_wyckoff_accumulation,
    # Video-mined, hardened daily strategies (see strategies/strategy_docs/)
    "s7_breakout_continuation": detect_s7_breakout_continuation,
    "s5_mean_reversion": detect_s5_mean_reversion,
    "coil_breakout": detect_coil_breakout,
    "macd_run": detect_macd_run,
    # Video-mined diversifiers (gated on correlation vs the live book) — active:false
    # pending in-app re-validation. See strategies/STRATEGY_GRID.md.
    "rsi_pullback": detect_rsi_pullback,
    "band_extreme_fade": detect_band_extreme_fade,
    "hidden_divergence": detect_hidden_divergence,
    # Sourced from reviewed platforms (QuantifiedStrategies/Quantpedia); validated + gated.
    "turn_of_month": detect_turn_of_month,
}

# Intraday detectors — different signature than ALL_DETECTORS. Each
# entry expects (bars_30m, daily, vix_prev_close, config, as_of_ts).
# Dispatched by intraday workflows (e.g. workflows/double_lock_1030.yaml)
# rather than the standard swing analyst.
INTRADAY_DETECTORS = {
    "double_lock_filtered": detect_double_lock_filtered,
    # Day-trade lane scaffold/example (flat by session close). NOT validated —
    # backtest via scripts/bt_intraday.py before enabling. See INTRADAY_SCAFFOLD.md.
    "intraday_reversion": detect_intraday_reversion,
}

__all__ = [
    "ALL_DETECTORS",
    "INTRADAY_DETECTORS",
    "detect_ascending_descending_triangle",
    "detect_band_extreme_fade",
    "detect_bull_flag",
    "detect_coil_breakout",
    "detect_cup_and_handle",
    "detect_double_bottom_top",
    "detect_double_lock_filtered",
    "detect_hidden_divergence",
    "detect_inside_bar_nr7",
    "detect_intraday_reversion",
    "detect_macd_run",
    "detect_rsi_divergence",
    "detect_rsi_pullback",
    "detect_s5_mean_reversion",
    "detect_turn_of_month",
    "detect_s7_breakout_continuation",
    "detect_volatility_squeeze",
    "detect_vwap_reclaim",
    "detect_wyckoff_accumulation",
]
