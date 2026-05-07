"""quant_sentiment_backtest.py — backtest harness for the Alpha Score loop.

Walks each symbol through history with daily resolution, computes the
Alpha Score at every decision date, simulates a trade when the score
qualifies, and aggregates expectancy by alpha bucket. Also produces
per-tag correlation stats so the operator can answer the optimizer
question from the spec: *"which news tags correlate with post-VCP
breakout success?"*.

Trade rule (intentionally simple, deterministic):

* **Entry trigger**: ``adjusted_composite >= entry_threshold`` AND
  ``sub_scores["price_action"].score >= 60``.
* **Entry price**: next bar's open after the decision bar.
* **Exit**: whichever comes first —
    - hit a +R profit target (default ``target_atr_mult * atr14``),
    - hit a -1R stop (``stop_atr_mult * atr14``),
    - hold for ``max_hold_bars`` bars and exit at close.
* **Position size**: 1 unit of equity (we report pct returns so size
  doesn't matter for expectancy comparison).

Expectancy per bucket:

    expectancy_pct = win_rate * avg_win_pct + (1 - win_rate) * avg_loss_pct

The harness is *not* trying to mimic the production
``services/pipeline_service`` — that would require driving the full
compliance + risk gates, which is a separate concern. This is the
research tool the spec calls out: it answers "what is the edge of
the alpha-score signal?" and nothing more.
"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd

from agents.alpha_score_agent import HIGH_THRESHOLD, MEDIUM_THRESHOLD, score_symbol
from models.alpha_score import AlphaScore, BacktestTrade, ExpectancyReport, WEIGHTS

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Trade simulation
# --------------------------------------------------------------------------- #


def _simulate_trade(
    bars: pd.DataFrame,
    entry_idx: int,
    *,
    target_atr_mult: float,
    stop_atr_mult: float,
    max_hold_bars: int,
) -> dict[str, Any] | None:
    """Walk forward from ``entry_idx + 1`` (next-bar open entry) and exit
    on first stop/target/time-stop. Returns dict or None if entry impossible."""
    if entry_idx + 1 >= len(bars):
        return None

    entry_bar = bars.iloc[entry_idx]
    entry_open_bar = bars.iloc[entry_idx + 1]
    atr = entry_bar.get("atr_14")
    if atr is None or pd.isna(atr) or atr <= 0:
        return None

    entry_price = float(entry_open_bar["open"])
    target = entry_price + target_atr_mult * float(atr)
    stop = entry_price - stop_atr_mult * float(atr)

    last_idx = min(entry_idx + 1 + max_hold_bars, len(bars) - 1)
    exit_price = None
    exit_idx = None
    exit_reason = None

    for j in range(entry_idx + 1, last_idx + 1):
        b = bars.iloc[j]
        hi = float(b["high"])
        lo = float(b["low"])
        # Stop fires first when both touched in same bar (conservative).
        if lo <= stop:
            exit_price = stop
            exit_idx = j
            exit_reason = "stop"
            break
        if hi >= target:
            exit_price = target
            exit_idx = j
            exit_reason = "target"
            break

    if exit_price is None:
        b = bars.iloc[last_idx]
        exit_price = float(b["close"])
        exit_idx = last_idx
        exit_reason = "time_stop"

    pnl_pct = (exit_price - entry_price) / entry_price * 100
    pnl_r = (exit_price - entry_price) / (entry_price - stop) if (entry_price - stop) > 0 else 0

    return {
        "entry_idx": entry_idx + 1,
        "exit_idx": exit_idx,
        "entry_ts": entry_open_bar.name,
        "exit_ts": bars.iloc[exit_idx].name,
        "entry_price": round(entry_price, 4),
        "exit_price": round(exit_price, 4),
        "pnl_pct": round(pnl_pct, 3),
        "pnl_r": round(pnl_r, 3),
        "win": pnl_pct > 0,
        "exit_reason": exit_reason,
        "holding_bars": exit_idx - entry_idx,
    }


# --------------------------------------------------------------------------- #
# Backtest loop
# --------------------------------------------------------------------------- #


async def backtest_symbol(
    symbol: str,
    *,
    start: datetime,
    end: datetime,
    entry_threshold: float = HIGH_THRESHOLD,
    target_atr_mult: float = 2.0,
    stop_atr_mult: float = 1.0,
    max_hold_bars: int = 10,
    decision_step_days: int = 1,
    benchmark: str = "SPY",
) -> tuple[list[BacktestTrade], list[AlphaScore]]:
    """Backtest one symbol across [start, end]. Returns trades + per-decision scores."""
    from services.data_service import DataNotAvailableError, get_bars  # lazy import
    from services.indicator_service import add_indicators
    try:
        bars_full = await get_bars(symbol, "1d", as_of_ts=pd.Timestamp(end), min_bars=220)
    except DataNotAvailableError as e:
        log.warning("backtest_symbol: %s no bars: %s", symbol, e)
        return [], []

    bars_full = add_indicators(bars_full)
    in_window = (bars_full.index >= pd.Timestamp(start, tz="UTC")) & (bars_full.index <= pd.Timestamp(end, tz="UTC"))
    decision_bars = bars_full[in_window]
    if decision_bars.empty:
        return [], []

    trades: list[BacktestTrade] = []
    scores: list[AlphaScore] = []

    # Sample every Nth bar to keep cost reasonable; daily by default.
    indices = list(range(0, len(decision_bars), decision_step_days))
    skip_until_idx = -1

    for i in indices:
        bar_ts = decision_bars.index[i]
        global_idx = bars_full.index.get_loc(bar_ts)
        if global_idx <= skip_until_idx:
            continue

        as_of = bar_ts.to_pydatetime()
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)

        try:
            score = await score_symbol(symbol, as_of_ts=as_of, benchmark=benchmark)
        except Exception as e:                     # noqa: BLE001
            log.warning("backtest_symbol: score failed @ %s: %s", as_of, e)
            continue

        scores.append(score)
        if score.blocked:
            continue
        if score.adjusted_composite < entry_threshold:
            continue
        pa = score.sub_scores.get("price_action")
        if pa is None or pa.score < 60:
            continue

        trade = _simulate_trade(
            bars_full, global_idx,
            target_atr_mult=target_atr_mult,
            stop_atr_mult=stop_atr_mult,
            max_hold_bars=max_hold_bars,
        )
        if trade is None:
            continue
        skip_until_idx = trade["exit_idx"]

        trades.append(BacktestTrade(
            symbol=symbol,
            entry_ts=trade["entry_ts"].to_pydatetime() if hasattr(trade["entry_ts"], "to_pydatetime") else trade["entry_ts"],
            exit_ts=trade["exit_ts"].to_pydatetime() if hasattr(trade["exit_ts"], "to_pydatetime") else trade["exit_ts"],
            direction="long",
            entry_price=trade["entry_price"],
            exit_price=trade["exit_price"],
            alpha_score=score.adjusted_composite,
            bucket=score.bucket,
            sentiment_multiplier=score.sentiment_multiplier,
            tags=list(score.tags),
            pnl_pct=trade["pnl_pct"],
            pnl_r=trade["pnl_r"],
            holding_bars=trade["holding_bars"],
            win=trade["win"],
        ))

    return trades, scores


async def backtest_universe(
    symbols: Iterable[str],
    *,
    start: datetime,
    end: datetime,
    concurrency: int = 6,
    **kwargs,
) -> tuple[list[BacktestTrade], list[AlphaScore]]:
    """Run ``backtest_symbol`` across many symbols with bounded concurrency."""
    sem = asyncio.Semaphore(concurrency)
    syms = [s.upper() for s in symbols]

    async def _one(sym: str):
        async with sem:
            return await backtest_symbol(sym, start=start, end=end, **kwargs)

    results = await asyncio.gather(*(_one(s) for s in syms))
    all_trades: list[BacktestTrade] = []
    all_scores: list[AlphaScore] = []
    for trades, scores in results:
        all_trades.extend(trades)
        all_scores.extend(scores)
    return all_trades, all_scores


# --------------------------------------------------------------------------- #
# Reporting / expectancy
# --------------------------------------------------------------------------- #


def _bucket_from_score(score: float) -> str:
    if score >= HIGH_THRESHOLD:
        return "high"
    if score >= MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def expectancy_by_bucket(trades: list[BacktestTrade]) -> dict[str, dict[str, float]]:
    """Group trades by bucket and compute the standard expectancy stats."""
    grouped: dict[str, list[BacktestTrade]] = defaultdict(list)
    for t in trades:
        grouped[t.bucket].append(t)

    out: dict[str, dict[str, float]] = {}
    for bucket in ("high", "medium", "low"):
        ts = grouped.get(bucket, [])
        if not ts:
            out[bucket] = {
                "n": 0,
                "win_rate": 0.0,
                "avg_win_pct": 0.0,
                "avg_loss_pct": 0.0,
                "avg_r": 0.0,
                "expectancy_pct": 0.0,
                "expectancy_r": 0.0,
                "total_pnl_pct": 0.0,
            }
            continue
        wins = [t for t in ts if t.win]
        losses = [t for t in ts if not t.win]
        win_rate = len(wins) / len(ts)
        avg_win = sum(t.pnl_pct for t in wins) / len(wins) if wins else 0.0
        avg_loss = sum(t.pnl_pct for t in losses) / len(losses) if losses else 0.0
        avg_r = sum(t.pnl_r for t in ts) / len(ts)
        expectancy_pct = win_rate * avg_win + (1 - win_rate) * avg_loss
        expectancy_r = win_rate * (avg_r if avg_r > 0 else 0) + (1 - win_rate) * (avg_r if avg_r < 0 else 0)
        out[bucket] = {
            "n": len(ts),
            "win_rate": round(win_rate, 4),
            "avg_win_pct": round(avg_win, 3),
            "avg_loss_pct": round(avg_loss, 3),
            "avg_r": round(avg_r, 3),
            "expectancy_pct": round(expectancy_pct, 3),
            "expectancy_r": round(expectancy_r, 3),
            "total_pnl_pct": round(sum(t.pnl_pct for t in ts), 3),
        }
    return out


def tag_correlations(trades: list[BacktestTrade], *, min_n: int = 5) -> list[dict[str, Any]]:
    """For each tag that appears on ``min_n`` or more trades, report:
    n, tag-cohort win-rate, baseline win-rate, lift, and avg pnl pct.

    A high *lift* (tag win-rate / baseline win-rate) means the tag's
    presence correlates with breakout success — exactly what the spec's
    optimizer wants to surface."""
    baseline_wins = sum(1 for t in trades if t.win)
    baseline_wr = baseline_wins / len(trades) if trades else 0.0

    tag_buckets: dict[str, list[BacktestTrade]] = defaultdict(list)
    for t in trades:
        for tag in t.tags:
            tag_buckets[tag].append(t)

    rows: list[dict[str, Any]] = []
    for tag, ts in tag_buckets.items():
        if len(ts) < min_n:
            continue
        wins = sum(1 for t in ts if t.win)
        wr = wins / len(ts)
        avg_pnl = sum(t.pnl_pct for t in ts) / len(ts)
        lift = (wr / baseline_wr) if baseline_wr > 0 else 0.0
        rows.append({
            "tag": tag,
            "n": len(ts),
            "win_rate": round(wr, 4),
            "lift_vs_baseline": round(lift, 3),
            "avg_pnl_pct": round(avg_pnl, 3),
        })
    rows.sort(key=lambda r: r["lift_vs_baseline"], reverse=True)
    return rows


def build_report(
    trades: list[BacktestTrade],
    *,
    universe_size: int,
) -> ExpectancyReport:
    """Materialize the ExpectancyReport from a list of backtest trades."""
    by_bucket = expectancy_by_bucket(trades)
    tags = tag_correlations(trades)

    notes: list[str] = []
    high = by_bucket.get("high", {}).get("expectancy_pct", 0.0)
    low = by_bucket.get("low", {}).get("expectancy_pct", 0.0)
    if high and low:
        if high > low:
            notes.append(
                f"high-bucket expectancy ({high}%) exceeds low-bucket ({low}%) by "
                f"{high - low:+.2f} pct — alpha signal carries edge"
            )
        else:
            notes.append(
                f"high-bucket expectancy ({high}%) does NOT exceed low-bucket "
                f"({low}%) — re-check weights or universe"
            )

    return ExpectancyReport(
        universe_size=universe_size,
        trades_total=len(trades),
        by_bucket=by_bucket,
        tag_correlations=tags,
        weights_used=dict(WEIGHTS),
        notes=notes,
    )
