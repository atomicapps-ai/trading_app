"""Phase 4 gates smoke test — compliance (C1–C8) + risk (R1–R9).

Exercises every gate with hand-crafted fixtures. Each case builds a
minimal valid TradePlan / AccountState / MarketState and asserts the
exact verdict. Failure = non-zero exit code with a line pointing at
the broken gate.

Run:  .venv\\Scripts\\python.exe -m scripts.smoke_phase4_gates
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from agents.compliance_officer import ComplianceOfficer
from agents.risk_manager import RiskManager
from models.account import AccountState, LULDBand, MarketState, Position
from models.trade_plan import (
    EntryOrder,
    Setup,
    StopLoss,
    StopLossInitial,
    TakeProfitLeg,
    ThesisInvalidation,
    TimeStop,
    TradePlan,
    TrailingStop,
)
from services.settings_service import Settings

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


# ---------------------------------------------------------------------- #
# Fixture builders
# ---------------------------------------------------------------------- #


def make_plan(
    *,
    mode: str = "paper",
    symbol: str = "NVDA",
    sector: str = "Technology",
    direction: str = "long",
    entry_price: float = 100.0,
    stop_price: float = 98.0,
    tp1: float = 104.0,
    tp2: float = 110.0,
    r_per_share: float = 2.0,
    position_size_shares: int = 500,
    r_multiple_to_tp1: float = 2.0,
    expected_holding_period: str = "swing_days",
) -> TradePlan:
    notional = position_size_shares * entry_price
    return TradePlan(
        mode=mode,
        instrument={
            "symbol": symbol,
            "asset_class": "equity",
            "exchange": "XNAS",
            "sector": sector,
            "industry": "Semiconductors",
        },
        thesis={
            "summary": "test",
            "lenses_contributing": ["technical"],
            "conviction": 0.7,
            "expected_holding_period": expected_holding_period,
        },
        setup=Setup(
            direction=direction,
            entry=EntryOrder(type="limit", price=entry_price, valid_until="gtc"),
            take_profit=[
                TakeProfitLeg(leg=1, price=tp1, size_pct=50, reason="tp1"),
                TakeProfitLeg(leg=2, price=tp2, size_pct=50, reason="tp2"),
            ],
            stop_loss=StopLoss(
                initial=StopLossInitial(type="hard", price=stop_price, reason="test"),
                trail=TrailingStop(
                    active=False, activate_after="none", mode="atr",
                    atr_multiple=1.5, atr_period=14,
                ),
                time_stop=TimeStop(active=False, condition="none", deadline="2099-01-01"),
                thesis_invalidation=ThesisInvalidation(active=False, condition="none"),
            ),
        ),
        risk={
            "r_per_share": r_per_share,
            "position_size_shares": position_size_shares,
            "position_notional_usd": notional,
            "position_risk_usd": position_size_shares * r_per_share,
            "r_multiple_to_tp1": r_multiple_to_tp1,
            "r_multiple_to_tp2": 4.0,
        },
        execution={
            "preferred_algo": "vwap",
            "participation_cap_pct_adv": 2.0,
            "broker": "tradestation",
            "account_type": "paper",
        },
        tradingview_chart_url="https://www.tradingview.com/chart/?symbol=NASDAQ:NVDA",
    )


def make_account(
    *,
    equity: float = 100_000.0,
    account_type: str = "margin",
    open_positions: list[Position] | None = None,
    wash_sale_window: list[str] | None = None,
    realized_pnl_today: float = 0.0,
    unrealized_pnl_today: float = 0.0,
    trades_today: int = 0,
    day_trade_count_rolling_5d: int = 0,
) -> AccountState:
    return AccountState(
        account_id="TEST-1",
        broker="tradestation",
        type=account_type,  # type: ignore[arg-type]
        equity=equity,
        cash=equity,
        buying_power=equity * 2,
        open_positions=open_positions or [],
        realized_pnl_today=realized_pnl_today,
        unrealized_pnl_today=unrealized_pnl_today,
        trades_today=trades_today,
        day_trade_count_rolling_5d=day_trade_count_rolling_5d,
        wash_sale_window=wash_sale_window or [],
        trading_halted=False,
        ts_snapshot=datetime.now(timezone.utc).isoformat(),
    )


def make_market(
    *,
    symbol: str = "NVDA",
    halt_status: bool = False,
    ssr_active: bool = False,
    luld_band: LULDBand | None = None,
    earnings_within_hours: float | None = None,
    adv: int = 50_000_000,
    current_spread_bps: float = 5.0,
) -> MarketState:
    return MarketState(
        symbol=symbol,
        ts=datetime.now(timezone.utc).isoformat(),
        halt_status=halt_status,
        ssr_active=ssr_active,
        luld_band=luld_band,
        earnings_within_hours=earnings_within_hours,
        adv=adv,
        adv_dollar=adv * 100.0,
        current_spread_bps=current_spread_bps,
        vix=18.0,
        session="regular",
    )


# ---------------------------------------------------------------------- #
# Assertions
# ---------------------------------------------------------------------- #


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run_compliance() -> int:
    print("\n" + "=" * 70)
    print("COMPLIANCE GATES C1–C8")
    print("=" * 70)

    settings = Settings()
    officer = ComplianceOfficer(settings)

    # baseline pass
    v = officer.check(make_plan(), make_account(), make_market())
    expect(v.result == "approved", f"baseline: expected pass, got {v.result}")
    expect(v.gates_evaluated == ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"],
           f"baseline: all 8 gates should evaluate, got {v.gates_evaluated}")
    print("  [baseline]           pass (all 8 gates evaluated)")

    # C1 — halt blocks in paper
    v = officer.check(make_plan(), make_account(), make_market(halt_status=True))
    expect(v.result == "rejected" and v.block_reason == "symbol_halted",
           f"C1: expected halt block, got {v.result} / {v.block_reason}")
    print("  [C1 halt paper]      block symbol_halted")

    # C1 — halt is advisory in research mode
    v = officer.check(make_plan(mode="research"), make_account(),
                      make_market(halt_status=True))
    expect(v.result == "approved", f"C1 research: expected pass, got {v.result}")
    print("  [C1 halt research]   advisory (pass)")

    # C2 — entry outside LULD blocks in paper
    band = LULDBand(lower=95.0, upper=99.0)  # entry 100 > upper
    v = officer.check(make_plan(), make_account(), make_market(luld_band=band))
    expect(v.result == "rejected" and v.block_reason == "price_outside_luld_band",
           f"C2: expected luld block, got {v.block_reason}")
    print("  [C2 LULD paper]      block price_outside_luld_band")

    # C2 — LULD advisory in research
    v = officer.check(make_plan(mode="research"), make_account(),
                      make_market(luld_band=band))
    expect(v.result == "approved", "C2 research: should be advisory")
    print("  [C2 LULD research]   advisory (pass)")

    # C3 — SSR active + short blocks
    v = officer.check(make_plan(direction="short"), make_account(),
                      make_market(ssr_active=True))
    expect(v.result == "rejected" and v.block_reason == "ssr_active_no_short_on_downtick",
           f"C3: expected ssr block, got {v.block_reason}")
    print("  [C3 SSR short]       block ssr_active_no_short_on_downtick")

    # C3 — SSR active but long → pass (SSR only gates shorts)
    v = officer.check(make_plan(direction="long"), make_account(),
                      make_market(ssr_active=True))
    expect(v.result == "approved", "C3 long+ssr: should pass (SSR only gates shorts)")
    print("  [C3 SSR long]        pass (long unaffected)")

    # C4 — wash sale window blocks long
    v = officer.check(make_plan(symbol="NVDA"),
                      make_account(wash_sale_window=["NVDA"]),
                      make_market())
    expect(v.result == "rejected" and v.block_reason == "wash_sale_window_active",
           f"C4: expected wash-sale block, got {v.block_reason}")
    print("  [C4 wash sale long]  block wash_sale_window_active")

    # C4 — wash sale does NOT block short
    v = officer.check(make_plan(symbol="NVDA", direction="short"),
                      make_account(wash_sale_window=["NVDA"]),
                      make_market())
    expect(v.result == "approved", "C4 short: wash sale only gates longs")
    print("  [C4 wash sale short] pass (shorts unaffected)")

    # C5 — PDT: margin < 25k, 3 day trades, intraday hold → block
    v = officer.check(
        make_plan(expected_holding_period="intraday"),
        make_account(equity=20_000, account_type="margin",
                     day_trade_count_rolling_5d=3),
        make_market(),
    )
    expect(v.result == "rejected" and v.block_reason == "pdt_rule_day_trade_limit_reached",
           f"C5: expected PDT block, got {v.block_reason}")
    print("  [C5 PDT intraday]    block pdt_rule_day_trade_limit_reached")

    # C5 — swing hold skips PDT even at <25k margin
    v = officer.check(
        make_plan(expected_holding_period="swing_days"),
        make_account(equity=20_000, account_type="margin",
                     day_trade_count_rolling_5d=3),
        make_market(),
    )
    expect(v.result == "approved", "C5 swing: should skip PDT for swing")
    print("  [C5 PDT swing]       pass (swing skips PDT)")

    # C5 — cash account skips PDT
    v = officer.check(
        make_plan(expected_holding_period="intraday"),
        make_account(equity=20_000, account_type="cash",
                     day_trade_count_rolling_5d=10),
        make_market(),
    )
    expect(v.result == "approved", "C5 cash: PDT only applies to margin")
    print("  [C5 PDT cash]        pass (cash skips PDT)")

    # C6 — restricted list blocks
    settings_restricted = Settings()
    settings_restricted.compliance.restricted_symbols = ["tsla"]  # case-insensitive
    officer_r = ComplianceOfficer(settings_restricted)
    v = officer_r.check(make_plan(symbol="TSLA"), make_account(), make_market())
    expect(v.result == "rejected" and v.block_reason == "on_restricted_list",
           f"C6: expected restricted block, got {v.block_reason}")
    print("  [C6 restricted]      block on_restricted_list (case-insensitive)")

    # C7 — earnings blackout blocks
    v = officer.check(make_plan(), make_account(),
                      make_market(earnings_within_hours=12.0))
    expect(v.result == "rejected" and v.block_reason == "earnings_blackout_window",
           f"C7: expected earnings block, got {v.block_reason}")
    print("  [C7 earnings 12h]    block earnings_blackout_window")

    # C7 — earnings outside window passes
    v = officer.check(make_plan(), make_account(),
                      make_market(earnings_within_hours=48.0))
    expect(v.result == "approved", "C7: 48h > 24h → pass")
    print("  [C7 earnings 48h]    pass (outside blackout)")

    # C7 — disabled in settings
    settings_noblackout = Settings()
    settings_noblackout.compliance.earnings_blackout_enabled = False
    officer_nb = ComplianceOfficer(settings_noblackout)
    v = officer_nb.check(make_plan(), make_account(),
                         make_market(earnings_within_hours=1.0))
    expect(v.result == "approved", "C7 disabled: should pass regardless")
    print("  [C7 disabled]        pass (blackout off)")

    # C8 — zero entry price blocks (need to bypass pydantic)
    plan = make_plan()
    plan.setup.entry.price = 0.0  # post-construction mutation
    v = officer.check(plan, make_account(), make_market())
    expect(v.result == "rejected" and "setup.entry.price" in (v.block_reason or ""),
           f"C8: expected incomplete plan, got {v.block_reason}")
    print("  [C8 zero entry]      block incomplete_trade_plan (setup.entry.price)")

    # C8 — missing r_per_share
    plan = make_plan()
    plan.risk["r_per_share"] = 0
    v = officer.check(plan, make_account(), make_market())
    expect(v.result == "rejected" and "risk.r_per_share" in (v.block_reason or ""),
           f"C8: expected missing r_per_share, got {v.block_reason}")
    print("  [C8 zero R]          block incomplete_trade_plan (risk.r_per_share)")

    print("  OK — all compliance cases green")
    return 0


def run_risk() -> int:
    print("\n" + "=" * 70)
    print("RISK GATES R1–R9")
    print("=" * 70)

    settings = Settings()
    rd = settings.risk_defaults
    risk = RiskManager(settings)

    # baseline: modest trade, everything passes → approve
    plan = make_plan(
        entry_price=100.0, r_per_share=2.0, position_size_shares=50,
        r_multiple_to_tp1=2.0,
    )
    # risk_usd = 50*2 = $100; equity 100k × 0.5% = $500 cap → well under
    # notional = 50*100 = $5,000; equity 100k × 10% = $10,000 cap → under
    # ADV participation 50,000,000 × 2% = 1,000,000 shares → way over 50
    v = risk.pre_trade_check(plan, make_account(), make_market())
    expect(v.result == "approved",
           f"baseline: expected approve, got {v.result} ({v.reject_reason})")
    expect(v.approved_size_shares == 50, f"approve size: got {v.approved_size_shares}")
    expect(v.gates_evaluated == ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"],
           f"all 9 gates should evaluate, got {v.gates_evaluated}")
    print(f"  [baseline]           approve {v.approved_size_shares} shares "
          f"(risk ${v.approved_risk_usd:.2f}, notional ${v.approved_notional_usd:.2f})")

    # R1: risk-cap resize — 100k × 0.5% = $500; at $2 R → cap = 250
    # Ask for 1,000 shares → R1 should cut to 250
    plan = make_plan(position_size_shares=1000, r_per_share=2.0,
                     entry_price=50.0, r_multiple_to_tp1=2.0)
    # notional 1000*50=50,000; cap 10% of 100k=10,000 → R2 cuts to 200 (even more)
    v = risk.pre_trade_check(plan, make_account(), make_market())
    expect(v.result == "resized", f"R1/R2: expected resize, got {v.result}")
    expect("R1" in v.gates_triggered and "R2" in v.gates_triggered,
           f"R1+R2: expected both triggered, got {v.gates_triggered}")
    # min(R1=250, R2=200) = 200
    expect(v.approved_size_shares == 200,
           f"R1+R2 min: expected 200, got {v.approved_size_shares}")
    print(f"  [R1+R2 both cap]     resize 1000->{v.approved_size_shares} "
          f"(min of R1 cap {rd.max_risk_pct_per_trade:.2f}%, "
          f"R2 cap {rd.max_position_pct_of_equity:.1f}%)")

    # R3: daily loss cap → reject
    # equity 100k × 2% = $2,000 loss cap; realized -$2,500 → hit
    plan = make_plan(position_size_shares=50)
    v = risk.pre_trade_check(plan,
                             make_account(realized_pnl_today=-2_500),
                             make_market())
    expect(v.result == "rejected" and v.reject_reason == "daily_loss_cap_reached",
           f"R3: expected reject daily_loss_cap_reached, got {v.reject_reason}")
    print("  [R3 daily loss]      reject daily_loss_cap_reached")

    # R4: too many open positions
    positions = [
        Position(symbol=f"T{i}", shares=10, avg_entry_price=50, market_price=50,
                 unrealized_pnl_usd=0, sector="Technology")
        for i in range(rd.max_open_positions)
    ]
    v = risk.pre_trade_check(make_plan(position_size_shares=50),
                             make_account(open_positions=positions),
                             make_market())
    expect(v.result == "rejected" and "max_open_positions" in (v.reject_reason or ""),
           f"R4: expected reject, got {v.reject_reason}")
    print(f"  [R4 {rd.max_open_positions} positions]    reject max_open_positions_reached")

    # R5: max daily trades
    v = risk.pre_trade_check(make_plan(position_size_shares=50),
                             make_account(trades_today=rd.max_daily_trades),
                             make_market())
    expect(v.result == "rejected" and "max_daily_trades" in (v.reject_reason or ""),
           f"R5: expected reject, got {v.reject_reason}")
    print(f"  [R5 {rd.max_daily_trades} trades today] reject max_daily_trades_reached")

    # R6: sector concentration
    # existing Technology position worth $30k already; equity 100k; cap 30%
    # new 50 shares × $100 = $5k → total $35k → >30% → reject
    heavy_tech = [Position(symbol="AAPL", shares=300, avg_entry_price=100,
                           market_price=100, unrealized_pnl_usd=0,
                           sector="Technology")]
    plan = make_plan(sector="Technology", entry_price=100.0, position_size_shares=50,
                     r_per_share=1.0, r_multiple_to_tp1=2.0)
    v = risk.pre_trade_check(plan, make_account(open_positions=heavy_tech),
                             make_market())
    expect(v.result == "rejected" and "sector_concentration" in (v.reject_reason or ""),
           f"R6: expected sector reject, got {v.reject_reason}")
    print("  [R6 sector 35%]      reject sector_concentration_exceeded")

    # R7: R:R below 2.0 min → reject
    plan = make_plan(position_size_shares=50, r_multiple_to_tp1=1.5)
    v = risk.pre_trade_check(plan, make_account(), make_market())
    expect(v.result == "rejected" and "insufficient_risk_reward" in (v.reject_reason or ""),
           f"R7: expected reject, got {v.reject_reason}")
    print("  [R7 R:R 1.5]         reject insufficient_risk_reward")

    # R8: participation cap resize
    # adv 1,000 shares × 2% = 20 share cap; ask for 50 → cut to 20
    plan = make_plan(position_size_shares=50, entry_price=50.0, r_per_share=1.0,
                     r_multiple_to_tp1=2.0)
    v = risk.pre_trade_check(plan, make_account(),
                             make_market(adv=1_000, current_spread_bps=5.0))
    expect(v.result == "resized" and "R8" in v.gates_triggered,
           f"R8: expected resize, got {v.result} triggered={v.gates_triggered}")
    expect(v.approved_size_shares == 20,
           f"R8 resize: expected 20 (= 1000 × 2%), got {v.approved_size_shares}")
    print(f"  [R8 ADV 1000]        resize 50->{v.approved_size_shares} (2% of ADV)")

    # R9: spread too wide in paper/live
    plan = make_plan(position_size_shares=50)
    v = risk.pre_trade_check(plan, make_account(),
                             make_market(current_spread_bps=30.0))
    expect(v.result == "rejected" and "spread_too_wide" in (v.reject_reason or ""),
           f"R9 paper: expected spread reject, got {v.reject_reason}")
    print("  [R9 spread 30bps]    reject spread_too_wide (paper)")

    # R9: skipped in research mode
    plan = make_plan(mode="research", position_size_shares=50)
    v = risk.pre_trade_check(plan, make_account(),
                             make_market(current_spread_bps=30.0))
    expect(v.result == "approved",
           f"R9 research: expected approve (skipped), got {v.result}")
    print("  [R9 research 30bps]  approve (R9 skipped in research)")

    # Resize-to-zero guard: R8 cap of 0 → reject
    # participation cap rounds down; adv=1, 2% → 0 → reject
    plan = make_plan(position_size_shares=50)
    v = risk.pre_trade_check(plan, make_account(),
                             make_market(adv=1, current_spread_bps=5.0))
    expect(v.result == "rejected" and v.reject_reason == "sizing_reduced_to_zero",
           f"zero-size: expected reject, got {v.reject_reason}")
    print("  [R8 ADV=1 -> 0]      reject sizing_reduced_to_zero")

    print("  OK — all risk cases green")
    return 0


def main() -> int:
    print("=" * 70)
    print("Phase 4 gates smoke test — compliance + risk")
    print("=" * 70)
    try:
        rc = run_compliance()
        if rc != 0:
            return rc
        rc = run_risk()
        if rc != 0:
            return rc
    except AssertionError as e:
        print(f"\n  FAIL — {e}")
        return 1

    print("\n" + "=" * 70)
    print("ALL GREEN — compliance C1–C8 and risk R1–R9 gates verified.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
