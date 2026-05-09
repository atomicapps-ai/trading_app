"""scripts/optimize_dl_per_symbol.py — per-symbol parameter sweep for DL.

Wraps the existing DL detector + replay infrastructure so we can vary the
core DL thresholds (body/press/vol/vix/cat-stop) per symbol and record every
combo's performance into `data/optimization_results.db`.

Why this is separate from optimize_strategies.py: DL has dependencies the
external detectors don't:
  - 30m bars filtered to RTH-only (slot-volume calculation depends on it)
  - prior-session VIX close map (regime gate)
  - daily indicator frame (VIX/ADX/RSI gates)
  - 15:00 ET / catastrophic-stop simulated exit

Reuses scripts/replay_dl.py primitives where possible.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import itertools
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

try:
    sys.stdout.reconfigure(encoding="utf-8")                            # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import pandas as pd

from agents.detectors.double_lock_filtered import detect_double_lock_filtered
from scripts.replay_dl import (
    _full_frames, _simulate_exit, _trading_days, _vix_prev_close_map,
    _as_of_for, _load_cat_stop_pct,
)
from services import optimization_db
from services.indicator_service import add_indicators


BELLWETHER_16 = ["AAPL", "AMD", "AMZN", "BA", "COST", "GS", "HD", "INTC",
                 "IWM", "META", "MSFT", "NVDA", "ORCL", "SPY", "TSLA", "XLF"]


# Coarse grid — 4×4×3×3 = 144 combos per symbol. With 16 symbols = 2,304
# combos; each combo requires walking ~1090 trading days × 16 lookups.
# DL is slow because of the day-by-day simulation; budget ~30min total.
PARAMETER_SPEC = {
    "body_pct": {
        "default": 0.5, "type": float,
        "sweep": [0.4, 0.5, 0.6, 0.7],
        "reasoning": "C1+C2 candle body strength. Higher = stricter conviction; "
                     "fewer signals but each is stronger. Per-symbol because "
                     "TSLA's 'wide body' is bigger than KO's.",
    },
    "press_hi": {
        "default": 0.6, "type": float,
        "sweep": [0.55, 0.6, 0.65, 0.7],
        "reasoning": "Bullish close-in-range threshold (HPRS). Higher = "
                     "tighter requirement that close pinned the high.",
    },
    "vol_mult": {
        "default": 1.3, "type": float,
        "sweep": [1.0, 1.3, 1.5, 2.0],
        "reasoning": "C1 volume vs slot 20-day median. Higher = stronger "
                     "institutional engagement requirement.",
    },
    "vix_min": {
        "default": 20.0, "type": float,
        "sweep": [15.0, 20.0, 25.0],
        "reasoning": "Regime gate — only fire on days where prior-session "
                     "VIX closed above this. 25 = high-vol-only (rare); "
                     "15 = always-on; 20 = current default.",
    },
}


def _hash_combo(combo: dict) -> str:
    j = json.dumps(combo, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(j.encode()).hexdigest()[:12]


def _make_grid() -> list[dict]:
    names = list(PARAMETER_SPEC.keys())
    values = [PARAMETER_SPEC[n]["sweep"] for n in names]
    return [{n: v for n, v in zip(names, c)} for c in itertools.product(*values)]


def _summarize(trades: list[dict], capital: float = 10_000.0) -> dict:
    n = len(trades)
    if n == 0:
        return dict(
            n_trades=0, wins=0, losses=0, wr_pct=0.0, profit_factor=0.0,
            net_pnl_usd=0.0, gross_profit_usd=0.0, gross_loss_usd=0.0,
            avg_r_multiple=0.0, max_drawdown_pct=0.0, score=0.0,
        )
    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    gp = sum(t["pnl_pct"] for t in wins) / 100.0 * capital
    gl = -sum(t["pnl_pct"] for t in losses) / 100.0 * capital
    pf = gp / gl if gl > 0 else (5.0 if gp > 0 else 0.0)
    wr = len(wins) / n * 100.0
    avg_r = sum(t.get("pnl_r", 0.0) for t in trades) / n

    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        eq += t["pnl_pct"] / 100.0 * capital
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
    max_dd_pct = (max_dd / capital) * 100.0

    import math
    pf_clamped = min(pf, 5.0)
    score = max(0.0, pf_clamped - 1.0) * math.log(max(n, 1)) * (wr / 100.0)
    return dict(
        n_trades=n, wins=len(wins), losses=len(losses),
        wr_pct=round(wr, 2), profit_factor=round(pf, 3),
        net_pnl_usd=round(gp - gl, 2),
        gross_profit_usd=round(gp, 2), gross_loss_usd=round(gl, 2),
        avg_r_multiple=round(avg_r, 3),
        max_drawdown_pct=round(max_dd_pct, 2),
        score=round(score, 4),
    )


async def replay_one_symbol_combo(
    sym: str,
    bars30: pd.DataFrame,
    daily_ind: pd.DataFrame,
    vix_by_date: dict,
    days: list[date],
    combo: dict,
    cat_stop_pct: float,
) -> list[dict]:
    """Replay DL on one symbol over the date range with this param combo.

    Returns list of trade dicts ready for `_summarize`.
    """
    config = {
        "thresholds": {
            "body_pct": combo["body_pct"],
            "press_hi": combo["press_hi"],
            "press_lo": 1.0 - combo["press_hi"],   # mirror around 0.5
            "vol_mult": combo["vol_mult"],
            "vix_min": combo["vix_min"],
            "adx_max": 35.0,
            "rsi_long_lo": 40.0,
            "rsi_long_hi": 65.0,
            "rsi_short_lo": 20.0,
            "rsi_short_hi": 40.0,
            "cat_stop_pct": cat_stop_pct,
        }
    }
    trades: list[dict] = []
    for d in days:
        as_of = _as_of_for(d)
        vix_prev = vix_by_date.get(d)
        if vix_prev is None:
            continue
        try:
            pat = detect_double_lock_filtered(
                bars_30m=bars30, daily=daily_ind, vix_prev_close=vix_prev,
                config=config, as_of_ts=as_of, ignore_regime=False,
            )
        except Exception:
            continue
        if pat is None:
            continue
        entry = float(pat.entry_price)
        stop = float(pat.stop_price)
        exit_pair = await _simulate_exit(sym, d, entry, stop, pat.direction)
        if exit_pair is None:
            continue
        exit_px, reason = exit_pair
        raw_pct = (exit_px - entry) / entry * 100.0
        pnl_pct = raw_pct if pat.direction == "long" else -raw_pct
        pnl_r = ((exit_px - entry) / max(abs(entry - stop), 1e-9)
                 * (1 if pat.direction == "long" else -1))
        trades.append({
            "date": str(d), "direction": pat.direction,
            "entry": entry, "exit": exit_px, "stop": stop,
            "pnl_pct": pnl_pct, "pnl_r": pnl_r, "reason": reason,
        })
    return trades


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--since", default="2022-01-03")
    ap.add_argument("--until", default="2026-05-08")
    ap.add_argument("--no-resume", action="store_true")
    args = ap.parse_args()

    optimization_db.ensure_schema()

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols else BELLWETHER_16
    )
    since = date.fromisoformat(args.since)
    until = date.fromisoformat(args.until)
    days = _trading_days(since, until)
    cat_stop_pct = _load_cat_stop_pct("double_lock")
    grid = _make_grid()
    grid_hashes = {_hash_combo(c): c for c in grid}

    print(f"DL OPTIMIZER START — {len(symbols)} symbols × {len(grid)} combos = "
          f"{len(symbols) * len(grid)} runs")
    print(f"  window: {since} -> {until} ({len(days)} trading days)")
    print(f"  cat_stop_pct: {cat_stop_pct}")
    print(f"  DB: {optimization_db.DB_PATH}")
    print("-" * 78)

    # Prefetch data once for ALL symbols (saves ~16x VIX fetches)
    print(f"Pre-fetching 30m + daily + VIX...")
    sym_data: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for sym in symbols:
        b, d = await _full_frames(sym, force_refresh=False)
        if b is None or d is None or b.empty or d.empty:
            print(f"  ! {sym}: data unavailable, skipping")
            continue
        sym_data[sym] = (b, add_indicators(d))
    vix_by_date = await _vix_prev_close_map(force_refresh=False)
    print(f"  ready: {len(sym_data)} symbols + {len(vix_by_date)} VIX rows\n")

    t0_total = time.time()
    total_run = 0
    for sym in symbols:
        if sym not in sym_data:
            continue
        bars30, daily_ind = sym_data[sym]

        done = (
            optimization_db.get_done_combos("double_lock", sym)
            if not args.no_resume else set()
        )
        todo_hashes = [h for h in grid_hashes if h not in done]
        if not todo_hashes:
            print(f"  [{sym}] all {len(grid)} combos already done; skipping")
            continue
        print(f"  [{sym}] {len(todo_hashes)}/{len(grid)} combos to run")

        for h in todo_hashes:
            combo = grid_hashes[h]
            t0 = time.time()
            try:
                trades = await replay_one_symbol_combo(
                    sym, bars30, daily_ind, vix_by_date, days, combo, cat_stop_pct,
                )
            except Exception as exc:                                   # noqa: BLE001
                optimization_db.log_analysis(
                    "warn", f"pair:double_lock:{sym}",
                    f"combo {h} failed: {type(exc).__name__}: {exc}",
                )
                continue
            dur = time.time() - t0
            summary = _summarize(trades)
            window_start = days[0].isoformat() if days else ""
            window_end = days[-1].isoformat() if days else ""

            record = optimization_db.RunRecord(
                run_id=str(uuid4()),
                strategy_slug="double_lock",
                symbol=sym,
                bars_interval="30m",
                params_json=json.dumps(combo, sort_keys=True),
                n_trades=summary["n_trades"], wins=summary["wins"],
                losses=summary["losses"], wr_pct=summary["wr_pct"],
                profit_factor=summary["profit_factor"],
                net_pnl_usd=summary["net_pnl_usd"],
                gross_profit_usd=summary["gross_profit_usd"],
                gross_loss_usd=summary["gross_loss_usd"],
                avg_r_multiple=summary["avg_r_multiple"],
                max_drawdown_pct=summary["max_drawdown_pct"],
                score=summary["score"],
                window_start=window_start, window_end=window_end,
                ran_at=datetime.now(timezone.utc).isoformat(),
                duration_seconds=round(dur, 3),
                notes=None,
            )
            reasoning_rows = []
            for pname, pval in combo.items():
                spec = PARAMETER_SPEC[pname]
                is_default = (pval == spec["default"])
                reasoning_rows.append({
                    "param_name": pname, "param_value": pval,
                    "reasoning": spec["reasoning"],
                    "source": "author_default" if is_default else "optimizer",
                })
            optimization_db.insert_run(record, reasoning_rows)
            done.add(h)
            total_run += 1

        optimization_db.upsert_checkpoint("double_lock", sym, done, len(grid))

        # Pick the winner for this symbol
        top = optimization_db.fetch_top_n("double_lock", sym, n=3)
        eligible = [r for r in top if r["n_trades"] >= 30 and r["profit_factor"] > 1.0]
        if eligible:
            best = eligible[0]
            runner_up = eligible[1] if len(eligible) > 1 else None
            rationale = (
                f"Picked {best['params_json']} — score {best['score']:.3f} "
                f"(PF {best['profit_factor']:.2f}, WR {best['wr_pct']:.1f}%, "
                f"n={best['n_trades']})"
            )
            if runner_up:
                rationale += (f". Runner-up: score {runner_up['score']:.3f} "
                              f"(PF {runner_up['profit_factor']:.2f}, "
                              f"n={runner_up['n_trades']}).")
            optimization_db.upsert_best_per_symbol(
                "double_lock", sym, best["run_id"], rationale,
            )
        else:
            optimization_db.log_analysis(
                "finding", f"pair:double_lock:{sym}",
                f"No eligible combo (n≥30, PF>1) across {len(grid)} sweeps for {sym}.",
            )

    print(f"\nDL OPTIMIZER DONE — ran {total_run} new combos in "
          f"{time.time() - t0_total:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
