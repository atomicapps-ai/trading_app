"""CopyTrader agent — converts a politician's disclosed trade into a TradePlan.

Position sizing logic
---------------------
We don't try to match the politician's dollar amount (they often report
$100K–$250K ranges that are far outside most retail account sizes).
Instead we cap at `max_per_trade_usd` (default $5,000) from config and
let the risk manager resize if needed.

Options handling
----------------
Capitol Trades disclosures identify options (calls/puts) but rarely
include strike or expiration. When asset_type is "option" we copy the
*underlying stock* and note the approximation in the thesis. A future
iteration can query SEC EDGAR option filings for full contract details.

Entry type
----------
TradePlan requires Literal["limit","stop","market_on_trigger"] — there is
no plain "market" type. We use a *limit* order priced 0.5% above the ask
(for buys) or 0.5% below the bid (for sells) so we get immediate fills
while still expressing a price limit.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from models.account import AccountState, Quote
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
from services.capitol_trades_service import PoliticianTrade
from services.settings_service import get_settings

logger = logging.getLogger(__name__)

# Default risk per trade as a fraction of price (4% stop)
_STOP_PCT = 0.04
# Limit order buffer above/below quote mid (0.5%) to ensure fill
_LIMIT_BUFFER_PCT = 0.005


class CopyTrader:
    """Convert a PoliticianTrade disclosure into a TradePlan.

    Caller is responsible for running the resulting plan through
    ComplianceOfficer and RiskManager before queuing it.
    """

    def __init__(self, max_per_trade_usd: float = 5_000.0) -> None:
        self.max_per_trade_usd = max_per_trade_usd

    # ------------------------------------------------------------------ #
    # Public
    # ------------------------------------------------------------------ #

    def should_copy(self, trade: PoliticianTrade) -> tuple[bool, str]:
        """Return (ok, skip_reason). ok=False means skip this trade."""
        if not trade.ticker:
            return False, "no ticker"
        if trade.transaction_type not in ("purchase", "sale"):
            return False, f"unsupported tx_type={trade.transaction_type!r}"
        # Skip very small disclosures (under $1K)
        if trade.amount_max < 1_000:
            return False, f"amount too small ({trade.amount_max:.0f})"
        # Skip trades older than 14 days (already priced in)
        try:
            pub = datetime.fromisoformat(trade.published_date).replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - pub).days
            if age_days > 14:
                return False, f"disclosure too old ({age_days}d)"
        except ValueError:
            pass
        return True, ""

    def generate_plan(
        self,
        trade: PoliticianTrade,
        quote: Quote,
        mode: str,
    ) -> TradePlan:
        """Build a TradePlan from a politician's disclosed trade + current quote."""
        direction: str
        if trade.transaction_type == "purchase":
            direction = "long"
        else:
            direction = "short"

        mid_price = (quote.bid + quote.ask) / 2

        # Entry: limit just past mid so it fills quickly
        if direction == "long":
            entry_price = round(mid_price * (1 + _LIMIT_BUFFER_PCT), 2)
            stop_price = round(entry_price * (1 - _STOP_PCT), 2)
        else:
            entry_price = round(mid_price * (1 - _LIMIT_BUFFER_PCT), 2)
            stop_price = round(entry_price * (1 + _STOP_PCT), 2)

        risk_per_share = abs(entry_price - stop_price)
        tp_price = round(
            entry_price + (2 * risk_per_share if direction == "long" else -2 * risk_per_share),
            2,
        )

        # Position size (shares) — capped at max_per_trade_usd
        invest_usd = min(self.max_per_trade_usd, trade.amount_mid * 0.1)
        invest_usd = max(invest_usd, 100.0)  # at least $100
        shares = max(1, int(invest_usd / entry_price))
        notional = shares * entry_price
        position_risk_usd = shares * risk_per_share
        rr_ratio = round(abs(tp_price - entry_price) / risk_per_share, 2) if risk_per_share > 0 else 2.0

        is_option = trade.asset_type in ("option", "options", "call", "put")
        effective_symbol = trade.ticker

        # Deadline: 30 days out (swing trade horizon for political signals)
        deadline = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        session_end = (datetime.now(timezone.utc).replace(
            hour=21, minute=0, second=0, microsecond=0
        )).isoformat()

        thesis_lines = [
            f"Copying {trade.politician_name} ({trade.party}) "
            f"{'purchase' if direction == 'long' else 'sale'} of {trade.ticker}",
            f"Disclosed {trade.published_date} (traded {trade.transaction_date}).",
            f"Reported size: ${trade.amount_min:,.0f}–${trade.amount_max:,.0f}.",
        ]
        if is_option:
            thesis_lines.append(
                f"Original trade was {trade.asset_type}; copying underlying stock "
                f"(option strike/expiry not available in STOCK Act disclosure)."
            )

        plan = TradePlan(
            mode=mode,
            instrument={
                "symbol": effective_symbol,
                "asset_class": "us_equity",
                "exchange": "NASDAQ",
                "sector": "unknown",
                "industry": "unknown",
            },
            thesis={
                "summary": thesis_lines[0],
                "detail": " ".join(thesis_lines[1:]),
                "lenses_contributing": ["copy_trading"],
                "conviction": 0.70,
                "politician": trade.politician_name,
                "politician_slug": trade.politician_slug,
                "party": trade.party,
                "original_asset_type": trade.asset_type,
                "disclosure_date": trade.published_date,
                "trade_date": trade.transaction_date,
                "reported_amount_min": trade.amount_min,
                "reported_amount_max": trade.amount_max,
            },
            setup=Setup(
                direction=direction,
                entry=EntryOrder(
                    type="limit",
                    price=entry_price,
                    trigger_condition=None,
                    valid_until=session_end,
                ),
                take_profit=[
                    TakeProfitLeg(
                        leg=1,
                        price=tp_price,
                        size_pct=100.0,
                        reason="2R target (copy-trade swing exit)",
                    )
                ],
                stop_loss=StopLoss(
                    initial=StopLossInitial(
                        type="hard",
                        price=stop_price,
                        reason=f"{int(_STOP_PCT * 100)}% hard stop — copy trade",
                    ),
                    trail=TrailingStop(
                        active=False,
                        activate_after="price >= entry + 1.0R",
                        mode="percent",
                        percent=2.0,
                    ),
                    time_stop=TimeStop(
                        active=True,
                        condition="exit at market if position open at deadline",
                        deadline=deadline,
                    ),
                    thesis_invalidation=ThesisInvalidation(
                        active=False,
                        condition="",
                    ),
                ),
            ),
            risk={
                "r_per_share": round(risk_per_share, 4),
                "position_size_shares": shares,
                "notional": round(notional, 2),
                "position_risk_usd": round(position_risk_usd, 2),
                "max_per_trade_usd": self.max_per_trade_usd,
                "rr_ratio_planned": rr_ratio,
                "pct_of_invest": round(invest_usd / self.max_per_trade_usd * 100, 1),
            },
            execution={
                "algo": "limit_aggressive",
                "participation_cap": 0.10,
                "spread_max": 0.02,
                "broker": "alpaca",
                "account_type": "paper" if mode == "paper" else mode,
                "strategy": "copy_trading",
            },
            evidence=[
                {
                    "source": "capitol_trades",
                    "trade_id": trade.trade_id,
                    "politician": trade.politician_name,
                    "ticker": trade.ticker,
                    "asset_type": trade.asset_type,
                    "tx_type": trade.transaction_type,
                    "tx_date": trade.transaction_date,
                    "published_date": trade.published_date,
                    "amount_range": f"${trade.amount_min:,.0f}–${trade.amount_max:,.0f}",
                }
            ],
            tradingview_chart_url=f"https://www.tradingview.com/chart/?symbol={effective_symbol}",
        )
        logger.info(
            "CopyTrader: generated plan %s — %s %s %d sh @ $%.2f (stop $%.2f, tp $%.2f)",
            plan.plan_id, direction.upper(), effective_symbol,
            shares, entry_price, stop_price, tp_price,
        )
        return plan
