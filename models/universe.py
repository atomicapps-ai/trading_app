"""Universe filter models — preset criteria, ticker lists, and run results.

The ticker list and the criteria live in separate YAML files (by design):

  * ``universe_filter_presets.yaml``         — criteria (rarely edited)
  * ``universe_filter_presets_tickers.yaml`` — ticker lists per preset,
                                                rewritten by the refresh
                                                script, committed to git

This split keeps criteria diffs clean and isolates the churn from the
periodic Finviz refresh.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Criteria schema (subset of universe_filter_presets.yaml actually consumed)
# --------------------------------------------------------------------------- #
#
# The full preset YAML is intentionally richer than this model — it carries
# Finviz-vocabulary fields (eps_ttm_positive, roe_min, etc.) that the refresh
# script uses to build the screener URL. The pre-screener only applies filters
# it can compute from cached OHLCV bars: price, volume, SMA relations, RSI,
# ATR%. Fundamental / catalyst filters are upstream of this agent.

SmaRelation = Literal["above", "below"]


class PrescreenCriteria(BaseModel):
    """Bar-derivable filter gates. Every field is optional — missing = no gate."""

    # Price window
    price_min: float | None = None
    price_max: float | None = None

    # Volume (20-bar SMA of daily volume)
    avg_volume_min: int | None = None

    # SMA relations
    sma20_relation: SmaRelation | None = None
    sma50_relation: SmaRelation | None = None
    sma200_relation: SmaRelation | None = None

    # RSI window
    rsi_min: float | None = None
    rsi_max: float | None = None

    # Volatility (ATR as % of close)
    atr_pct_min: float | None = None
    atr_pct_max: float | None = None


# --------------------------------------------------------------------------- #
# Ticker list (written by scripts/refresh_universe.py)
# --------------------------------------------------------------------------- #


class PresetTickers(BaseModel):
    """Refresh output: the ticker list a preset resolves to right now."""

    refreshed_at: str  # iso8601
    source: str = "manual"  # e.g. "finviz:...", "manual", "tradestation_scan"
    tickers: list[str] = Field(default_factory=list)


class PresetTickersFile(BaseModel):
    """Schema of ``universe_filter_presets_tickers.yaml``.

    Top-level keys are preset names; values are ``PresetTickers`` objects.
    """

    presets: dict[str, PresetTickers] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Run result (what universe_filter.run() returns)
# --------------------------------------------------------------------------- #


class PrescreenScore(BaseModel):
    symbol: str
    total: float
    momentum: float = 0.0
    volume: float = 0.0
    volatility: float = 0.0
    passed_filters: bool = True
    rejection_reason: str | None = None


class UniverseFilterResult(BaseModel):
    filter_id: str = Field(default_factory=lambda: str(uuid4()))
    ts_run: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    preset_name: str
    mode: Literal["research", "paper", "live"]
    as_of_ts: str | None = None  # iso8601 or None for live

    # Full filtered list (everyone who passed the hard filters)
    universe: list[str] = Field(default_factory=list)
    universe_size: int = 0

    # Ranked shortlist (top N by prescreen score — the analyst's workload)
    shortlist: list[str] = Field(default_factory=list)
    shortlist_size: int = 0

    # Counts + diagnostics
    total_screened: int = 0
    rejected_count: int = 0
    prescreener_scores: dict[str, float] = Field(default_factory=dict)
    rejection_reasons: dict[str, int] = Field(default_factory=dict)
    elevated_risk_symbols: list[str] = Field(default_factory=list)

    run_duration_seconds: float = 0.0
