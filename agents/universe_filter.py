"""universe_filter.py — preset-driven shortlist generator.

Flow
----
1. Load the preset's filter criteria and ticker list.
   Priority: SQLite (UI-managed presets) → legacy YAML files.
2. For every ticker, fetch daily bars via ``data_service.get_bars`` at
   ``as_of_ts`` (live → None, backtest → historical ts).
3. Append indicators, apply hard filters (price / volume / SMA / RSI / ATR).
4. Score the survivors on momentum + volume + volatility (0–100).
5. Return the top ``shortlist_size`` symbols in the
   ``UniverseFilterResult``.

SQLite presets (created via /universe UI)
-----------------------------------------
When a preset exists in SQLite and has saved tickers, this agent reads from
there instead of the legacy YAML files.  Filter criteria are derived from the
Finviz filter strings stored in the preset (e.g. ``sh_price=o10`` →
``price_min=10``, ``ta_sma50=pa`` → ``sma50_relation="above"``).

Pure-function contract
----------------------
No wall-clock calls, no Finviz or broker calls — this agent only reads:
  * SQLite preset (via universe_service) or the two legacy YAML files
  * cached bars via ``data_service.get_bars(..., as_of_ts=as_of_ts)``

That makes it replayable under Phase 5.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from models.universe import (
    PrescreenCriteria,
    PrescreenScore,
    PresetTickers,
    UniverseFilterResult,
)
from services.data_service import DataNotAvailableError, get_bars_multi
from services.indicator_service import add_indicators
from services.settings_service import (
    PROJECT_ROOT,
    Settings,
)

logger = logging.getLogger(__name__)

# Default file locations — overridable for tests.
CRITERIA_FILE_DEFAULT: Path = PROJECT_ROOT / "universe_filter_presets.yaml"
TICKERS_FILE_DEFAULT: Path = PROJECT_ROOT / "universe_filter_presets_tickers.yaml"

DEFAULT_SHORTLIST_SIZE = 50
MIN_BARS_FOR_PRESCREEN = 210  # enough for sma_200 + buffer

# sh_avgvol option value → absolute share volume
_AVGVOL_MAP: dict[str, int] = {
    "o50": 50_000, "o100": 100_000, "o200": 200_000, "o300": 300_000,
    "o400": 400_000, "o500": 500_000, "o750": 750_000,
    "o1000": 1_000_000, "o2000": 2_000_000,
}

# ta_rsi option value → (rsi_min, rsi_max)
_RSI_MAP: dict[str, tuple[float | None, float | None]] = {
    "ob90": (90.0, None), "ob80": (80.0, None),
    "ob70": (70.0, None), "ob60": (60.0, None),
    "os40": (None, 40.0), "os30": (None, 30.0),
    "os20": (None, 20.0), "os10": (None, 10.0),
    "nob60": (None, 60.0), "nob50": (None, 50.0),
    "nos50": (50.0, None), "nos40": (40.0, None),
}


def _finviz_to_criteria(filters: dict[str, str]) -> PrescreenCriteria:
    """Translate Finviz filter param strings to PrescreenCriteria.

    Covers filters that map cleanly to the in-process screener's numeric gates.
    ATR is skipped: Finviz uses absolute $ while PrescreenCriteria needs atr_pct.
    """
    kw: dict[str, Any] = {}

    v = filters.get("sh_price", "")
    if v.startswith("o"):
        try: kw["price_min"] = float(v[1:])
        except ValueError: pass
    elif v.startswith("u"):
        try: kw["price_max"] = float(v[1:])
        except ValueError: pass
    elif "to" in v:
        lo, hi = v.split("to", 1)
        try: kw["price_min"] = float(lo)
        except ValueError: pass
        try: kw["price_max"] = float(hi)
        except ValueError: pass

    v = filters.get("sh_avgvol", "")
    if v in _AVGVOL_MAP:
        kw["avg_volume_min"] = _AVGVOL_MAP[v]

    for fid, key in (
        ("ta_sma20", "sma20_relation"),
        ("ta_sma50", "sma50_relation"),
        ("ta_sma200", "sma200_relation"),
    ):
        v = filters.get(fid, "")
        if v.startswith("pa"):
            kw[key] = "above"
        elif v.startswith("pb"):
            kw[key] = "below"

    v = filters.get("ta_rsi", "")
    if v in _RSI_MAP:
        rmin, rmax = _RSI_MAP[v]
        if rmin is not None:
            kw["rsi_min"] = rmin
        if rmax is not None:
            kw["rsi_max"] = rmax

    return PrescreenCriteria(**kw)


async def _load_sqlite_preset(
    preset_name: str,
) -> tuple[PresetTickers, PrescreenCriteria, list[str], list[str]] | None:
    """Return (tickers, criteria, elev_sectors, elev_industries) from SQLite.

    Returns None if the preset doesn't exist in SQLite or has no saved tickers.
    """
    from services import universe_service  # local import avoids circular at module load
    preset = await universe_service.get_preset_db(preset_name)
    if preset is None or not preset.get("tickers"):
        return None
    tickers_obj = PresetTickers(tickers=preset["tickers"])
    criteria = _finviz_to_criteria(preset.get("filters") or {})
    return tickers_obj, criteria, [], []


# --------------------------------------------------------------------------- #
# Criteria loader — maps the rich YAML into the subset we pre-screen on
# --------------------------------------------------------------------------- #


def _load_criteria(
    preset_name: str,
    criteria_file: Path = CRITERIA_FILE_DEFAULT,
) -> tuple[PrescreenCriteria, list[str], list[str]]:
    """Return (prescreen_criteria, elevated_risk_sectors, elevated_risk_industries).

    Parses the multi-doc universe_filter_presets.yaml and picks the doc
    whose ``preset_name`` matches. Raises KeyError if the preset isn't there.
    """
    text = criteria_file.read_text(encoding="utf-8")
    for doc in yaml.safe_load_all(text):
        if not isinstance(doc, dict):
            continue
        if doc.get("preset_name") != preset_name:
            continue
        raw = doc.get("criteria", {}) or {}
        pc = PrescreenCriteria(
            price_min=raw.get("price_min"),
            price_max=raw.get("price_max"),
            avg_volume_min=raw.get("avg_volume_min"),
            sma20_relation=raw.get("sma20_relation"),
            sma50_relation=raw.get("sma50_relation"),
            sma200_relation=raw.get("sma200_relation"),
            rsi_min=raw.get("rsi_min"),
            rsi_max=raw.get("rsi_max"),
            atr_pct_min=raw.get("atr_pct_min"),
            atr_pct_max=raw.get("atr_pct_max"),
        )
        return (
            pc,
            list(doc.get("elevated_risk_sectors") or []),
            list(doc.get("elevated_risk_industries") or []),
        )
    raise KeyError(f"preset {preset_name!r} not found in {criteria_file}")


def _load_tickers(
    preset_name: str,
    tickers_file: Path = TICKERS_FILE_DEFAULT,
) -> PresetTickers:
    text = tickers_file.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    presets = data.get("presets", {}) or {}
    raw = presets.get(preset_name)
    if raw is None:
        raise KeyError(f"preset {preset_name!r} not found in {tickers_file}")
    return PresetTickers.model_validate(raw)


# --------------------------------------------------------------------------- #
# Hard-filter gates — return None if pass, else a rejection reason string
# --------------------------------------------------------------------------- #


def _apply_filters(row: pd.Series, c: PrescreenCriteria) -> str | None:
    close = float(row["close"])
    if c.price_min is not None and close < c.price_min:
        return "price_below_min"
    if c.price_max is not None and close > c.price_max:
        return "price_above_max"

    vol_sma = float(row.get("volume_sma_20", 0.0))
    if c.avg_volume_min is not None and vol_sma < c.avg_volume_min:
        return "avg_volume_below_min"

    if c.sma20_relation:
        sma20 = float(row.get("sma_20", float("nan")))
        if pd.isna(sma20):
            return "sma20_unavailable"
        if c.sma20_relation == "above" and close <= sma20:
            return "sma20_not_above"
        if c.sma20_relation == "below" and close >= sma20:
            return "sma20_not_below"

    if c.sma50_relation:
        sma50 = float(row.get("sma_50", float("nan")))
        if pd.isna(sma50):
            return "sma50_unavailable"
        if c.sma50_relation == "above" and close <= sma50:
            return "sma50_not_above"
        if c.sma50_relation == "below" and close >= sma50:
            return "sma50_not_below"

    if c.sma200_relation:
        sma200 = float(row.get("sma_200", float("nan")))
        if pd.isna(sma200):
            return "sma200_unavailable"
        if c.sma200_relation == "above" and close <= sma200:
            return "sma200_not_above"
        if c.sma200_relation == "below" and close >= sma200:
            return "sma200_not_below"

    rsi = float(row.get("rsi_14", float("nan")))
    if pd.isna(rsi):
        return "rsi_unavailable"
    if c.rsi_min is not None and rsi < c.rsi_min:
        return "rsi_below_min"
    if c.rsi_max is not None and rsi > c.rsi_max:
        return "rsi_above_max"

    atr_pct = float(row.get("atr_14_pct", float("nan")))
    if pd.isna(atr_pct):
        return "atr_pct_unavailable"
    if c.atr_pct_min is not None and atr_pct < c.atr_pct_min:
        return "atr_pct_below_min"
    if c.atr_pct_max is not None and atr_pct > c.atr_pct_max:
        return "atr_pct_above_max"

    return None


# --------------------------------------------------------------------------- #
# Scoring — momentum / volume / volatility, 0-100
# --------------------------------------------------------------------------- #


def _score(row: pd.Series) -> PrescreenScore:
    close = float(row["close"])
    sma20 = float(row.get("sma_20", float("nan")))
    sma50 = float(row.get("sma_50", float("nan")))
    sma200 = float(row.get("sma_200", float("nan")))
    vol_ratio = float(row.get("volume_ratio", float("nan")))
    vol_sma = float(row.get("volume_sma_20", 0.0))
    atr_pct = float(row.get("atr_14_pct", float("nan")))

    # Momentum: SMA ladder, max 40
    momentum = 0.0
    if not pd.isna(sma20) and close > sma20:
        momentum += 10
    if not pd.isna(sma50) and close > sma50:
        momentum += 15
    if not pd.isna(sma200) and close > sma200:
        momentum += 15

    # Volume: relative vol vs 20-day SMA, max 30
    volume = 0.0
    if not pd.isna(vol_ratio):
        if vol_ratio >= 2.0:
            volume += 30
        elif vol_ratio >= 1.5:
            volume += 15
    if vol_sma >= 10_000_000:
        # Keep the +10 nudge even if volume gate isn't tripped today —
        # liquid names deserve a tiebreaker against equally scored thinner
        # names. Cap at 30 total so the band stays honest.
        volume = min(30.0, volume + 10.0)

    # Volatility: ATR% band, max 30
    volatility = 0.0
    if not pd.isna(atr_pct):
        if 1.5 <= atr_pct <= 5.0:
            volatility = 30
        elif 1.0 <= atr_pct < 1.5 or 5.0 < atr_pct <= 8.0:
            volatility = 15

    total = momentum + volume + volatility
    return PrescreenScore(
        symbol=str(row.name) if row.name else "",
        total=total,
        momentum=momentum,
        volume=volume,
        volatility=volatility,
    )


# --------------------------------------------------------------------------- #
# Agent class
# --------------------------------------------------------------------------- #


class UniverseFilter:
    """Preset → ranked shortlist. Pure function of cached bars + YAML state."""

    def __init__(
        self,
        settings: Settings,
        criteria_file: Path = CRITERIA_FILE_DEFAULT,
        tickers_file: Path = TICKERS_FILE_DEFAULT,
    ) -> None:
        self._settings = settings
        self._criteria_file = criteria_file
        self._tickers_file = tickers_file

    async def run(
        self,
        preset_name: str,
        as_of_ts: pd.Timestamp | None = None,
        shortlist_size: int = DEFAULT_SHORTLIST_SIZE,
        min_bars: int = MIN_BARS_FOR_PRESCREEN,
    ) -> UniverseFilterResult:
        t0 = time.perf_counter()
        mode = self._settings.app.mode

        # Prefer SQLite preset (UI-managed); fall back to legacy YAML files.
        sqlite_data = await _load_sqlite_preset(preset_name)
        if sqlite_data is not None:
            preset_tickers, criteria, elev_sectors, elev_industries = sqlite_data
            logger.info(
                "UniverseFilter %r: loaded from SQLite (%d tickers)",
                preset_name, len(preset_tickers.tickers),
            )
        else:
            criteria, elev_sectors, elev_industries = _load_criteria(
                preset_name, self._criteria_file,
            )
            preset_tickers = _load_tickers(preset_name, self._tickers_file)
            logger.info(
                "UniverseFilter %r: loaded from YAML (%d tickers)",
                preset_name, len(preset_tickers.tickers),
            )
        tickers = [t.upper() for t in preset_tickers.tickers]

        if not tickers:
            logger.warning(
                "Preset %r has an empty ticker list — returning empty shortlist. "
                "Run scripts/refresh_universe.py to populate.",
                preset_name,
            )
            return UniverseFilterResult(
                preset_name=preset_name,
                mode=mode,
                as_of_ts=as_of_ts.isoformat() if as_of_ts is not None else None,
                total_screened=0,
                run_duration_seconds=time.perf_counter() - t0,
            )

        # Batch-fetch daily bars. Per-symbol errors are already logged and
        # dropped by get_bars_multi.
        bars_by_symbol = await get_bars_multi(
            tickers, "1d",
            as_of_ts=as_of_ts,
            min_bars=min_bars,
        )

        passed: list[PrescreenScore] = []
        rejection_counts: dict[str, int] = {}
        rejection_counts["no_bars"] = len(tickers) - len(bars_by_symbol)

        for symbol in tickers:
            df = bars_by_symbol.get(symbol)
            if df is None:
                continue
            try:
                enriched = add_indicators(df)
            except Exception as e:  # noqa: BLE001
                logger.warning("add_indicators failed for %s: %s", symbol, e)
                rejection_counts["indicator_error"] = (
                    rejection_counts.get("indicator_error", 0) + 1
                )
                continue

            # Last row is the "current" snapshot at as_of_ts
            if enriched.empty:
                rejection_counts["empty_bars"] = (
                    rejection_counts.get("empty_bars", 0) + 1
                )
                continue
            row = enriched.iloc[-1]
            row.name = symbol  # so _score knows the ticker

            reason = _apply_filters(row, criteria)
            if reason is not None:
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
                continue

            passed.append(_score(row))

        # Rank: score desc, volume score tie-breaker
        passed.sort(key=lambda s: (s.total, s.volume), reverse=True)
        shortlist = [s.symbol for s in passed[:shortlist_size]]
        universe = [s.symbol for s in passed]

        duration = time.perf_counter() - t0
        result = UniverseFilterResult(
            preset_name=preset_name,
            mode=mode,
            as_of_ts=as_of_ts.isoformat() if as_of_ts is not None else None,
            universe=universe,
            universe_size=len(universe),
            shortlist=shortlist,
            shortlist_size=len(shortlist),
            total_screened=len(tickers),
            rejected_count=len(tickers) - len(passed),
            prescreener_scores={s.symbol: s.total for s in passed},
            rejection_reasons={k: v for k, v in rejection_counts.items() if v > 0},
            run_duration_seconds=round(duration, 3),
        )
        logger.info(
            "UniverseFilter %s: %d screened → %d passed → %d shortlist (%.2fs)",
            preset_name, len(tickers), len(passed), len(shortlist), duration,
        )
        return result
