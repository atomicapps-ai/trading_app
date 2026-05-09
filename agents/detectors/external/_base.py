"""Shared scaffolding for external strategy detectors.

Each external detector module exposes:

    PARAMETER_SPEC: dict[str, dict]    # name → {default, sweep, type, reasoning}
    META: dict                          # bar_interval, family, source_url, etc.

    def detect(bars: pd.DataFrame, params: dict) -> list[Signal]:
        ...

The optimizer iterates `PARAMETER_SPEC` to build sweep grids and calls
`detect()` once per (symbol, params) combo. The signals are then run through
the shared `simulate_trades()` to produce a uniform trade ledger that gets
scored.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd


@dataclass
class Signal:
    """One entry signal emitted by a detector. Exit logic is handled by
    `simulate_trades()` based on stop/TP/time-stop fields."""
    bar_idx: int                                   # index into bars DataFrame
    direction: Literal["long", "short"]
    entry_price: float
    stop_price: float                              # absolute price, not %
    take_profit_price: float | None = None         # absolute, optional
    time_stop_bars: int | None = None              # max bars to hold
    note: str = ""                                 # for debugging


@dataclass
class Trade:
    """One closed trade. The unit of measurement for backtest scoring."""
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    direction: Literal["long", "short"]
    entry_price: float
    exit_price: float
    stop_price: float
    take_profit_price: float | None
    bars_held: int
    exit_reason: Literal["stop", "tp", "time_stop", "opposite_signal", "end_of_data"]
    pnl_pct: float                                 # (exit-entry)/entry, signed by direction
    pnl_r: float                                   # (exit-entry)/(entry-stop), signed
    win: bool


def simulate_trades(
    bars: pd.DataFrame,
    signals: list[Signal],
    *,
    on_opposite_signal: Literal["close", "ignore"] = "close",
) -> list[Trade]:
    """Walk bars chronologically, track open position, exit per Signal rules.

    Single-position model: at most one open trade at any time. New signals
    that fire while a trade is open are ignored unless ``on_opposite_signal``
    is ``"close"`` and the new signal direction is opposite — in which case
    the open trade closes at this bar's close and the new signal opens after.

    Bars must be tz-aware DateTimeIndex with columns open/high/low/close.
    """
    if not signals:
        return []
    sig_by_idx = {s.bar_idx: s for s in sorted(signals, key=lambda x: x.bar_idx)}

    trades: list[Trade] = []
    open_sig: Signal | None = None
    open_idx: int = -1
    bars_held = 0

    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    close = bars["close"].to_numpy()
    n = len(bars)

    for i in range(n):
        # Check exits on existing position first
        if open_sig is not None:
            bars_held = i - open_idx
            exit_price: float | None = None
            exit_reason: str | None = None

            # Stop check (intra-bar — touched on this bar's range)
            if open_sig.direction == "long":
                if low[i] <= open_sig.stop_price:
                    exit_price = open_sig.stop_price
                    exit_reason = "stop"
                elif (open_sig.take_profit_price is not None
                      and high[i] >= open_sig.take_profit_price):
                    exit_price = open_sig.take_profit_price
                    exit_reason = "tp"
            else:  # short
                if high[i] >= open_sig.stop_price:
                    exit_price = open_sig.stop_price
                    exit_reason = "stop"
                elif (open_sig.take_profit_price is not None
                      and low[i] <= open_sig.take_profit_price):
                    exit_price = open_sig.take_profit_price
                    exit_reason = "tp"

            # Time stop
            if (exit_reason is None
                    and open_sig.time_stop_bars is not None
                    and bars_held >= open_sig.time_stop_bars):
                exit_price = float(close[i])
                exit_reason = "time_stop"

            # Opposite signal closes existing position
            new_sig = sig_by_idx.get(i)
            if (exit_reason is None
                    and new_sig is not None
                    and on_opposite_signal == "close"
                    and new_sig.direction != open_sig.direction):
                exit_price = float(close[i])
                exit_reason = "opposite_signal"

            if exit_reason is not None:
                trades.append(_make_trade(
                    open_sig, exit_price, exit_reason,
                    bars.index[open_idx], bars.index[i], bars_held,
                ))
                open_sig = None
                open_idx = -1
                bars_held = 0

        # Open a new position if signal fires this bar and we're flat
        if open_sig is None:
            new_sig = sig_by_idx.get(i)
            if new_sig is not None:
                open_sig = new_sig
                open_idx = i
                bars_held = 0

    # Force-close any remaining open trade at end of data
    if open_sig is not None:
        trades.append(_make_trade(
            open_sig, float(close[-1]), "end_of_data",
            bars.index[open_idx], bars.index[-1], n - 1 - open_idx,
        ))

    return trades


def _make_trade(
    sig: Signal,
    exit_price: float,
    exit_reason: str,
    entry_ts: pd.Timestamp,
    exit_ts: pd.Timestamp,
    bars_held: int,
) -> Trade:
    if sig.direction == "long":
        pnl_pct = (exit_price - sig.entry_price) / sig.entry_price
        r_denom = sig.entry_price - sig.stop_price
    else:
        pnl_pct = (sig.entry_price - exit_price) / sig.entry_price
        r_denom = sig.stop_price - sig.entry_price

    pnl_r = (
        ((exit_price - sig.entry_price) / r_denom)
        if sig.direction == "long" and r_denom > 0
        else (sig.entry_price - exit_price) / r_denom
        if sig.direction == "short" and r_denom > 0
        else 0.0
    )
    return Trade(
        entry_ts=entry_ts,
        exit_ts=exit_ts,
        direction=sig.direction,
        entry_price=sig.entry_price,
        exit_price=exit_price,
        stop_price=sig.stop_price,
        take_profit_price=sig.take_profit_price,
        bars_held=bars_held,
        exit_reason=exit_reason,                                       # type: ignore[arg-type]
        pnl_pct=pnl_pct,
        pnl_r=pnl_r,
        win=pnl_pct > 0,
    )


def summarize_trades(trades: list[Trade], capital_per_trade_usd: float = 10_000.0) -> dict:
    """Compute the metrics the optimizer scores on."""
    n = len(trades)
    if n == 0:
        return dict(
            n_trades=0, wins=0, losses=0, wr_pct=0.0, profit_factor=0.0,
            net_pnl_usd=0.0, gross_profit_usd=0.0, gross_loss_usd=0.0,
            avg_r_multiple=0.0, max_drawdown_pct=0.0, score=0.0,
        )
    wins = [t for t in trades if t.win]
    losses = [t for t in trades if not t.win]
    gp = sum(t.pnl_pct for t in wins) * capital_per_trade_usd
    gl = -sum(t.pnl_pct for t in losses) * capital_per_trade_usd  # positive number
    pf = (gp / gl) if gl > 0 else float("inf") if gp > 0 else 0.0
    wr = len(wins) / n * 100.0
    avg_r = sum(t.pnl_r for t in trades) / n

    # Max drawdown on equity curve
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        eq += t.pnl_pct * capital_per_trade_usd
        peak = max(peak, eq)
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd
    max_dd_pct = (max_dd / capital_per_trade_usd) * 100.0

    # Score: (PF-1) * log(N) * WR%/100, with PF=inf clamped to 5.0
    import math
    pf_clamped = min(pf, 5.0) if pf != float("inf") else 5.0
    score = max(0.0, pf_clamped - 1.0) * math.log(max(n, 1)) * (wr / 100.0)

    return dict(
        n_trades=n,
        wins=len(wins),
        losses=len(losses),
        wr_pct=round(wr, 2),
        profit_factor=round(pf, 3) if pf != float("inf") else 999.0,
        net_pnl_usd=round(gp - gl, 2),
        gross_profit_usd=round(gp, 2),
        gross_loss_usd=round(gl, 2),
        avg_r_multiple=round(avg_r, 3),
        max_drawdown_pct=round(max_dd_pct, 2),
        score=round(score, 4),
    )
