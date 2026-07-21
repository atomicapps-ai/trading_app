"""fvg_scan_service.py — turn the validated FVG-continuation setup into
pending TradePlans the operator can view / modify / manage in the UI.

The equity strategies scan daily bars through the workflow engine
(filter_universe → analyze → plan). FVG doesn't fit that mould: it is an
*intraday, session-based* FX/gold strategy (Asia range → London sweep →
NY reversal → displacement FVG). So instead of the daily detector path we
reuse the exact validated session logic in ``scripts/replay_fvg`` and wrap
its most-recent-session output as a TradePlan.

Flow (mirrors pipeline_service so the UI is identical):
    for each configured symbol:
        evaluate the latest completed NY session via replay_fvg
        if a fresh setup fired -> build a forex TradePlan
        run ComplianceOfficer (C1-C8) then RiskManager (R1-R9)
        upsert to pending_approvals (strategy="fvg_continuation")
    record a pipeline_run for the history view

Data source is transparent: ``replay_fvg._load`` reads
``data/historical/{SYM}_30m.csv`` — populated from HistData for backtest,
or refreshed from IBKR once the live broker is wired. This service is
broker-agnostic; it only produces plans + runs gates.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import yaml

from agents.compliance_officer import ComplianceOfficer
from agents.risk_manager import RiskManager
from models.trade_plan import (
    EntryOrder, Setup, StopLoss, StopLossInitial, TakeProfitLeg,
    ThesisInvalidation, TimeStop, TradePlan, TrailingStop,
)
from services import db_service
from services.broker_service import get_adapter
from services.settings_service import DATA_DIR, STRATEGY_CONFIG_DIR, Settings, get_settings

logger = logging.getLogger(__name__)

STRATEGY = "fvg_continuation"
# Where replay_fvg._load reads its 30m bars — the same cache the IBKR refresh
# writes into so a live "Run" evaluates the CURRENT session.
HIST_DIR = DATA_DIR / "historical"
# Gold is the source instrument + best config; the 9 FX majors are the
# validated breadth set. Operator-selected: gold + 9 FX.
DEFAULT_SYMBOLS = [
    "XAUUSD", "EURUSD", "USDJPY", "EURJPY", "GBPJPY",
    "AUDJPY", "EURAUD", "EURCAD", "GBPUSD", "AUDUSD",
]
# Only surface a setup whose session is this recent (calendar days), so a
# stale cache doesn't queue a week-old entry as if it were live.
FRESHNESS_DAYS = 4


def _load_config() -> dict:
    path = STRATEGY_CONFIG_DIR / f"{STRATEGY}.yaml"
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("fvg_scan: bad config: %s", e)
        return {}


def _symbols(cfg: dict) -> list[str]:
    uni = list(cfg.get("universe") or [])
    syms = ["XAUUSD"] + [s.upper() for s in uni]
    # de-dupe, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for s in syms:
        if s not in seen:
            seen.add(s); out.append(s)
    return out or DEFAULT_SYMBOLS


def _round_px(symbol: str, px: float) -> float:
    """FX quotes carry more precision than equities. JPY pairs 3dp, gold
    2dp, other FX 5dp. Never the equity 2dp that would flatten 1.16849."""
    s = symbol.upper()
    if s.startswith("XAU") or s.startswith("XAG"):
        return round(px, 2)
    if s.endswith("JPY"):
        return round(px, 3)
    return round(px, 5)


def _build_plan(trade, symbol: str, equity: float, mode: str,
                risk_pct: float) -> TradePlan | None:
    """Wrap a replay_fvg SwingTrade (the latest session's setup) as a
    forex TradePlan. We take only entry/stop/tp/direction from the replay —
    the simulated exit is irrelevant to a forward-looking plan."""
    import math

    direction = trade.direction  # "long" | "short"
    entry = float(trade.entry)
    stop = float(trade.stop)
    tp = float(trade.tp) if trade.tp is not None else None
    r_per_unit = abs(entry - stop)
    if r_per_unit <= 0 or tp is None:
        return None

    # Risk-based sizing in units (FX/gold trade in units/oz, not "shares").
    # position_risk_usd == units * r_per_unit ≈ the risk budget, so the R
    # gates stay internally consistent; they may still resize on notional.
    cap_usd = equity * risk_pct / 100.0 if equity > 0 else 0.0
    units = max(0, math.floor(cap_usd / r_per_unit)) if r_per_unit else 0
    if units <= 0:
        return None
    notional = units * entry
    position_risk_usd = units * r_per_unit
    r_to_tp = (abs(tp - entry) / r_per_unit) if r_per_unit else 0.0

    entry_order = EntryOrder(
        type="market_on_trigger",
        price=_round_px(symbol, entry),
        trigger_condition="displacement FVG confirmed beyond ORB in bias direction",
        valid_until="session_close",
    )
    stop_loss = StopLoss(
        initial=StopLossInitial(
            type="hard", price=_round_px(symbol, stop),
            reason="far edge of the displacement gap",
        ),
        trail=TrailingStop(active=False, activate_after="", mode="atr"),
        time_stop=TimeStop(
            active=True, condition="flat at NY session close (16:00 ET)",
            deadline=_session_close_utc(),
        ),
        thesis_invalidation=ThesisInvalidation(
            active=True, condition="price closes beyond the gap far edge",
        ),
    )
    take_profit = [TakeProfitLeg(
        leg=1, price=_round_px(symbol, tp), size_pct=100,
        reason="fixed 3R target",
    )]
    setup = Setup(direction=direction, entry=entry_order,
                  take_profit=take_profit, stop_loss=stop_loss)

    asset = "commodity" if symbol.upper().startswith(("XAU", "XAG")) else "forex"
    instrument = {
        "symbol": symbol.upper(), "asset_class": asset,
        "exchange": "IDEALPRO" if asset == "forex" else "SMART",
        "sector": None, "industry": None,
    }
    risk = {
        "r_per_share": round(r_per_unit, 5),
        "position_size_shares": units,
        "position_notional_usd": round(notional, 2),
        "position_risk_usd": round(position_risk_usd, 2),
        "position_risk_pct_of_equity": (
            round(position_risk_usd / equity * 100, 3) if equity > 0 else 0.0),
        "position_notional_pct_of_equity": (
            round(notional / equity * 100, 2) if equity > 0 else 0.0),
        "r_multiple_to_tp1": round(r_to_tp, 2),
        "r_multiple_to_tp2": round(r_to_tp, 2),
    }
    thesis = {
        "summary": f"{direction.upper()} {symbol.upper()} — FVG displacement-"
                   f"continuation (session {trade.date_str})",
        "strategy": STRATEGY,
        "lenses_contributing": ["technical"],
        "conviction": 0.70,
        "expected_holding_period": "intraday",
        "session_date": trade.date_str,
        "similar_past_setups": [], "memory_win_rate": None, "memory_avg_r": None,
    }
    evidence = [{"type": "fvg_zone", "ref": trade.notes}]

    return TradePlan(
        mode=mode, instrument=instrument, thesis=thesis, setup=setup,
        risk=risk,
        execution={
            "preferred_algo": "market", "urgency": "high",
            "broker": "ibkr", "account_type": mode,
        },
        evidence=evidence,
        tradingview_chart_url=(
            f"https://www.tradingview.com/chart/?symbol=FX_IDC:{symbol.upper()}"
            if asset == "forex"
            else "https://www.tradingview.com/chart/?symbol=TVC:GOLD"
        ),
    )


def _session_close_utc() -> str:
    """Today's 16:00 ET as UTC ISO (next day if already past)."""
    from zoneinfo import ZoneInfo
    now_et = datetime.now(ZoneInfo("America/New_York"))
    close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    if close <= now_et:
        close += timedelta(days=1)
    return close.astimezone(timezone.utc).isoformat()


def _merge_into_csv(path, new_df):
    """Concat IBKR bars (lowercase ohlcv, UTC index) with the existing CSV,
    dedupe on timestamp (keep the freshest), and write back in the
    {datetime, Open..Volume} shape replay_fvg._load reads. Preserves deep
    history — only the overlapping/newer tail is updated."""
    import pandas as pd
    frames = []
    if path.exists():
        old = pd.read_csv(path)
        dc = old.columns[0]
        old[dc] = pd.to_datetime(old[dc], utc=True, errors="coerce")
        old = old.dropna(subset=[dc]).set_index(dc)
        old.columns = [c.lower() for c in old.columns]
        keep = [c for c in ("open", "high", "low", "close", "volume") if c in old.columns]
        frames.append(old[keep])
    frames.append(new_df[["open", "high", "low", "close", "volume"]])
    merged = pd.concat(frames)
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    out = merged.rename(columns={"open": "Open", "high": "High", "low": "Low",
                                 "close": "Close", "volume": "Volume"})
    out.index.name = "datetime"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path)
    return merged


async def _refresh_bars_from_ibkr(symbols: list[str], interval: str = "30m",
                                  lookback_days: int = 12) -> dict[str, str]:
    """Best-effort: pull the recent {interval} window per symbol from IBKR and
    merge it into the cache so 'today' evaluates the CURRENT session. Needs a
    running IB Gateway (uses IBKR_DATA_CLIENT_ID, separate from trading). On any
    failure the symbol keeps its cached bars — the scan then shows a stale
    preview instead of a fresh setup, which is the honest fallback."""
    from services import hf_data_service as H
    from datetime import date as _date

    start = (_date.today() - timedelta(days=lookback_days)).isoformat()
    out: dict[str, str] = {}
    for sym in symbols:
        try:
            new = await H._fetch_symbol_ibkr(sym, start=start, interval=interval)
        except Exception as e:  # noqa: BLE001
            out[sym] = f"skip ({type(e).__name__})"
            logger.info("fvg refresh: %s IBKR fetch failed: %s", sym, e)
            continue
        if new is None or getattr(new, "empty", True):
            out[sym] = "no_new_bars"
            continue
        try:
            merged = _merge_into_csv(HIST_DIR / f"{sym.upper()}_{interval}.csv", new)
            out[sym] = f"+{len(new)} bars, last {merged.index[-1].date()}"
        except Exception as e:  # noqa: BLE001
            out[sym] = f"merge_error: {e}"
            logger.warning("fvg refresh: %s merge failed: %s", sym, e)
    return out


async def run_fvg_scan(settings: Settings | None = None,
                       mode: str | None = None,
                       as_of: date | None = None,
                       refresh: bool | None = None) -> dict:
    """Evaluate the latest FVG setup per symbol, gate it, queue to /pending.

    Returns a summary dict shaped like the equity scan summary so the
    Strategies "Run" modal can render it uniformly.
    """
    s = settings or get_settings()
    effective_mode = mode or s.app.mode
    cfg = _load_config()
    symbols = _symbols(cfg)
    risk_pct = float((cfg.get("risk") or {}).get("max_risk_pct_per_trade",
                     s.risk_defaults.max_risk_pct_per_trade))
    until = as_of or date.today()
    # Look back far enough to always locate the LATEST available session in the
    # data, even if the cache is months old. The FRESHNESS_DAYS guard below —
    # not this window — decides what actually gets queued vs shown as a stale
    # preview, so a wide window is safe (cost is one full-frame load per symbol
    # regardless of window width).
    since = until - timedelta(days=730)
    run_id = str(uuid4())

    # Live-bar refresh: before evaluating, top up each symbol's 30m cache from
    # IBKR so "today" sees the CURRENT session, not last week's stale preview.
    # Default: refresh in paper/live for a real-time run; skip in research and
    # for any as_of (historical/backtest) run where the cache is the source.
    do_refresh = refresh if refresh is not None else (
        effective_mode != "research" and as_of is None)
    refresh_status: dict[str, str] = {}
    if do_refresh:
        try:
            refresh_status = await _refresh_bars_from_ibkr(symbols)
        except Exception as e:  # noqa: BLE001
            logger.warning("fvg_scan: bar refresh failed wholesale: %s", e)
            refresh_status = {"_error": str(e)}

    # Lazy import — replay_fvg pulls pandas + the fvg detector.
    from scripts.replay_fvg import _run_pair

    # Account + gates (mirror pipeline_service).
    from services.pipeline_service import _safe_get_account, _market_state_for_plan
    adapter = get_adapter()
    account = await _safe_get_account(adapter)
    compliance = ComplianceOfficer(s)
    risk = RiskManager(s)

    # Symbols the operator already holds — a setup for one of these has already
    # been accepted (it IS the position), so we flag it and don't re-queue.
    held_symbols = {
        p.symbol.upper() for p in getattr(account, "open_positions", []) or []
        if abs(getattr(p, "shares", 0) or 0) > 0
    }

    proposed = 0
    approved = 0
    seen_before = 0
    blocked: list[dict] = []
    per_symbol: list[dict] = []
    fresh_cutoff = until - timedelta(days=FRESHNESS_DAYS)

    for sym in symbols:
        try:
            trades = _run_pair(sym, since, until, interval="30m")
        except Exception as e:  # noqa: BLE001
            per_symbol.append({"symbol": sym, "status": "error", "detail": str(e)})
            continue
        if not trades:
            per_symbol.append({"symbol": sym, "status": "no_setup"})
            continue
        trade = trades[-1]  # most-recent session
        try:
            sess = date.fromisoformat(trade.date_str)
        except ValueError:
            sess = until
        if sess < fresh_cutoff:
            # Not queued (too old to trade), but surface the setup details so
            # the operator can see the mechanism working on historical data
            # before live (IBKR) bars are wired.
            per_symbol.append({
                "symbol": sym, "status": "stale", "session": trade.date_str,
                "direction": trade.direction,
                "entry": _round_px(sym, float(trade.entry)),
                "stop": _round_px(sym, float(trade.stop)),
                "tp": _round_px(sym, float(trade.tp)) if trade.tp is not None else None,
            })
            continue

        setup_px = {
            "direction": trade.direction,
            "entry": _round_px(sym, float(trade.entry)),
            "stop": _round_px(sym, float(trade.stop)),
            "tp": _round_px(sym, float(trade.tp)) if trade.tp is not None else None,
        }

        # Guard 1 — already a position. The operator accepted this instrument;
        # don't propose another trade in it. Surface it, flagged, don't queue.
        if sym.upper() in held_symbols:
            seen_before += 1
            per_symbol.append({"symbol": sym, "status": "position_open",
                               "session": trade.date_str, **setup_px})
            continue

        # Guard 2 — same NY session already queued/seen on a prior scan. Dedup
        # on (symbol, session) so a daily re-run never re-lists an unchanged
        # setup. Flag it (with the prior status + plan_id) instead of inserting
        # a duplicate row.
        prior = await db_service.find_session_plan(sym, STRATEGY, trade.date_str)
        if prior is not None:
            seen_before += 1
            per_symbol.append({
                "symbol": sym, "status": "already_listed",
                "session": trade.date_str, "prior_status": prior["status"],
                "plan_id": prior["plan_id"], **setup_px,
            })
            continue

        plan = _build_plan(trade, sym, account.equity, effective_mode, risk_pct)
        if plan is None:
            per_symbol.append({"symbol": sym, "status": "unsized"})
            continue
        proposed += 1

        market_state = await _market_state_for_plan(plan, adapter)
        plan_dict = plan.model_dump()

        cv = compliance.check(plan, account, market_state)
        if cv.result == "rejected":
            await db_service.upsert_pending_plan(
                plan_dict, compliance_verdict=cv.model_dump(), risk_verdict=None,
                status="rejected", strategy=STRATEGY)
            blocked.append({"symbol": sym, "gate": "compliance",
                            "reason": cv.block_reason or ""})
            per_symbol.append({"symbol": sym, "status": "rejected",
                               "gate": "compliance", "reason": cv.block_reason,
                               "session": trade.date_str})
            continue

        rv = risk.pre_trade_check(plan, account, market_state)
        if rv.result == "rejected":
            await db_service.upsert_pending_plan(
                plan_dict, compliance_verdict=cv.model_dump(),
                risk_verdict=rv.model_dump(), status="rejected", strategy=STRATEGY)
            blocked.append({"symbol": sym, "gate": "risk",
                            "reason": rv.reject_reason or ""})
            per_symbol.append({"symbol": sym, "status": "rejected", "gate": "risk",
                               "reason": rv.reject_reason, "session": trade.date_str})
            continue

        if rv.result == "resized":
            from services.pipeline_service import _apply_resize
            plan_dict = _apply_resize(plan_dict, rv.model_dump())

        await db_service.upsert_pending_plan(
            plan_dict, compliance_verdict=cv.model_dump(),
            risk_verdict=rv.model_dump(), status="pending", strategy=STRATEGY)
        approved += 1
        per_symbol.append({
            "symbol": sym, "status": "pending", "session": trade.date_str,
            "direction": plan.setup.direction,
            "entry": plan.setup.entry.price,
            "stop": plan.setup.stop_loss.initial.price,
            "tp": plan.setup.take_profit[0].price,
            "plan_id": plan.plan_id,
        })

    ts = datetime.now(timezone.utc).isoformat()
    try:
        await db_service.record_pipeline_run(
            run_id=run_id, workflow_id="fvg_continuation_scan", mode=effective_mode,
            ts_start=ts, ts_end=ts, symbols_analyzed=len(symbols),
            signals_generated=proposed, plans_proposed=proposed,
            plans_approved=approved, plans_blocked=blocked,
            error_message=None, status="complete", duration_seconds=0.0,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("fvg_scan: record_pipeline_run failed: %s", e)

    logger.info("fvg_scan: %d symbols, %d setups, %d queued, %d blocked, "
                "%d already-seen (deduped)",
                len(symbols), proposed, approved, len(blocked), seen_before)

    # Collapse any duplicate rows and drop stale pending setups so re-runs never
    # accrete the same trade twice.
    try:
        await db_service.dedupe_pending_plans()
    except Exception as e:  # noqa: BLE001
        logger.warning("fvg_scan: dedupe_pending_plans failed: %s", e)
    return {
        "strategy": STRATEGY, "run_id": run_id,
        "symbols_scanned": len(symbols),
        "setups_found": proposed, "plans_approved": approved,
        "seen_before": seen_before,
        "plans_blocked": blocked, "per_symbol": per_symbol,
        "mode": effective_mode, "refresh": refresh_status,
        # Aliases so the Strategies "Run" result strip (which reads the equity
        # scan shape) renders FVG runs uniformly.
        "signals_generated": proposed, "plans_proposed": proposed,
    }
