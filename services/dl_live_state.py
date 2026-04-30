"""dl_live_state.py — evaluate a symbol's Double Lock state in real time.

Renders the four moving parts of the DL strategy as the trading day
progresses, so the UI can paint each symbol with the right color
(amber=forming, green=passed, red=failed, gray=pending):

    candle 1 (9:30-10:00)  — first 30m bar; checked for direction +
                             body strength + close position + volume
    candle 2 (10:00-10:30) — second 30m bar; direction confirmation
    regime                 — VIX prev close >= 20, ADX <= 35 on prior daily
    plan                   — armed plan in pending_approvals

This module is **read-only** — it never schedules orders or writes to
the alert table. It mirrors the gate logic of
``agents.lock1_scout.evaluate_lock1`` and ``agents.detectors.double_lock_filtered``;
the production fire path stays the only producer of plans and alerts.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as dtime, timezone
from typing import Any, Literal

import pandas as pd

from services import data_service

logger = logging.getLogger(__name__)


GateStatus = Literal["pending", "forming", "passed", "failed", "n/a"]


@dataclass
class LiveState:
    symbol: str
    as_of_iso: str

    # Phase rollup
    c1_status: GateStatus = "pending"
    c2_status: GateStatus = "pending"
    regime_status: GateStatus = "pending"

    # Direction inferred from c1 (and confirmed by c2 if direction matches)
    direction: Literal["long", "short", "unknown"] = "unknown"

    # Numeric details (for the card body)
    c1_open:  float | None = None
    c1_close: float | None = None
    c1_body_pct:   float | None = None
    c1_close_pct:  float | None = None
    c1_volume_ratio: float | None = None

    c2_open:  float | None = None
    c2_close: float | None = None
    c2_body_pct: float | None = None

    vix_prev_close: float | None = None
    vix_min:        float | None = None
    adx_d:          float | None = None
    adx_max:        float | None = None
    rsi_d:          float | None = None

    # Failure annotations — short human strings for the card to surface
    failures: list[str] = field(default_factory=list)

    # Armed plan (if pending_approvals has one for this symbol today)
    armed:           bool = False
    plan_id:         str | None = None
    entry_price:     float | None = None
    stop_price:      float | None = None
    eod_close_iso:   str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


async def evaluate_symbol(
    symbol: str,
    *,
    config: dict[str, Any] | None = None,
    now: pd.Timestamp | None = None,
) -> LiveState:
    """Evaluate one symbol's DL state. Failures surface as `failures`
    notes — the function never raises for missing data."""
    cfg = config or _DEFAULT_CONFIG
    t = cfg.get("thresholds", {}) or {}
    vix_min = float(t.get("vix_min", 20.0))
    adx_max = float(t.get("adx_max", 35.0))

    if now is None:
        now = pd.Timestamp.now(tz="UTC")
    elif now.tzinfo is None:
        now = now.tz_localize("UTC")

    state = LiveState(
        symbol=symbol.upper(),
        as_of_iso=now.isoformat(),
        vix_min=vix_min,
        adx_max=adx_max,
    )

    # ---- Bars ---------------------------------------------------------
    try:
        bars_30m = await data_service.get_bars(
            symbol, "30m", as_of_ts=now, min_bars=1, download_if_missing=False,
        )
    except Exception as exc:                                          # noqa: BLE001
        state.failures.append(f"no 30m bars: {exc}")
        return state

    # If today's bars aren't in the cache yet AND we're past 9:30 ET,
    # the cache is stale — yfinance updates with a slight lag. Force a
    # refresh so the live view actually shows live state.
    today_et = now.tz_convert("America/New_York").date()
    has_today_bar = False
    if len(bars_30m) > 0:
        idx_et = bars_30m.index.tz_convert("America/New_York")
        has_today_bar = bool((idx_et.date == today_et).any())
    if not has_today_bar and now.tz_convert("America/New_York").time() >= dtime(9, 30):
        try:
            bars_30m = await data_service.refresh_bars(symbol, "30m")
        except Exception as exc:                                      # noqa: BLE001
            state.failures.append(f"30m refresh failed: {exc}")

    try:
        daily = await data_service.get_bars(
            symbol, "1d", as_of_ts=now, min_bars=1, download_if_missing=False,
        )
    except Exception as exc:                                          # noqa: BLE001
        state.failures.append(f"no daily bars: {exc}")
        daily = None

    bars_30m_et = bars_30m.copy()
    if bars_30m_et.index.tz is None:
        bars_30m_et.index = bars_30m_et.index.tz_localize("UTC")
    bars_30m_et.index = bars_30m_et.index.tz_convert("America/New_York")

    today = now.tz_convert("America/New_York").date()
    today_bars = bars_30m_et[bars_30m_et.index.date == today]

    # ---- Regime gate (independent of c1/c2 timing) -------------------
    state.vix_prev_close = await _vix_prev_close(now)
    if daily is not None and len(daily) > 0:
        prev_daily = daily.iloc[-1]
        state.adx_d = _maybe_float(prev_daily.get("adx_14"))
        state.rsi_d = _maybe_float(prev_daily.get("rsi_14"))

    state.regime_status = _regime_status(state, vix_min=vix_min, adx_max=adx_max)

    # ---- c1 (9:30-10:00) ---------------------------------------------
    et_now = now.tz_convert("America/New_York")
    c1_window_close = et_now.replace(hour=10, minute=0, second=0, microsecond=0)
    c1 = _bar_at_slot(today_bars, dtime(9, 30))

    if c1 is None:
        if et_now < c1_window_close:
            state.c1_status = "forming" if et_now.time() >= dtime(9, 30) else "pending"
        else:
            state.c1_status = "n/a"
            state.failures.append("no 9:30 bar in cache")
    else:
        # If we're inside the c1 window AND the bar is the only 'today' bar
        # we have, treat it as forming (yfinance returns the in-progress bar).
        if et_now < c1_window_close:
            state.c1_status = "forming"
        else:
            ok, fails = _check_c1(c1, today_bars, bars_30m_et, t)
            state.c1_status = "passed" if ok else "failed"
            if fails:
                state.failures.extend(f"c1: {f}" for f in fails)
        _populate_c1_metrics(state, c1, bars_30m_et)

    # ---- c2 (10:00-10:30) --------------------------------------------
    c2_window_close = et_now.replace(hour=10, minute=30, second=0, microsecond=0)
    c2 = _bar_at_slot(today_bars, dtime(10, 0))

    if c2 is None:
        if et_now < et_now.replace(hour=10, minute=0, second=0, microsecond=0):
            state.c2_status = "pending"
        elif et_now < c2_window_close:
            state.c2_status = "forming"
        else:
            state.c2_status = "n/a"
    else:
        if et_now < c2_window_close:
            state.c2_status = "forming"
        else:
            ok, fails = _check_c2(c1, c2, t)
            state.c2_status = "passed" if ok else "failed"
            if fails:
                state.failures.extend(f"c2: {f}" for f in fails)
        _populate_c2_metrics(state, c2)

    # ---- Direction inference -----------------------------------------
    if c1 is not None:
        try:
            o, c = float(c1["open"]), float(c1["close"])
            state.direction = "long" if c > o else ("short" if c < o else "unknown")
        except Exception:                                             # noqa: BLE001
            pass

    # ---- Armed plan (from pending_approvals) -------------------------
    await _attach_armed_plan(state, today_iso=str(today))

    return state


# --------------------------------------------------------------------------- #
# Internal: gate logic (mirrors lock1_scout + double_lock_filtered)
# --------------------------------------------------------------------------- #


def _check_c1(
    c1: pd.Series,
    today_bars: pd.DataFrame,
    bars_30m_et: pd.DataFrame,
    t: dict[str, Any],
) -> tuple[bool, list[str]]:
    body_pct_thr = float(t.get("body_pct", 0.5))
    press_hi     = float(t.get("press_hi", 0.5))
    press_lo     = float(t.get("press_lo", 0.5))
    vol_mult     = float(t.get("vol_mult", 1.2))

    failures: list[str] = []
    o, h, l, c, v = (
        float(c1["open"]), float(c1["high"]), float(c1["low"]),
        float(c1["close"]), float(c1["volume"]),
    )
    rng = h - l
    if rng <= 0:
        return False, ["zero-range candle"]

    body = abs(c - o) / rng
    cp = (c - l) / rng

    same_slot = bars_30m_et[bars_30m_et.index.time == dtime(9, 30)]
    slot_med = float(same_slot["volume"].median()) if len(same_slot) else 0.0
    vol_ratio = (v / slot_med) if slot_med > 0 else 0.0

    if body < body_pct_thr:
        failures.append(f"body {body:.2f} < {body_pct_thr:.2f}")
    if c > o:                # bull lock — close near top
        if cp < press_hi:
            failures.append(f"close-pos {cp:.2f} < {press_hi:.2f}")
    elif c < o:              # bear lock — close near bottom
        if cp > press_lo:
            failures.append(f"close-pos {cp:.2f} > {press_lo:.2f}")
    else:
        failures.append("indecisive (open == close)")
    if vol_ratio < vol_mult:
        failures.append(f"volume {vol_ratio:.2f}x < {vol_mult:.2f}x")

    return (not failures), failures


def _check_c2(
    c1: pd.Series | None,
    c2: pd.Series,
    t: dict[str, Any],
) -> tuple[bool, list[str]]:
    body_pct_thr = float(t.get("body_pct", 0.5))
    failures: list[str] = []
    o, h, l, c = (
        float(c2["open"]), float(c2["high"]),
        float(c2["low"]),  float(c2["close"]),
    )
    rng = h - l
    if rng <= 0:
        return False, ["zero-range candle"]
    body = abs(c - o) / rng
    if body < body_pct_thr:
        failures.append(f"body {body:.2f} < {body_pct_thr:.2f}")

    if c1 is not None:
        c1_dir = (
            "long" if c1["close"] > c1["open"]
            else "short" if c1["close"] < c1["open"] else "neutral"
        )
        c2_dir = "long" if c > o else "short" if c < o else "neutral"
        if c1_dir != c2_dir:
            failures.append(f"direction mismatch (c1={c1_dir}, c2={c2_dir})")

    return (not failures), failures


def _regime_status(
    state: LiveState, *, vix_min: float, adx_max: float,
) -> GateStatus:
    fails: list[str] = []
    if state.vix_prev_close is None:
        return "pending"
    if state.vix_prev_close < vix_min:
        fails.append(f"VIX {state.vix_prev_close:.2f} < {vix_min:.0f}")
    if state.adx_d is not None and state.adx_d > adx_max:
        fails.append(f"ADX {state.adx_d:.1f} > {adx_max:.0f}")
    if fails:
        state.failures.extend(f"regime: {f}" for f in fails)
        return "failed"
    return "passed"


def _bar_at_slot(today_bars: pd.DataFrame, target: dtime) -> pd.Series | None:
    if len(today_bars) == 0:
        return None
    matches = today_bars[today_bars.index.time == target]
    if len(matches) == 0:
        return None
    return matches.iloc[0]


def _populate_c1_metrics(
    state: LiveState, c1: pd.Series, bars_30m_et: pd.DataFrame,
) -> None:
    o, h, l, c, v = (
        float(c1["open"]), float(c1["high"]), float(c1["low"]),
        float(c1["close"]), float(c1["volume"]),
    )
    rng = h - l
    state.c1_open  = round(o, 2)
    state.c1_close = round(c, 2)
    if rng > 0:
        state.c1_body_pct  = round(abs(c - o) / rng, 3)
        state.c1_close_pct = round((c - l) / rng, 3)

    same_slot = bars_30m_et[bars_30m_et.index.time == dtime(9, 30)]
    slot_med = float(same_slot["volume"].median()) if len(same_slot) else 0.0
    if slot_med > 0:
        state.c1_volume_ratio = round(v / slot_med, 2)


def _populate_c2_metrics(state: LiveState, c2: pd.Series) -> None:
    o, h, l, c = (
        float(c2["open"]), float(c2["high"]),
        float(c2["low"]),  float(c2["close"]),
    )
    rng = h - l
    state.c2_open  = round(o, 2)
    state.c2_close = round(c, 2)
    if rng > 0:
        state.c2_body_pct = round(abs(c - o) / rng, 3)


# --------------------------------------------------------------------------- #
# Internal: VIX prev close + armed-plan lookup
# --------------------------------------------------------------------------- #


async def _vix_prev_close(now: pd.Timestamp) -> float | None:
    """Read VIX prev daily close from the cache. Returns None if missing."""
    try:
        vix = await data_service.get_bars(
            "^VIX", "1d", as_of_ts=now, min_bars=1, download_if_missing=False,
        )
        if len(vix) == 0:
            return None
        return float(vix.iloc[-1]["close"])
    except Exception:                                                 # noqa: BLE001
        try:
            vix = await data_service.get_bars(
                "VIX", "1d", as_of_ts=now, min_bars=1,
                download_if_missing=False,
            )
            return float(vix.iloc[-1]["close"]) if len(vix) else None
        except Exception:                                             # noqa: BLE001
            return None


async def _attach_armed_plan(state: LiveState, *, today_iso: str) -> None:
    """Look up today's pending_approvals row for this symbol, if any."""
    try:
        from services import db_service
        plans = await db_service.get_pending_plans(status_filter=None, limit=200)
    except Exception:                                                 # noqa: BLE001
        return

    # Filter to today's plans for this symbol — we don't want yesterday's
    # expired plan painting today's chart.
    for p in plans:
        if (p.get("symbol") or "").upper() != state.symbol:
            continue
        ts_created = (p.get("ts_created") or "")
        if not ts_created.startswith(today_iso):
            continue
        if p.get("status") in ("rejected", "expired"):
            continue
        state.armed = True
        state.plan_id = p.get("plan_id")
        state.entry_price = _maybe_float(p.get("entry"))
        state.stop_price  = _maybe_float(p.get("stop"))
        # eod_close_iso comes from the plan's time_stop deadline
        plan_json = p.get("plan_json") or {}
        try:
            import json as _json
            if isinstance(plan_json, str):
                plan_json = _json.loads(plan_json)
        except Exception:                                             # noqa: BLE001
            plan_json = {}
        ts = (
            plan_json.get("setup", {})
            .get("stop_loss", {}).get("time_stop", {})
            .get("deadline")
        )
        state.eod_close_iso = ts
        break


def _maybe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Default config — keeps in sync with strategy_configs/*.yaml
# --------------------------------------------------------------------------- #


_DEFAULT_CONFIG: dict[str, Any] = {
    "thresholds": {
        "body_pct":     0.5,
        "press_hi":     0.5,
        "press_lo":     0.5,
        "vol_mult":     1.2,
        "vix_min":      20.0,
        "adx_max":      35.0,
        "rsi_long_lo":  40.0,
        "rsi_long_hi":  65.0,
        "rsi_short_lo": 20.0,
        "rsi_short_hi": 40.0,
    },
}


def _load_config_from_yaml() -> dict[str, Any]:
    """Best-effort load of the actual strategy YAML if present."""
    try:
        from pathlib import Path
        import yaml
        from services.settings_service import PROJECT_ROOT
        path = Path(PROJECT_ROOT) / "strategy_configs" / "double_lock_filtered.yaml"
        if path.exists():
            return yaml.safe_load(path.read_text())
    except Exception as exc:                                          # noqa: BLE001
        logger.debug("dl_live_state: yaml load failed (%s); using defaults", exc)
    return _DEFAULT_CONFIG
