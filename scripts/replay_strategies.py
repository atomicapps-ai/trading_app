"""scripts/replay_strategies.py — multi-strategy intraday backtest.

Compares the Double Lock (DL) strategy against two community-style
intraday strategies on the same universe + window + exit assumptions:

  - DL                : c1+c2 conviction + regime gate (the existing one)
  - ORB-30m           : breakout above/below the 9:30-10:00 ET 30-min range
  - VWAP-Reclaim-1030 : c1 closes one side of intraday VWAP, c2 reclaims
                        it (long if reclaim is upward; short if downward)

All three strategies share:
  - Same 30m bar data (yfinance)
  - Same exit rule: market close at 15:00 ET, OR a 3% catastrophic
    stop on the entry-side direction, whichever first
  - Same per-trade dollar capital (default $10k) for $ comparison

The 3% catastrophic stop is the DL spec; using it for all three keeps
the comparison apples-to-apples even though ORB normally uses the
opposite-end of the opening range as the stop.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import date, datetime, time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Reuse the simulation primitives from replay_dl
from scripts.replay_dl import (                                       # noqa: E402
    ReplayTrade, _full_frames, _simulate_exit, _trading_days,
    _vix_prev_close_map, _load_cat_stop_pct, _as_of_for,
)


# --------------------------------------------------------------------------- #
# Strategy 1: ORB-30m (Opening Range Breakout)
# --------------------------------------------------------------------------- #


def _detect_orb(today_bars, *, cat_stop_pct: float):
    """Identify ORB entry+direction from the day's 30m bars.

    Algorithm:
      - c1 (9:30-10:00) defines the opening range high/low
      - From 10:00 onward, first 30m close above c1.high => LONG entry
        at that bar's close; or first close below c1.low => SHORT
      - If neither triggers, no trade
      - Stop = 3% catastrophic (matches DL for fair comparison)

    Returns (direction, entry_price, stop_price, entry_bar_time) or None.
    """
    if len(today_bars) < 2:
        return None
    c1 = today_bars.iloc[0]
    if c1.name.time() != dtime(9, 30):
        return None
    c1_hi, c1_lo = float(c1["high"]), float(c1["low"])

    # Walk the rest of the day looking for the first close that breaks
    # outside the opening range.
    for i in range(1, len(today_bars)):
        bar = today_bars.iloc[i]
        # Bracket trigger logic — if you take both, you'd whipsaw.
        # Pick whichever side breaks first by close.
        c = float(bar["close"])
        if c > c1_hi:
            entry = c
            stop = round(entry * (1 - cat_stop_pct / 100.0), 2)
            return ("long", entry, stop, bar.name)
        if c < c1_lo:
            entry = c
            stop = round(entry * (1 + cat_stop_pct / 100.0), 2)
            return ("short", entry, stop, bar.name)
    return None


# --------------------------------------------------------------------------- #
# Strategy 2: VWAP Reclaim at 10:30
# --------------------------------------------------------------------------- #


def _intraday_vwap_through(today_bars, idx: int) -> float | None:
    """Volume-weighted average price using bars 0..idx inclusive.
    Typical price = (H+L+C)/3 per bar; weighted by volume."""
    if idx < 0 or idx >= len(today_bars):
        return None
    pv = 0.0
    v = 0.0
    for i in range(idx + 1):
        b = today_bars.iloc[i]
        tp = (float(b["high"]) + float(b["low"]) + float(b["close"])) / 3.0
        vol = float(b["volume"])
        pv += tp * vol
        v += vol
    return pv / v if v > 0 else None


def _detect_vwap_reclaim(today_bars, *, cat_stop_pct: float):
    """Detect a c1->c2 VWAP-reclaim signal.

    Signal:
      - c1 (9:30) closes BELOW intraday VWAP-through-c1
      - c2 (10:00) closes ABOVE intraday VWAP-through-c2  -> LONG
      OR mirror for SHORT (c1 closes above, c2 closes below)

    Entry  : c2 close
    Stop   : 3% catastrophic
    Returns (direction, entry, stop, entry_bar_time) or None.
    """
    if len(today_bars) < 2:
        return None
    c1 = today_bars.iloc[0]
    c2 = today_bars.iloc[1]
    if c1.name.time() != dtime(9, 30) or c2.name.time() != dtime(10, 0):
        return None

    vwap_c1 = _intraday_vwap_through(today_bars, 0)
    vwap_c2 = _intraday_vwap_through(today_bars, 1)
    if vwap_c1 is None or vwap_c2 is None:
        return None

    c1_close = float(c1["close"])
    c2_close = float(c2["close"])

    # LONG reclaim: was below, now above
    if c1_close < vwap_c1 and c2_close > vwap_c2:
        entry = c2_close
        stop = round(entry * (1 - cat_stop_pct / 100.0), 2)
        return ("long", entry, stop, c2.name)
    # SHORT reclaim
    if c1_close > vwap_c1 and c2_close < vwap_c2:
        entry = c2_close
        stop = round(entry * (1 + cat_stop_pct / 100.0), 2)
        return ("short", entry, stop, c2.name)
    return None


# --------------------------------------------------------------------------- #
# Strategy 3: Double Lock (existing detector — wire it for parity)
# --------------------------------------------------------------------------- #


def _detect_dl_wrapper(today_bars, daily_ind, vix_prev, config, as_of_ts, sym):
    """Thin wrapper so the strategy plug-in interface is uniform."""
    from agents.detectors.double_lock_filtered import detect_double_lock_filtered

    pat = detect_double_lock_filtered(
        bars_30m=today_bars.iloc[:0].append(today_bars) if False else
                 today_bars.copy(),  # detector reads bars_30m as the full bar set
        daily=daily_ind, vix_prev_close=vix_prev,
        config=config, as_of_ts=as_of_ts,
    )
    if pat is None:
        return None
    direction = pat.direction.lower()
    entry = float(pat.entry_price)
    stop = float(pat.stop_price)
    return (direction, entry, stop, today_bars.iloc[1].name)


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #


@dataclass
class StrategyResult:
    name: str
    trades: list[ReplayTrade]


async def replay_one_strategy(
    name: str,
    detector,                # callable taking (today_bars, sym, daily_ind, vix_prev) -> tuple|None
    *,
    symbols: list[str],
    since: date,
    until: date,
    cat_stop_pct: float = 3.0,
) -> StrategyResult:
    days = _trading_days(since, until)
    sym_data = {}
    for sym in symbols:
        b, d = await _full_frames(sym, force_refresh=False)
        if b is None or d is None or b.empty or d.empty:
            continue
        sym_data[sym] = (b, d)
    vix_by_date = await _vix_prev_close_map(force_refresh=False)

    trades: list[ReplayTrade] = []
    for d in days:
        as_of = _as_of_for(d)
        vix_prev = vix_by_date.get(d)
        for sym, (bars30, daily_d) in sym_data.items():
            today_bars = bars30[bars30.index.tz_convert("America/New_York").date == d]
            if len(today_bars) < 2:
                continue
            try:
                sig = detector(today_bars, sym, daily_d, vix_prev, as_of)
            except Exception:
                continue
            if sig is None:
                continue
            direction, entry, stop, _entry_ts = sig

            exit_pair = await _simulate_exit(sym, d, entry, stop, direction.upper())
            if exit_pair is None:
                continue
            exit_px, exit_reason = exit_pair

            sign = 1 if direction == "long" else -1
            pnl_pct = sign * (exit_px - entry) / entry * 100.0
            pnl_per_100 = sign * (exit_px - entry) * 100.0

            trades.append(ReplayTrade(
                date_str=d.isoformat(),
                symbol=sym,
                direction=direction.upper(),
                entry=round(entry, 2),
                stop=round(stop, 2),
                exit_px=round(exit_px, 2),
                exit_reason=exit_reason,
                pnl_pct=round(pnl_pct, 2),
                pnl_dollars_per_100shr=round(pnl_per_100, 2),
                win=pnl_pct > 0,
                pqs=0,
                notes=name,
            ))
    return StrategyResult(name=name, trades=trades)


def _summarize(name: str, trades: list[ReplayTrade], capital: float) -> dict:
    if not trades:
        return {"name": name, "n": 0}
    wins = sum(1 for t in trades if t.win)
    losses = len(trades) - wins
    wr = wins / len(trades) * 100
    pcts = [t.pnl_pct for t in trades]
    total_pct = sum(pcts)
    gross_profit = sum(capital * p / 100 for p in pcts if p > 0)
    gross_loss = sum(-capital * p / 100 for p in pcts if p < 0)
    net = gross_profit - gross_loss
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    longs = sum(1 for t in trades if t.direction == "LONG")
    shorts = len(trades) - longs
    return {
        "name": name,
        "n": len(trades),
        "wins": wins, "losses": losses, "wr": wr,
        "total_pct": total_pct,
        "best_pct": max(pcts), "worst_pct": min(pcts),
        "longs": longs, "shorts": shorts,
        "gross_profit_usd": gross_profit,
        "gross_loss_usd": gross_loss,
        "net_usd": net,
        "pf": pf,
    }


def _print_summaries(summaries: list[dict], capital: float) -> None:
    print()
    print("=" * 92)
    print(f"COMPARISON  (capital per trade: ${capital:,.0f})")
    print("=" * 92)
    print(f"{'Strategy':22s} {'N':>4s} {'WR%':>6s} {'PF':>5s} "
          f"{'Net $':>10s} {'GP $':>10s} {'GL $':>10s} {'Tot %':>7s} {'L/S':>8s}")
    print("-" * 92)
    for s in summaries:
        if s["n"] == 0:
            print(f"{s['name']:22s} {0:>4d}  (no trades)")
            continue
        pf_str = f"{s['pf']:.2f}" if s['pf'] != float('inf') else 'inf'
        print(f"{s['name']:22s} {s['n']:>4d} {s['wr']:>6.1f} {pf_str:>5s} "
              f"${s['net_usd']:>9,.0f} ${s['gross_profit_usd']:>9,.0f} "
              f"${s['gross_loss_usd']:>9,.0f} {s['total_pct']:>+7.2f} "
              f"{s['longs']:>3d}/{s['shorts']:<3d}")


async def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    BELLWETHER_16 = ['AMD','AMZN','BA','COST','GS','HD','INTC','IWM','META',
                     'ORCL','SPY','TSLA','XLF','AAPL','MSFT','NVDA']
    SINCE = date(2026, 1, 1)
    UNTIL = date.today()
    CAPITAL = 10_000.0

    cat_stop = _load_cat_stop_pct("double_lock")

    # Load DL config once
    import yaml
    from services.settings_service import STRATEGY_CONFIG_DIR
    dl_cfg = yaml.safe_load(
        (STRATEGY_CONFIG_DIR / "double_lock.yaml").read_text(encoding="utf-8")
    )

    print(f"Window: {SINCE} -> {UNTIL}  ({len(BELLWETHER_16)} symbols)")
    print(f"Capital: ${CAPITAL:,.0f}/trade  Stop: {cat_stop}% catastrophic")
    print()

    # Detector adapters that wrap the per-strategy detection logic into
    # a uniform (today_bars, sym, daily_ind, vix_prev, as_of) -> sig signature.
    def dl_detect(today_bars, sym, daily_ind, vix_prev, as_of):
        from agents.detectors.double_lock_filtered import detect_double_lock_filtered
        # Detector wants the full intraday cache for slot-volume-median.
        # We pass the today-only frame; it mostly works because DL only
        # reads c1+c2; slot median falls back to 0 -> always fails the
        # vol filter in this slim mode. So instead get the full cache.
        # The replay_dl uses bars30 (full cache); replicate that:
        from services import data_service
        # Pull from cache: in-memory chain via the full frame again
        # (fast since cached). This is wasteful but correct.
        # Actually we already loaded the full frame in replay_one_strategy
        # via _full_frames. We don't have access here; cheap workaround:
        # call the detector with what we have plus a bigger context.
        # Use bars30_full from the closure if possible — but our adapter
        # doesn't have it. Skip DL via this path; we'll run the proper
        # replay_dl.replay() instead and merge results.
        return None

    # 1. Run DL via the proper replay_dl.replay() which uses full bars30 frames
    from scripts.replay_dl import replay as dl_replay
    dl_trades = await dl_replay(
        BELLWETHER_16, since=SINCE, until=UNTIL, strategy="double_lock",
    )

    # 2. Run ORB
    def orb_detect(today_bars, sym, daily_ind, vix_prev, as_of):
        return _detect_orb(today_bars, cat_stop_pct=cat_stop)

    orb_result = await replay_one_strategy(
        "ORB-30m", orb_detect,
        symbols=BELLWETHER_16, since=SINCE, until=UNTIL, cat_stop_pct=cat_stop,
    )

    # 3. Run VWAP-Reclaim
    def vwap_detect(today_bars, sym, daily_ind, vix_prev, as_of):
        return _detect_vwap_reclaim(today_bars, cat_stop_pct=cat_stop)

    vwap_result = await replay_one_strategy(
        "VWAP-Reclaim-1030", vwap_detect,
        symbols=BELLWETHER_16, since=SINCE, until=UNTIL, cat_stop_pct=cat_stop,
    )

    summaries = [
        _summarize("Double-Lock (DL)", dl_trades, CAPITAL),
        _summarize("ORB-30m", orb_result.trades, CAPITAL),
        _summarize("VWAP-Reclaim-1030", vwap_result.trades, CAPITAL),
    ]
    _print_summaries(summaries, CAPITAL)


if __name__ == "__main__":
    asyncio.run(main())
