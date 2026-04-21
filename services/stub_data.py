"""Phase 2 stub data — shared across dashboard, pending, trades templates.

Replaced by real broker / agent / JSONL reads in Phases 4–5. Kept as plain
dicts (not Pydantic models) since these are UI-shaped placeholders, not
domain objects flowing through the agent pipeline.
"""

STUB_ACCOUNT: dict = {
    "equity": 162480.00,
    "buying_power": 48220.00,
    "day_pnl_usd": 847.50,
    "day_pnl_pct": 0.52,
    "unrealized_pnl": 2340.00,
    "open_positions": 3,
    "max_positions": 8,
    "trades_today": 2,
    "mode": "paper",
    "broker": "tradestation_sim",
    "connected": True,
}

STUB_AGENTS: list[dict] = [
    {"name": "universe_filter",     "status": "green", "detail": "312 symbols · 08:00 ET"},
    {"name": "analyst",             "status": "green", "detail": "4 lenses · 3 signals today"},
    {"name": "portfolio_manager",   "status": "green", "detail": "2 plans queued"},
    {"name": "compliance_officer",  "status": "green", "detail": "0 blocks today"},
    {"name": "risk_manager",        "status": "green", "detail": "1 resize today"},
    {"name": "executioner",         "status": "amber", "detail": "awaiting approval"},
]

STUB_PENDING: list[dict] = [
    {
        "plan_id": "plan-nvda-001",
        "symbol": "NVDA",
        "direction": "long",
        "strategy": "momentum_breakout",
        "conviction": 0.74,
        "entry": 148.50,
        "stop": 146.25,
        "tp1": 153.00,
        "tp2": 157.50,
        "risk_usd": 787.50,
        "rr_tp1": 2.0,
        "rr_tp2": 4.0,
        "position_size": 350,
        "notional": 51975.00,
        "risk_pct": 0.49,
        "ts_created": "2026-04-17T10:23:00-04:00",
        "compliance": "pass",
        "risk_result": "approve",
        "lenses": ["technical", "sentiment"],
        "thesis": "RSI divergence + VWAP reclaim on analyst upgrade catalyst; momentum continuation setup.",
        "evidence": [
            {"type": "indicator", "ref": "RSI_14=33 bullish_divergence on 1h chart"},
            {"type": "indicator", "ref": "VWAP reclaim 10:18 ET on 1.8x avg volume"},
            {"type": "sentiment", "ref": "analyst_upgrade MS→Buy, novelty=0.84, relevance=0.91"},
        ],
        "similar_setups": [
            {"trade_id": "tr-past-101", "outcome_r": 2.1, "similarity": 0.82},
            {"trade_id": "tr-past-074", "outcome_r": -0.8, "similarity": 0.71},
        ],
    },
    {
        "plan_id": "plan-spy-002",
        "symbol": "SPY",
        "direction": "long",
        "strategy": "etf_sector_rotation",
        "conviction": 0.61,
        "entry": 521.40,
        "stop": 517.80,
        "tp1": 528.00,
        "tp2": 534.00,
        "risk_usd": 540.00,
        "rr_tp1": 1.8,
        "rr_tp2": 3.5,
        "position_size": 150,
        "notional": 78210.00,
        "risk_pct": 0.33,
        "ts_created": "2026-04-17T10:31:00-04:00",
        "compliance": "pass",
        "risk_result": "resize",
        "lenses": ["technical", "macro"],
        "thesis": "Sector ETF dual-momentum signal; tech leadership rotating into broad market.",
        "evidence": [
            {"type": "indicator", "ref": "SPY 20d return +2.3% > 0; 5d return +0.8% > 0"},
            {"type": "macro", "ref": "VIX = 14.2 (low regime); no FOMC within 2d"},
        ],
        "similar_setups": [
            {"trade_id": "tr-past-058", "outcome_r": 1.4, "similarity": 0.76},
        ],
    },
]

STUB_TRADES: list[dict] = [
    {
        "trade_id": "tr-001",
        "symbol": "AAPL",
        "direction": "long",
        "strategy": "mean_reversion_rsi",
        "entry": 182.30,
        "exit_avg": 187.10,
        "pnl_usd": 960.00,
        "pnl_r": 1.92,
        "mfe_r": 2.3,
        "mae_r": -0.4,
        "hold_seconds": 21600,
        "exit_reason": "tp1_hit",
        "mode": "paper",
        "ts_entered": "2026-04-16T10:15:00-04:00",
    },
    {
        "trade_id": "tr-002",
        "symbol": "MSFT",
        "direction": "long",
        "strategy": "momentum_breakout",
        "entry": 415.80,
        "exit_avg": 412.40,
        "pnl_usd": -680.00,
        "pnl_r": -0.85,
        "mfe_r": 0.6,
        "mae_r": -1.1,
        "hold_seconds": 9000,
        "exit_reason": "trailing_stop_hit",
        "mode": "paper",
        "ts_entered": "2026-04-16T13:40:00-04:00",
    },
    {
        "trade_id": "tr-003",
        "symbol": "NVDA",
        "direction": "long",
        "strategy": "sentiment_catalyst",
        "entry": 138.20,
        "exit_avg": 144.80,
        "pnl_usd": 1320.00,
        "pnl_r": 2.64,
        "mfe_r": 3.1,
        "mae_r": -0.3,
        "hold_seconds": 7200,
        "exit_reason": "tp2_hit",
        "mode": "paper",
        "ts_entered": "2026-04-15T09:45:00-04:00",
    },
]

STUB_OPEN_POSITIONS: list[dict] = [
    {
        "symbol": "TSLA", "direction": "long", "entry": 248.40, "current": 252.10,
        "pnl_usd": 555.00, "pnl_pct": 1.49, "pnl_r": 0.82, "stop": 244.20,
        "strategy": "momentum_breakout", "shares": 150,
    },
    {
        "symbol": "META", "direction": "long", "entry": 612.80, "current": 618.50,
        "pnl_usd": 855.00, "pnl_pct": 0.93, "pnl_r": 0.61, "stop": 605.00,
        "strategy": "mean_reversion_rsi", "shares": 150,
    },
    {
        "symbol": "AMZN", "direction": "long", "entry": 195.20, "current": 197.80,
        "pnl_usd": 930.00, "pnl_pct": 1.33, "pnl_r": 1.04, "stop": 192.50,
        "strategy": "momentum_breakout", "shares": 358,
    },
]

STUB_ACTIVITY: list[dict] = [
    {"ts": "11:42", "kind": "fill",       "text": "AMZN buy 358 @ 195.20 (slip 4 bps)"},
    {"ts": "11:38", "kind": "approve",    "text": "AMZN momentum_breakout — operator approved"},
    {"ts": "11:35", "kind": "risk",       "text": "AMZN resized 400 → 358 shares (R1: per-trade cap)"},
    {"ts": "11:34", "kind": "compliance", "text": "AMZN passed all 8 gates"},
    {"ts": "10:23", "kind": "plan",       "text": "NVDA momentum_breakout queued (conv 0.74)"},
    {"ts": "10:14", "kind": "signal",     "text": "NVDA technical: VWAP reclaim + RSI divergence"},
    {"ts": "09:31", "kind": "compliance", "text": "ROKU blocked — earnings within 24h"},
    {"ts": "08:00", "kind": "universe",   "text": "Universe refreshed: 312 symbols (preset: liquid_midcap_momentum)"},
]


def hold_seconds_to_human(seconds: int) -> str:
    """4h 22m / 2d 3h / 45m. Used by trades.html."""
    if seconds < 60:
        return f"{seconds}s"
    minutes, _ = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    days, hrs = divmod(hours, 24)
    return f"{days}d {hrs}h" if hrs else f"{days}d"


def time_ago(iso_ts: str, now=None) -> str:
    """Format an ISO timestamp as '12m ago', '2h ago', '3d ago'."""
    from datetime import datetime, timezone
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return ""
    now = now or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = (now - ts).total_seconds()
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"
