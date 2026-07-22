"""Seed the SQLite DB with realistic demo data so the UI has content.

Drops any prior pending rows, runs the live pipeline once (to capture a
real rejection scenario), then inserts a handful of synthetic plans
with pre-baked gate verdicts so every UI state is represented:

  * pending, all-green verdicts   (AAPL long)
  * pending, resized by R1/R2     (TSLA long, sized down)
  * rejected by compliance        (synthetic — restricted symbol)
  * rejected by risk              (the real GOOGL plan from the live run)

Run:
  .venv\\Scripts\\python -m scripts.seed_demo_data
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone

import aiosqlite
from dotenv import load_dotenv

from services.settings_service import ENV_FILE

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def _now_iso(delta_minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=delta_minutes)).isoformat()


def _sample_plan(
    *,
    plan_id: str,
    symbol: str,
    direction: str,
    entry: float,
    stop: float,
    tp1: float,
    tp2: float,
    position_size: int,
    conviction: float,
    lenses: list[str],
    pattern: str,
    exchange: str = "NASDAQ",
    sector: str = "Technology",
    ts_ago_min: int = 0,
    strategy_thesis: str = "",
) -> dict:
    r_per_share = abs(entry - stop)
    r_to_tp1 = abs(tp1 - entry) / r_per_share if r_per_share else 0
    r_to_tp2 = abs(tp2 - entry) / r_per_share if r_per_share else 0
    notional = round(position_size * entry, 2)
    risk_usd = round(position_size * r_per_share, 2)

    return {
        "plan_id": plan_id,
        "ts_created": _now_iso(-ts_ago_min),
        "mode": "paper",
        "schema_version": "1.0.0",
        "instrument": {
            "symbol": symbol,
            "asset_class": "equity",
            "exchange": exchange,
            "sector": sector,
            "industry": None,
        },
        "thesis": {
            "summary": strategy_thesis or f"{direction.upper()} {symbol} on {pattern}",
            "lenses_contributing": lenses,
            "signal_ids": [f"sig-{symbol}-{i}" for i in range(len(lenses))],
            "conviction": conviction,
            "expected_holding_period": "swing_days",
            "similar_past_setups": [
                {"trade_id": f"mem-{symbol}-1", "outcome_r": 2.1, "similarity": 0.82},
                {"trade_id": f"mem-{symbol}-2", "outcome_r": -0.8, "similarity": 0.71},
            ],
            "memory_win_rate": 0.62,
            "memory_avg_r": 1.35,
        },
        "setup": {
            "direction": direction,
            "entry": {
                "type": "limit",
                "price": round(entry, 2),
                "valid_until": "gtc",
                "do_not_enter_windows": ["open_5min", "close_5min"],
            },
            "take_profit": [
                {"leg": 1, "price": round(tp1, 2), "size_pct": 50,
                 "reason": f"{pattern}_tp1"},
                {"leg": 2, "price": round(tp2, 2), "size_pct": 50,
                 "reason": f"{pattern}_tp2"},
            ],
            "stop_loss": {
                "initial": {"type": "hard", "price": round(stop, 2),
                            "reason": "pattern_invalidation"},
                "trail": {"active": True,
                          "activate_after": "price >= entry + 1.5R",
                          "mode": "atr", "atr_multiple": 1.5, "atr_period": 14},
                "time_stop": {"active": True, "condition": "close if no progress",
                              "deadline": _now_iso(delta_minutes=7 * 24 * 60)},
                "thesis_invalidation": {"active": True,
                                        "condition": "daily_close_below_stop"},
            },
        },
        "risk": {
            "r_per_share": round(r_per_share, 2),
            "position_size_shares": position_size,
            "position_notional_usd": notional,
            "position_risk_usd": risk_usd,
            "position_risk_pct_of_equity": round(risk_usd / 100_000 * 100, 3),
            "position_notional_pct_of_equity": round(notional / 100_000 * 100, 2),
            "r_multiple_to_tp1": round(r_to_tp1, 2),
            "r_multiple_to_tp2": round(r_to_tp2, 2),
        },
        "execution": {
            "preferred_algo": "vwap",
            "participation_cap_pct_adv": 2.0,
            "max_spread_bps_to_cross": 15,
            "urgency": "low",
            "broker": "alpaca_paper",
            "account_type": "paper",
        },
        "evidence": [
            {"type": "pattern", "ref": f"{pattern} triggered on daily"},
            {"type": "indicator", "ref": "volume 1.8x avg, volume_ratio strong"},
            {"type": "indicator", "ref": "RSI 62 bullish zone, MA stack aligned"},
        ],
        "tradingview_chart_url": (
            f"https://www.tradingview.com/chart/?symbol={exchange}:{symbol}&interval=D"
        ),
    }


async def main() -> int:
    load_dotenv(ENV_FILE, override=False)

    from services import db_service, pipeline_service

    print("=" * 78)
    print("Seeding demo data for the /pending page")
    print("=" * 78)

    await db_service.ensure_tables()

    # Fresh slate
    async with aiosqlite.connect(db_service.DB_PATH) as db:
        await db.execute("DELETE FROM pending_approvals")
        await db.execute("DELETE FROM pipeline_runs")
        await db.commit()
    print("[1/4] Wiped pending_approvals + pipeline_runs for a clean demo state")

    # Real pipeline run — captures whatever the live analyst produces today.
    print("\n[2/4] Running live research_run (real rejection will be persisted)")
    summary = await pipeline_service.run_workflow_by_id("research_run")
    print(f"  proposed={summary['plans_proposed']}, "
          f"approved={summary['plans_approved']}, "
          f"blocked={len(summary['plans_blocked'])}")
    for b in summary["plans_blocked"]:
        print(f"    {b['symbol']} blocked by {b['gate']}: {b['reason']}")

    # Synthetic plans that represent every UI state.
    # One row per terminal + non-terminal status so every tab has content.
    print("\n[3/4] Seeding synthetic plans to exercise every UI state")

    # (a) Clean pass — both gates pass, all-green. The demo "happy path."
    aapl = _sample_plan(
        plan_id="demo-aapl-long",
        symbol="AAPL", direction="long",
        entry=228.50, stop=222.75, tp1=240.00, tp2=251.50,
        position_size=86, conviction=0.78,
        lenses=["technical", "macro"], pattern="bull_flag",
        sector="Technology", ts_ago_min=14,
        strategy_thesis=(
            "AAPL bull flag on 1D — 4-ATR flagpole, 5-bar flag retracing 42%, "
            "breakout close on 1.8x volume. Macro lens aligned (SPY uptrend, "
            "VIX low regime)."
        ),
    )
    await db_service.upsert_pending_plan(
        aapl,
        compliance_verdict={
            "verdict_id": "cv-aapl-1", "plan_id": aapl["plan_id"],
            "ts": aapl["ts_created"], "result": "approved",
            "gates_evaluated": ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"],
            "gates_failed": [],
        },
        risk_verdict={
            "verdict_id": "rv-aapl-1", "plan_id": aapl["plan_id"],
            "ts": aapl["ts_created"], "result": "approved",
            "original_size_shares": 86, "approved_size_shares": 86,
            "gates_evaluated": ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"],
            "gates_triggered": [],
            "approved_risk_usd": aapl["risk"]["position_risk_usd"],
            "approved_notional_usd": aapl["risk"]["position_notional_usd"],
        },
        status="pending", strategy="swing_momentum",
    )
    print(f"  seeded [approve] {aapl['instrument']['symbol']} {aapl['setup']['direction']}")

    # (b) Resized by R1 (per-trade risk cap). Proposal 500 → 250 shares.
    tsla = _sample_plan(
        plan_id="demo-tsla-long",
        symbol="TSLA", direction="long",
        entry=310.25, stop=302.50, tp1=327.75, tp2=342.50,
        position_size=250, conviction=0.72,
        lenses=["technical"], pattern="volatility_squeeze",
        sector="Consumer Discretionary", ts_ago_min=8,
        strategy_thesis=(
            "TSLA 9-bar squeeze fire on 1D with positive momentum histogram. "
            "Position originally proposed at 500 shares — R1 cap resized "
            "to 250 (0.5% equity risk)."
        ),
    )
    # Override proposed size for the display narrative
    tsla_risk = dict(tsla["risk"])
    tsla_risk["position_size_shares"] = 250  # approved
    tsla["risk"] = tsla_risk
    await db_service.upsert_pending_plan(
        tsla,
        compliance_verdict={
            "verdict_id": "cv-tsla-1", "plan_id": tsla["plan_id"],
            "ts": tsla["ts_created"], "result": "approved",
            "gates_evaluated": ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"],
            "gates_failed": [],
        },
        risk_verdict={
            "verdict_id": "rv-tsla-1", "plan_id": tsla["plan_id"],
            "ts": tsla["ts_created"], "result": "resized",
            "original_size_shares": 500, "approved_size_shares": 250,
            "gates_evaluated": ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"],
            "gates_triggered": ["R1"],
            "resize_reason": "R1 per_trade_risk_cap: reduced from 500 to 250 shares",
            "approved_risk_usd": tsla["risk"]["position_risk_usd"],
            "approved_notional_usd": tsla["risk"]["position_notional_usd"],
        },
        status="pending", strategy="swing_momentum",
    )
    print(f"  seeded [resize]  {tsla['instrument']['symbol']} {tsla['setup']['direction']} "
          f"(500 -> 250 shares)")

    # (c) Another clean pass, different pattern — fills the Pending tab.
    msft = _sample_plan(
        plan_id="demo-msft-long",
        symbol="MSFT", direction="long",
        entry=418.20, stop=408.75, tp1=437.50, tp2=456.90,
        position_size=47, conviction=0.71,
        lenses=["technical"], pattern="inside_bar_nr7",
        sector="Technology", ts_ago_min=4,
        strategy_thesis=(
            "MSFT inside bar + NR7 on 1D at the 20-SMA reclaim. "
            "Measured move from mother-bar range; breakout trigger at "
            "prior-day high on above-average volume."
        ),
    )
    await db_service.upsert_pending_plan(
        msft,
        compliance_verdict={
            "verdict_id": "cv-msft-1", "plan_id": msft["plan_id"],
            "ts": msft["ts_created"], "result": "approved",
            "gates_evaluated": ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"],
            "gates_failed": [],
        },
        risk_verdict={
            "verdict_id": "rv-msft-1", "plan_id": msft["plan_id"],
            "ts": msft["ts_created"], "result": "approved",
            "original_size_shares": 47, "approved_size_shares": 47,
            "gates_evaluated": ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"],
            "gates_triggered": [],
            "approved_risk_usd": msft["risk"]["position_risk_usd"],
            "approved_notional_usd": msft["risk"]["position_notional_usd"],
        },
        status="pending", strategy="swing_momentum",
    )
    print(f"  seeded [approve] {msft['instrument']['symbol']} {msft['setup']['direction']}")

    # (d) Executed — fully through gates + human approved + broker accepted.
    nvda = _sample_plan(
        plan_id="demo-nvda-long",
        symbol="NVDA", direction="long",
        entry=182.40, stop=176.50, tp1=194.20, tp2=206.00,
        position_size=60, conviction=0.84,
        lenses=["technical", "macro"], pattern="bull_flag",
        sector="Technology", ts_ago_min=42,
        strategy_thesis=(
            "NVDA post-earnings bull flag. Approved by operator "
            "44 minutes ago; order routed to Alpaca paper and accepted."
        ),
    )
    await db_service.upsert_pending_plan(
        nvda,
        compliance_verdict={
            "verdict_id": "cv-nvda-1", "plan_id": nvda["plan_id"],
            "ts": nvda["ts_created"], "result": "approved",
            "gates_evaluated": ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"],
            "gates_failed": [],
        },
        risk_verdict={
            "verdict_id": "rv-nvda-1", "plan_id": nvda["plan_id"],
            "ts": nvda["ts_created"], "result": "approved",
            "original_size_shares": 60, "approved_size_shares": 60,
            "gates_evaluated": ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"],
            "gates_triggered": [],
            "approved_risk_usd": nvda["risk"]["position_risk_usd"],
            "approved_notional_usd": nvda["risk"]["position_notional_usd"],
        },
        status="pending", strategy="swing_momentum",
    )
    # Simulate the post-ack writeback: human ack + executioner result.
    ack_ts = _now_iso(-40)
    await db_service.ack_plan(
        nvda["plan_id"], "approve",
        ack_record={
            "ack_id": "ack-nvda-1", "plan_id": nvda["plan_id"],
            "ts": ack_ts, "action": "approve", "ack_by": "human",
            "modified_fields": {},
        },
    )
    await db_service.record_execution(
        nvda["plan_id"],
        {
            "plan_id": nvda["plan_id"], "ack_id": "ack-nvda-1",
            "placed": True, "ts": ack_ts,
            "client_order_id": "exec-demo-nvda1",
            "broker_order_id": "ALP-DEMO-NVDA-9821",
            "broker_name": "alpaca_paper",
            "order_json": {"symbol": "NVDA", "side": "buy",
                            "order_type": "limit", "quantity": 60,
                            "limit_price": 182.40, "time_in_force": "gtc"},
            "order_ack_json": {"accepted": True,
                                "broker_order_id": "ALP-DEMO-NVDA-9821"},
            "reject_reason": None,
        },
    )
    print(f"  seeded [executed] {nvda['instrument']['symbol']} "
          f"{nvda['setup']['direction']} (broker_order_id ALP-DEMO-NVDA-9821)")

    # (e) Blocked by compliance — restricted-list symbol.
    meme = _sample_plan(
        plan_id="demo-gme-long",
        symbol="GME", direction="long",
        entry=24.50, stop=22.80, tp1=28.50, tp2=32.00,
        position_size=50, conviction=0.62,
        lenses=["sentiment"], pattern="news_catalyst",
        exchange="NYSE", sector="Consumer Discretionary", ts_ago_min=22,
        strategy_thesis=(
            "GME news catalyst with 2.3x volume surge. Sentiment lens fired "
            "on analyst-upgrade headline. BLOCKED by compliance C6 — "
            "symbol on the operator's restricted list."
        ),
    )
    await db_service.upsert_pending_plan(
        meme,
        compliance_verdict={
            "verdict_id": "cv-gme-1", "plan_id": meme["plan_id"],
            "ts": meme["ts_created"], "result": "rejected",
            "gates_evaluated": ["C1", "C2", "C3", "C4", "C5", "C6"],
            "gates_failed": ["C6"],
            "block_reason": "on_restricted_list",
            "cited_rule": "settings.compliance.restricted_symbols",
        },
        risk_verdict=None,
        status="rejected", strategy="sentiment_catalyst",
    )
    print(f"  seeded [compliance-block] {meme['instrument']['symbol']}")

    # ---- Final report --------------------------------------------------
    pending = await db_service.get_pending_plans(status_filter="pending")
    executed = await db_service.get_pending_plans(status_filter="executed")
    rejected = await db_service.get_pending_plans(status_filter="rejected")
    print(
        f"\n[4/4] Demo DB populated: "
        f"{len(pending)} pending, "
        f"{len(executed)} executed, "
        f"{len(rejected)} rejected"
    )
    print("  Ready for: https://app.tindex.ai/pending  (or http://localhost:5000/pending on the box)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
