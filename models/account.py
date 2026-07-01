"""Account, market, order, quote, fill — broker-adapter and gate contracts."""
from typing import Literal

from pydantic import BaseModel

OrderSide = Literal["buy", "sell", "buy_to_cover", "sell_short"]
OrderType = Literal[
    "market",
    "limit",
    "stop",
    "stop_limit",
    "trailing_stop",
    "vwap_algo",
    "twap_algo",
    "pov_algo",
]
TimeInForce = Literal["day", "gtc", "ioc", "fok"]


class Quote(BaseModel):
    symbol: str
    ts: str
    bid: float
    ask: float
    bid_size: int
    ask_size: int

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_bps(self) -> float:
        m = self.mid
        if m <= 0:
            return 0.0
        return (self.ask - self.bid) / m * 10000.0


class Order(BaseModel):
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: TimeInForce = "day"
    algo: str | None = None
    extended_hours: bool = False
    # Bracket support: when order_class == "bracket", the broker attaches an
    # OCO take-profit + stop-loss to the entry so exits are enforced server-side.
    order_class: str | None = None
    take_profit_price: float | None = None
    stop_loss_price: float | None = None


class OrderAck(BaseModel):
    client_order_id: str
    broker_order_id: str | None
    accepted: bool
    ts: str
    reject_reason: str | None = None


class Fill(BaseModel):
    fill_id: str
    broker_order_id: str
    client_order_id: str
    symbol: str
    ts: str
    side: OrderSide
    price: float
    shares: int
    commission_usd: float = 0.0
    fees_usd: float = 0.0


class Position(BaseModel):
    symbol: str
    shares: int  # signed: positive = long, negative = short
    avg_entry_price: float
    market_price: float
    unrealized_pnl_usd: float
    sector: str | None = None


class AccountState(BaseModel):
    account_id: str
    broker: str
    type: Literal["cash", "margin"]
    equity: float
    cash: float
    buying_power: float
    open_positions: list[Position] = []
    realized_pnl_today: float = 0.0
    unrealized_pnl_today: float = 0.0
    trades_today: int = 0
    day_trade_count_rolling_5d: int = 0
    wash_sale_window: list[str] = []  # symbols within 30-day wash-sale window
    trading_halted: bool = False
    ts_snapshot: str


class LULDBand(BaseModel):
    lower: float
    upper: float


class MarketState(BaseModel):
    """Per-symbol microstructure snapshot consumed by compliance & risk gates."""

    symbol: str
    ts: str
    halt_status: bool = False
    ssr_active: bool = False
    luld_band: LULDBand | None = None
    earnings_within_hours: float | None = None
    adv: int  # 30-day avg daily share volume
    adv_dollar: float
    current_spread_bps: float
    vix: float | None = None
    session: Literal["pre", "regular", "post", "closed"] = "regular"
