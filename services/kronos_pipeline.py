"""kronos_pipeline — turn Kronos candidates into pending TradePlans on Alpaca paper.

Mirrors services.pipeline_service.run_workflow_by_id, but the plans come from the
Kronos scan instead of the workflow engine. For each symbol it forecasts, builds a
certainty-scaled plan, constructs a real TradePlan, runs the SAME compliance + risk
gates, and persists survivors to pending_approvals with status='pending'. They then
appear in the existing /pending queue for HUMAN approval (no auto-approve here), and
approval routes through the existing executioner -> Alpaca paper path unchanged.

Each plan carries the raw Kronos probability AND the GBM baseline probability in its
thesis/evidence, so closed trades become the calibration dataset later.

Run it via scripts/kronos_queue.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from agents.compliance_officer import ComplianceOfficer
from agents.risk_manager import RiskManager
from models.trade_plan import (
    EntryOrder, Setup, StopLoss, StopLossInitial, TakeProfitLeg,
    ThesisInvalidation, TimeStop, TradePlan, TrailingStop,
)
from services import (
    baseline_service, company_service, db_service, kronos_planner,
    kronos_service, pivot_service,
)
from services.broker_service import get_adapter
from services.pipeline_service import (
    _apply_resize, _market_state_for_plan, _safe_get_account,
)
from services.settings_service import get_settings

logger = logging.getLogger(__name__)

STRATEGY = "kronos_daily"
DEFAULT_RISK_PCT = 0.005   # 0.5% of equity risked per trade; risk_manager re-caps


def _build_trade_plan(kp, *, mode: str, equity: float, pred_len: int,
                      baseline_p: float | None, pivots: dict | None = None) -> TradePlan:
    """Map a KronosPlan into the app's full TradePlan (single 100% TP leg)."""
    r_per_share = kp.risk_per_share or abs(kp.entry - kp.stop)
    risk_budget = max(equity, 1.0) * DEFAULT_RISK_PCT
    shares = max(1, int(risk_budget / r_per_share)) if r_per_share > 0 else 1
    deadline = (pd.Timestamp.now(tz=timezone.utc)
                + pd.tseries.offsets.BDay(pred_len)).isoformat()

    return TradePlan(
        mode=mode,
        instrument={
            "symbol": kp.symbol,
            "name": company_service.get_name(kp.symbol),
            "asset_class": "equity",
        },
        thesis={
            "summary": f"Kronos {kp.direction} forecast, {pred_len}-bar horizon",
            "conviction": kp.dir_conviction,
            "lenses_contributing": ["kronos"],
            # --- calibration shadow fields (raw, uncalibrated) ---
            "kronos_pred_prob": kp.p_profit,
            "kronos_expected_r": kp.expected_r,
            "baseline_prob": baseline_p,
            "path_sigma_pct": kp.path_sigma_pct,
            "horizon_bars": pred_len,
            # --- pivot context (displayed + logged; NOT folded into the prob) ---
            "pivots": pivots,
            "pivot_confluence": (pivots or {}).get("confluence"),
        },
        setup=Setup(
            direction=kp.direction,
            entry=EntryOrder(type="limit", price=kp.entry, valid_until="gtc"),
            take_profit=[TakeProfitLeg(
                leg=1, price=kp.take_profit, size_pct=100.0,
                reason=f"certainty-scaled RR {kp.rr} (conviction {kp.dir_conviction:.0%})",
            )],
            stop_loss=StopLoss(
                initial=StopLossInitial(
                    type="hard", price=kp.stop,
                    reason=f"{kronos_planner.STOP_ATR_MULT}x ATR ({kp.atr})",
                ),
                trail=TrailingStop(active=False, activate_after="", mode="atr"),
                time_stop=TimeStop(
                    active=True,
                    condition=f"close at {pred_len}-bar forecast horizon",
                    deadline=deadline,
                ),
                thesis_invalidation=ThesisInvalidation(active=False, condition=""),
            ),
        ),
        risk={
            "r_per_share": round(r_per_share, 4),
            "position_size_shares": shares,
            "position_risk_usd": round(shares * r_per_share, 2),
            "position_notional_usd": round(shares * kp.entry, 2),
            "position_risk_pct_of_equity": round(DEFAULT_RISK_PCT * 100, 3),
            "r_multiple_to_tp1": kp.rr,
            "r_multiple_to_tp2": kp.rr,
        },
        execution={"algo": "limit", "broker": "alpaca", "account_type": "paper"},
        evidence=[
            {
                "source": "kronos",
                "p_profit": kp.p_profit,
                "expected_r": kp.expected_r,
                "baseline_p_profit": baseline_p,
                "path_sigma_pct": kp.path_sigma_pct,
                "rr": kp.rr,
            },
            {
                "source": "pivots",
                "confluence": (pivots or {}).get("confluence"),
                "note": (pivots or {}).get("note"),
                "nearest_support": (pivots or {}).get("nearest_support"),
                "nearest_resistance": (pivots or {}).get("nearest_resistance"),
            },
        ],
        tradingview_chart_url=f"https://www.tradingview.com/chart/?symbol={kp.symbol}",
    )


async def queue_candidates(
    *,
    symbols: list[str],
    pred_len: int = 10,
    n_paths: int = 30,
    device: str | None = None,
    min_prob: float = 0.60,
    min_er: float = 0.0,
    settings=None,
) -> dict:
    """Forecast each symbol, gate it, and queue survivors to /pending."""
    from scripts.kronos_poc import fetch_daily_bars  # reuse the loader

    s = settings or get_settings()
    mode = s.app.mode
    compliance = ComplianceOfficer(s)
    risk = RiskManager(s)
    adapter = get_adapter()
    account = await _safe_get_account(adapter)
    equity = float(getattr(account, "equity", 0.0) or 0.0) or 100_000.0

    queued: list[str] = []
    rejected: list[tuple] = []
    skipped: list[str] = []

    for sym in symbols:
        try:
            bars = fetch_daily_bars(sym)
            dist = kronos_service.forecast(
                symbol=sym, interval="1d", bars=bars,
                pred_len=pred_len, n_paths=n_paths, device=device,
            )
            kp = kronos_planner.build_plan(symbol=sym, dist=dist, bars=bars)
            if kp is None or kp.p_profit < min_prob or kp.expected_r < min_er:
                skipped.append(sym)
                continue

            # GBM baseline P(profit) on the SAME setup — for calibration later
            baseline_p: float | None = None
            try:
                gd = baseline_service.gbm_forecast(
                    symbol=sym, interval="1d", bars=bars,
                    pred_len=pred_len, n_paths=max(n_paths, 100), seed=7,
                )
                baseline_p = gd.hit_probabilities(
                    entry=kp.entry, stop=kp.stop, take_profit=kp.take_profit,
                    direction=kp.direction,
                ).p_profit
            except Exception as exc:  # noqa: BLE001
                logger.debug("baseline for %s failed: %s", sym, exc)

            try:
                pivots = pivot_service.pivot_context(
                    bars, direction=kp.direction, entry=kp.entry, take_profit=kp.take_profit)
            except Exception as exc:  # noqa: BLE001
                logger.debug("pivots for %s failed: %s", sym, exc)
                pivots = None

            plan = _build_trade_plan(kp, mode=mode, equity=equity,
                                     pred_len=pred_len, baseline_p=baseline_p, pivots=pivots)
            plan_dict = plan.model_dump()
            market_state = await _market_state_for_plan(plan, adapter)

            cv = compliance.check(plan, account, market_state)
            if cv.result == "rejected":
                await db_service.upsert_pending_plan(
                    plan_dict, compliance_verdict=cv.model_dump(),
                    status="rejected", strategy=STRATEGY)
                rejected.append((sym, "compliance", cv.block_reason))
                continue

            rv = risk.pre_trade_check(plan, account, market_state)
            if rv.result == "rejected":
                await db_service.upsert_pending_plan(
                    plan_dict, compliance_verdict=cv.model_dump(),
                    risk_verdict=rv.model_dump(), status="rejected", strategy=STRATEGY)
                rejected.append((sym, "risk", rv.reject_reason))
                continue
            if rv.result == "resized":
                plan_dict = _apply_resize(plan_dict, rv.model_dump())

            await db_service.upsert_pending_plan(
                plan_dict, compliance_verdict=cv.model_dump(),
                risk_verdict=rv.model_dump(), status="pending", strategy=STRATEGY)
            queued.append(sym)
            logger.info("queued %s %s  P(profit)=%.0f%%  RR=%.1f",
                        sym, kp.direction, kp.p_profit * 100, kp.rr)
        except Exception as exc:  # noqa: BLE001
            logger.error("%s failed: %s", sym, exc)
            rejected.append((sym, "error", str(exc)))

    return {"queued": queued, "rejected": rejected, "skipped": skipped,
            "equity": equity, "mode": mode}
