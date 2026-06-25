"""research router — pages for the strategy-research subsystem.

Currently exposes /research/explosive-moves: a sortable, filterable table
view of the explosive first-hour moves identified by
scripts/find_explosive_first_hour.py. Reads the persisted CSV at
data/state_memory/explosive_first_hour.csv (refreshed by re-running the
scanner).

Each row has a click-out to TradingView's chart at the right symbol +
30-minute interval centered on the explosive day, so the user can verify
what the data thinks is "explosive" against what the chart actually shows.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services.settings_service import PROJECT_ROOT, TEMPLATES_DIR, Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)

EXPLOSIVE_CSV = PROJECT_ROOT / "data" / "state_memory" / "explosive_first_hour.csv"


def _safe_float(x: Any) -> float | None:
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return None
        return float(x)
    except Exception:
        return None


def _load_hits() -> pd.DataFrame:
    if not EXPLOSIVE_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(EXPLOSIVE_CSV)
    # Normalize types
    for col in ("is_earnings_day", "is_split_day", "is_dividend_day"):
        if col in df.columns:
            df[col] = df[col].fillna(False).astype(bool)
    return df


def _apply_filters(
    df: pd.DataFrame,
    *,
    symbol: str | None,
    direction: str | None,
    triggers_contains: str | None,
    earnings: str | None,
    outcome: str | None,
    min_abs_z: float | None,
    min_consol: float | None,
    date_from: str | None,
    date_to: str | None,
) -> pd.DataFrame:
    out = df
    if symbol:
        out = out[out["symbol"].str.upper() == symbol.strip().upper()]
    if direction in ("UP", "DOWN"):
        out = out[out["direction"] == direction]
    if triggers_contains:
        out = out[out["triggers"].fillna("").str.contains(triggers_contains.upper(), regex=False)]
    if earnings == "yes":
        out = out[out["is_earnings_day"]]
    elif earnings == "no":
        out = out[~out["is_earnings_day"]]
    if outcome and outcome != "any" and "outcome_label" in out.columns:
        out = out[out["outcome_label"] == outcome]
    if min_abs_z is not None:
        out = out[out["first_return_z"].abs() >= float(min_abs_z)]
    if min_consol is not None and "consolidation_score" in out.columns:
        out = out[out["consolidation_score"].fillna(0) >= float(min_consol)]
    if date_from:
        out = out[out["date"] >= date_from]
    if date_to:
        out = out[out["date"] <= date_to]
    return out


def _make_tv_url(symbol: str, date_str: str) -> str:
    """Build a TradingView 30m chart deep-link.

    TV doesn't support a true "scroll to date" param via plain URLs, but
    https://www.tradingview.com/chart/?symbol=NASDAQ:NVDA&interval=30 will
    open a 30-minute chart on the symbol; the user navigates manually.
    """
    return f"https://www.tradingview.com/chart/?symbol={symbol}&interval=30"


@router.get("/research/explosive-moves", response_class=HTMLResponse)
async def explosive_moves_page(
    request: Request,
    symbol: str = Query("", alias="symbol"),
    direction: str = Query("any"),
    triggers: str = Query("any"),
    earnings: str = Query("any"),
    outcome: str = Query("any"),
    min_abs_z: float = Query(3.0),
    min_consol: float = Query(0.0),
    date_from: str = Query(""),
    date_to: str = Query(""),
    sort: str = Query("abs_z"),
    desc: int = Query(1),
    limit: int = Query(200, ge=10, le=2000),
    settings: Settings = Depends(get_settings),
):
    df = _load_hits()
    csv_exists = not df.empty
    n_total = len(df)
    n_symbols = df["symbol"].nunique() if csv_exists else 0

    if csv_exists:
        df = _apply_filters(
            df,
            symbol=symbol or None,
            direction=direction if direction in ("UP", "DOWN") else None,
            triggers_contains=triggers if triggers != "any" else None,
            earnings=earnings if earnings in ("yes", "no") else None,
            outcome=outcome,
            min_abs_z=min_abs_z if min_abs_z is not None else None,
            min_consol=min_consol if min_consol > 0 else None,
            date_from=date_from or None,
            date_to=date_to or None,
        )
        df["abs_z"] = df["first_return_z"].abs()
        sort_col = sort if sort in df.columns else "abs_z"
        df = df.sort_values(sort_col, ascending=not desc, na_position="last")
        df = df.head(limit)

    n_filtered = len(df)

    # Tally by trigger and label
    trigger_breakdown: dict[str, int] = {}
    outcome_breakdown: dict[str, int] = {}
    if csv_exists and n_filtered:
        trigger_breakdown = df["triggers"].value_counts().to_dict()
        if "outcome_label" in df.columns:
            outcome_breakdown = df["outcome_label"].value_counts().to_dict()

    rows: list[dict] = []
    for _, r in df.iterrows():
        rows.append({
            "symbol": r["symbol"],
            "date": r["date"],
            "direction": r["direction"],
            "triggers": r.get("triggers", ""),
            "first_return_pct": _safe_float(r.get("first_return_pct")),
            "first_return_z":   _safe_float(r.get("first_return_z")),
            "first_range_pct":  _safe_float(r.get("first_range_pct")),
            "first_range_z":    _safe_float(r.get("first_range_z")),
            "gap_pct":          _safe_float(r.get("gap_pct")),
            "gap_z":            _safe_float(r.get("gap_z")),
            "consolidation_score": _safe_float(r.get("consolidation_score")),
            "atr_contraction":     _safe_float(r.get("atr_contraction")),
            "sma9_sma20_spread_pct": _safe_float(r.get("sma9_sma20_spread_pct")),
            "volume_z_5d":         _safe_float(r.get("volume_z_5d")),
            "is_earnings_day":     bool(r.get("is_earnings_day", False)),
            "is_split_day":        bool(r.get("is_split_day", False)),
            "is_dividend_day":     bool(r.get("is_dividend_day", False)),
            "outcome_label":       r.get("outcome_label", "UNKNOWN"),
            "outcome_1d_pct":      _safe_float(r.get("outcome_1d_pct")),
            "outcome_5d_pct":      _safe_float(r.get("outcome_5d_pct")),
            "max_favorable_5d_pct": _safe_float(r.get("max_favorable_5d_pct")),
            "max_adverse_5d_pct":   _safe_float(r.get("max_adverse_5d_pct")),
            "tv_url": _make_tv_url(r["symbol"], r["date"]),
        })

    return templates.TemplateResponse(
        request=request,
        name="research/explosive_moves.html",
        context={
            "settings": settings,
            "app_version": "0.1.0",
            "active_page": "research_explosive",
            "active_section": "research",
            "csv_exists": csv_exists,
            "csv_path": str(EXPLOSIVE_CSV.relative_to(PROJECT_ROOT)),
            "n_total": n_total,
            "n_filtered": n_filtered,
            "n_symbols": n_symbols,
            "rows": rows,
            "filters": {
                "symbol": symbol,
                "direction": direction,
                "triggers": triggers,
                "earnings": earnings,
                "outcome": outcome,
                "min_abs_z": min_abs_z,
                "min_consol": min_consol,
                "date_from": date_from,
                "date_to": date_to,
                "sort": sort,
                "desc": desc,
                "limit": limit,
            },
            "trigger_breakdown": trigger_breakdown,
            "outcome_breakdown": outcome_breakdown,
        },
    )
