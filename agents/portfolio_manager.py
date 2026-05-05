"""portfolio_manager.py — signal synthesizer and TradePlan builder.

Takes the raw Signals that analyst.run() emits and decides whether the
evidence is strong enough to become a TradePlan, then assembles the full
plan object (entry / stop / TP legs / risk sizing / thesis / evidence).

Phase 4 scope
-------------
The original SKILL.md rule is "minimum 2 lenses must agree in direction."
Today only the technical lens is wired; sentiment + fundamental are
stubbed. So this build uses an intermediate rule that honors the spirit
of consensus without requiring lenses that don't exist yet:

    go if ANY of these is true:
      * >= min_lenses_agreeing (default 2) unique lenses point the same way
      * the single firing lens has >= min_patterns_agreeing (default 2)
        distinct patterns in the same direction
      * a single signal has strength >= single_signal_override (default 0.75)

All three thresholds are overridable in strategy_configs/*.yaml under
``portfolio_rules``. The 2-lens rule becomes strict once sentiment and
fundamental land.

Position sizing (SKILL.md §2.5) is fixed-fractional:
    R = |entry - stop|
    size = floor(equity × risk_pct / 100 / R)

Risk gates (R1/R2) may later resize this downward — portfolio_manager
proposes an initial size and the compliance+risk gates get the last word.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from models.account import AccountState
from models.signal import Signal
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

logger = logging.getLogger(__name__)

MAX_PENDING_PROPOSALS = 5  # SKILL.md §3 — hard cap on concurrent pending plans


# ---------------------------------------------------------------------- #
# Defaults (overridable via strategy_config.portfolio_rules)
# ---------------------------------------------------------------------- #

_DEFAULT_RULES = {
    "min_lenses_agreeing": 2,
    "min_patterns_agreeing": 2,
    "single_signal_override": 0.75,
    # Trail / time-stop knobs used in TradePlan assembly
    "trail_atr_multiple": 1.5,
    "trail_atr_period": 14,
    "trail_activate_after": "price >= entry + 1.5R",
    "time_stop_sessions": 5,
    "time_stop_condition": "close if no progress by session N",
}


# ---------------------------------------------------------------------- #
# PortfolioManager
# ---------------------------------------------------------------------- #


class PortfolioManager:
    def __init__(
        self,
        settings: Settings,
        strategy_config: dict[str, Any] | None = None,
    ) -> None:
        self._settings = settings
        self._strategy_config = strategy_config or {}

    async def process_signals(
        self,
        symbol: str,
        signals: list[Signal],
        account: AccountState,
        existing_positions: list[str] | None = None,
        mode: Literal["research", "paper", "live"] | None = None,
        pending_count: int = 0,
    ) -> TradePlan | None:
        """Collapse signals → TradePlan. Returns None if criteria not met."""
        if not signals:
            return None

        # Hard cap — can't propose more plans than the approval queue allows
        if pending_count >= MAX_PENDING_PROPOSALS:
            logger.info(
                "%s: skipping — pending proposal queue is full (%d)",
                symbol, pending_count,
            )
            return None

        rules = {**_DEFAULT_RULES, **(self._strategy_config.get("portfolio_rules") or {})}
        effective_mode = mode or self._settings.app.mode

        # Group by direction (neutral signals are informational only)
        by_direction: dict[str, list[Signal]] = {"long": [], "short": []}
        for s in signals:
            if s.direction in by_direction:
                by_direction[s.direction].append(s)

        # Pick the direction with stronger aggregate evidence
        long_strength = sum(s.strength for s in by_direction["long"])
        short_strength = sum(s.strength for s in by_direction["short"])
        if long_strength == short_strength:
            # Ambiguous — don't trade
            logger.info("%s: long and short signals tie on strength — skip", symbol)
            return None
        direction = "long" if long_strength > short_strength else "short"
        primary_direction_signals = by_direction[direction]

        # Consensus rule (three OR-ed paths)
        if not self._consensus_met(primary_direction_signals, rules):
            logger.info(
                "%s: %s signals (%d total) don't clear consensus rule",
                symbol, direction, len(primary_direction_signals),
            )
            return None

        # Anchor signal: highest-strength signal with non-None prices.
        # If none of the signals have prices (e.g. all from non-technical
        # lenses), we can't build a plan yet — portfolio_manager isn't in
        # the business of guessing entry/stop.
        priced = [s for s in primary_direction_signals
                  if s.entry_price and s.stop_price
                  and s.tp1_price and s.tp2_price]
        if not priced:
            logger.info(
                "%s: no signal carries entry/stop/tp prices — skip", symbol,
            )
            return None
        anchor = max(priced, key=lambda s: s.strength)

        # Sanity: stop must actually be a stop for the chosen direction
        if direction == "long" and anchor.stop_price >= anchor.entry_price:
            logger.warning(
                "%s: long anchor has stop >= entry — inverted; skip", symbol,
            )
            return None
        if direction == "short" and anchor.stop_price <= anchor.entry_price:
            logger.warning(
                "%s: short anchor has stop <= entry — inverted; skip", symbol,
            )
            return None

        # Existing position check — SKILL.md says "evaluate add/hold/reduce
        # instead of new entry." For Phase 4 we emit a NEW plan only if
        # the symbol is NOT already open; add/hold/reduce lands with the
        # memory service in Phase 7.
        existing = set(existing_positions or [])
        if symbol in existing:
            logger.info(
                "%s: already have a position — add/hold logic is Phase 7", symbol,
            )
            return None

        return self._build_plan(
            symbol=symbol,
            direction=direction,
            anchor=anchor,
            all_signals=primary_direction_signals,
            account=account,
            mode=effective_mode,
            rules=rules,
        )

    # ------------------------------------------------------------------ #
    # Consensus
    # ------------------------------------------------------------------ #

    def _consensus_met(
        self, direction_signals: list[Signal], rules: dict[str, Any],
    ) -> bool:
        if not direction_signals:
            return False

        # (1) Single-signal override on very high conviction
        if any(s.strength >= float(rules["single_signal_override"])
               for s in direction_signals):
            return True

        # (2) Multi-lens agreement
        unique_lenses = {s.lens for s in direction_signals}
        if len(unique_lenses) >= int(rules["min_lenses_agreeing"]):
            return True

        # (3) Intra-lens multi-pattern agreement (technical lens, multiple
        # detectors firing the same direction)
        unique_patterns = {s.pattern_name for s in direction_signals
                           if s.pattern_name}
        if len(unique_patterns) >= int(rules["min_patterns_agreeing"]):
            return True

        return False

    # ------------------------------------------------------------------ #
    # Plan assembly
    # ------------------------------------------------------------------ #

    def _build_plan(
        self,
        *,
        symbol: str,
        direction: Literal["long", "short"],
        anchor: Signal,
        all_signals: list[Signal],
        account: AccountState,
        mode: Literal["research", "paper", "live"],
        rules: dict[str, Any],
    ) -> TradePlan:
        entry_price = float(anchor.entry_price)
        stop_price = float(anchor.stop_price)
        tp1_price = float(anchor.tp1_price)
        tp2_price = float(anchor.tp2_price)

        # Risk math
        r_per_share = abs(entry_price - stop_price)
        shares = _compute_position_size(
            equity=account.equity,
            r_per_share=r_per_share,
            risk_pct_per_trade=self._settings.risk_defaults.max_risk_pct_per_trade,
        )

        # Per-account fixed-dollar override: when the active broker_account
        # has ``extra.position_size_usd`` set, ignore the % calc and size
        # the position to (position_size_usd / entry_price) shares. This
        # is the operator-friendly "I want exactly $X per trade" mode,
        # used most often on live accounts to keep trade size predictable
        # regardless of equity drift.
        try:
            shares = _apply_per_account_size_override(
                shares, entry_price=entry_price, account=account, logger=self._log,
            )
        except Exception as exc:                                      # noqa: BLE001
            self._log.warning("size override raised: %s; using %% calc", exc)
        notional = shares * entry_price
        position_risk_usd = shares * r_per_share
        if direction == "long":
            r_to_tp1 = (tp1_price - entry_price) / r_per_share if r_per_share else 0.0
            r_to_tp2 = (tp2_price - entry_price) / r_per_share if r_per_share else 0.0
        else:
            r_to_tp1 = (entry_price - tp1_price) / r_per_share if r_per_share else 0.0
            r_to_tp2 = (entry_price - tp2_price) / r_per_share if r_per_share else 0.0

        # Entry leg — limit order at anchor price; executioner translates this
        # into the actual order placement semantics during Phase 6.
        entry = EntryOrder(
            type="limit",
            price=round(entry_price, 2),
            valid_until="gtc",
            do_not_enter_windows=["open_5min", "close_5min"],
        )

        # Stop loss — initial hard stop + trailing + time stop + thesis.
        # trail_mode is config-driven so different strategies can use ATR,
        # percent, or structural trails. Default "atr" matches the swing
        # baseline; double_lock.yaml overrides to "percent" for example.
        trail_mode = str(rules.get("trail_mode", "atr"))
        trail_kwargs: dict = dict(
            active=True,
            activate_after=str(rules["trail_activate_after"]),
            mode=trail_mode,  # type: ignore[arg-type]
        )
        if trail_mode == "atr":
            trail_kwargs["atr_multiple"] = float(rules.get("trail_atr_multiple", 1.5))
            trail_kwargs["atr_period"]   = int(rules.get("trail_atr_period", 14))
        elif trail_mode == "percent":
            trail_kwargs["percent"] = float(rules.get("trail_percent", 1.0))
        # "structural" needs no extra params — caller-side logic uses
        # last-bar swing levels at execution time.
        trail = TrailingStop(**trail_kwargs)
        # Intraday strategies anchor the deadline to today's regular-session
        # close (default 15:00 ET so the executioner has runway to flatten
        # before the bell). Multi-session strategies count whole days from
        # planning time. The string deadline is always UTC ISO-8601 — the
        # scheduler handles tz conversion at fire time.
        holding_period = str(
            self._strategy_config.get("holding_period", "swing_days")
        )
        if holding_period == "intraday":
            close_hour = int(rules.get("time_stop_close_et_hour", 15))
            close_minute = int(rules.get("time_stop_close_et_minute", 0))
            now_et = datetime.now(ZoneInfo("America/New_York"))
            deadline_dt = now_et.replace(
                hour=close_hour, minute=close_minute, second=0, microsecond=0,
            )
            if deadline_dt <= now_et:
                deadline_dt += timedelta(days=1)
            deadline = deadline_dt.astimezone(timezone.utc).isoformat()
        else:
            sessions = int(rules.get("time_stop_sessions", 5))
            deadline = (
                datetime.now(timezone.utc) + timedelta(days=sessions)
            ).isoformat()
        time_stop = TimeStop(
            active=True,
            condition=str(rules.get("time_stop_condition",
                                    _DEFAULT_RULES["time_stop_condition"])),
            deadline=deadline,
        )
        thesis_invalidation = ThesisInvalidation(
            active=True,
            condition=anchor.invalidation_condition,
        )
        stop_loss = StopLoss(
            initial=StopLossInitial(
                type="hard",
                price=round(stop_price, 2),
                reason=anchor.invalidation_condition,
            ),
            trail=trail,
            time_stop=time_stop,
            thesis_invalidation=thesis_invalidation,
        )

        # Take-profit legs (50% / 50% split — configurable later)
        take_profit = [
            TakeProfitLeg(
                leg=1, price=round(tp1_price, 2), size_pct=50,
                reason=f"{anchor.pattern_name or 'pattern'}_tp1",
            ),
            TakeProfitLeg(
                leg=2, price=round(tp2_price, 2), size_pct=50,
                reason=f"{anchor.pattern_name or 'pattern'}_tp2",
            ),
        ]

        setup = Setup(
            direction=direction,
            entry=entry,
            take_profit=take_profit,
            stop_loss=stop_loss,
        )

        # Risk block — dict so portfolio_manager can ship without touching
        # the TradePlan schema every time we add a field.
        risk = {
            "r_per_share": round(r_per_share, 2),
            "position_size_shares": shares,
            "position_notional_usd": round(notional, 2),
            "position_risk_usd": round(position_risk_usd, 2),
            "position_risk_pct_of_equity": (
                round(position_risk_usd / account.equity * 100, 3)
                if account.equity > 0 else 0.0
            ),
            "position_notional_pct_of_equity": (
                round(notional / account.equity * 100, 2)
                if account.equity > 0 else 0.0
            ),
            "r_multiple_to_tp1": round(r_to_tp1, 2),
            "r_multiple_to_tp2": round(r_to_tp2, 2),
        }

        # Execution hints (the executioner makes the final routing decision)
        execution = {
            "preferred_algo": self._settings.execution.default_algo,
            "participation_cap_pct_adv": self._settings.risk_defaults.participation_cap_pct_adv,
            "max_spread_bps_to_cross": self._settings.risk_defaults.max_spread_bps_to_cross,
            "urgency": "low",
            "broker": account.broker,
            "account_type": mode,
        }

        # Thesis — aggregate signal metadata
        unique_lenses = sorted({s.lens for s in all_signals})
        unique_patterns = sorted({s.pattern_name for s in all_signals
                                  if s.pattern_name})
        avg_strength = sum(s.strength for s in all_signals) / len(all_signals)
        summary_patterns = ", ".join(unique_patterns) if unique_patterns else "multi-lens"
        thesis = {
            "summary": f"{direction.upper()} {symbol} — {summary_patterns} "
                       f"({len(all_signals)} signals across {len(unique_lenses)} lens(es))",
            "lenses_contributing": unique_lenses,
            "signal_ids": [s.signal_id for s in all_signals],
            "conviction": round(avg_strength, 2),
            "expected_holding_period": holding_period,
            "similar_past_setups": [],  # Phase 7 memory lookup
            "memory_win_rate": None,
            "memory_avg_r": None,
        }

        # Evidence — flatten from every contributing signal
        evidence: list[dict] = []
        for s in all_signals:
            for ev in s.evidence:
                evidence.append({"type": ev.type, "ref": ev.ref})

        # Instrument — minimal; upstream pipelines can enrich sector/industry
        exchange = "NASDAQ"  # TODO: lookup via universe filter preset
        instrument = {
            "symbol": symbol,
            "asset_class": "equity",
            "exchange": exchange,
            "sector": None,
            "industry": None,
        }

        chart_url = (
            f"https://www.tradingview.com/chart/?symbol={exchange}:{symbol}&interval=D"
        )

        plan = TradePlan(
            mode=mode,
            instrument=instrument,
            thesis=thesis,
            setup=setup,
            risk=risk,
            execution=execution,
            evidence=evidence,
            tradingview_chart_url=chart_url,
        )
        logger.info(
            "TradePlan %s %s %s shares=%d risk=$%.2f R_tp1=%.2f conviction=%.2f",
            plan.plan_id, symbol, direction, shares,
            position_risk_usd, r_to_tp1, avg_strength,
        )
        return plan


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #


def _compute_position_size(
    *,
    equity: float,
    r_per_share: float,
    risk_pct_per_trade: float,
) -> int:
    """Fixed-fractional sizing. ``risk_pct_per_trade`` is a % (0.5 = 0.5%)."""
    if equity <= 0 or r_per_share <= 0:
        return 0
    cap_usd = equity * risk_pct_per_trade / 100.0
    return max(0, math.floor(cap_usd / r_per_share))


def _apply_per_account_size_override(
    shares_from_pct: int, *, entry_price: float, account, logger,
) -> int:
    """If the active broker_account has ``extra.position_size_usd``,
    override the %-of-equity sizing with a fixed-dollar position.

    Caps at the smaller of override-shares vs %-shares × 5 (sanity
    guard so a misconfigured override can't 5×-overshoot the original
    risk budget). Account.cash is checked too — refuses if the
    notional exceeds 95% of cash.
    """
    import asyncio as _asyncio
    try:
        # Run the async account_service lookup synchronously since
        # portfolio_manager is sync. We're inside an event loop, so
        # use the running loop's run_coroutine_threadsafe pattern OR
        # fetch synchronously via a fresh task.
        from services import account_service
        try:
            loop = _asyncio.get_running_loop()
            future = _asyncio.run_coroutine_threadsafe(
                account_service.get_active_account(), loop,
            )
            active = future.result(timeout=2.0)
        except RuntimeError:
            # No running loop — call directly in a fresh one
            active = _asyncio.run(account_service.get_active_account())
    except Exception:                                                 # noqa: BLE001
        return shares_from_pct

    if not active:
        return shares_from_pct
    extra = active.get("extra") or {}
    position_size_usd = extra.get("position_size_usd")
    if not position_size_usd or float(position_size_usd) <= 0:
        return shares_from_pct

    pos_usd = float(position_size_usd)
    override_shares = max(0, math.floor(pos_usd / entry_price))

    # Guard: never let the override exceed 5× the %-calc shares
    if shares_from_pct > 0 and override_shares > shares_from_pct * 5:
        logger.warning(
            "position_size_usd override %.2f produces %d shares vs %d "
            "from %%-calc; capping at 5× = %d for safety",
            pos_usd, override_shares, shares_from_pct, shares_from_pct * 5,
        )
        override_shares = shares_from_pct * 5

    # Guard: refuse if notional exceeds 95% of cash
    notional = override_shares * entry_price
    cash = float(getattr(account, "cash", 0) or 0)
    if cash > 0 and notional > cash * 0.95:
        logger.warning(
            "position_size_usd override notional $%.2f exceeds 95%% of "
            "cash $%.2f; falling back to %%-calc (%d shares)",
            notional, cash, shares_from_pct,
        )
        return shares_from_pct

    logger.info(
        "position_size_usd override active: $%.2f / $%.2f entry = %d shares "
        "(%%-calc was %d)",
        pos_usd, entry_price, override_shares, shares_from_pct,
    )
    return override_shares
