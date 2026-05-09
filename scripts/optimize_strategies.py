"""scripts/optimize_strategies.py — per-symbol parameter sweep optimizer.

For each (strategy, symbol) pair, walk the strategy's PARAMETER_SPEC sweep
grids, run the detector + trade simulator over the 4-yr window, score each
combo, and store every result + reasoning in `data/optimization_results.db`.

Resumable: on restart, skips combos already recorded for a (strategy, symbol).
Long-running: ~4-8 hrs per full run depending on grid size. Run overnight.

Usage:
    python scripts/optimize_strategies.py                       # all strategies, all bellwether-16
    python scripts/optimize_strategies.py --strategy supertrend_kivanc
    python scripts/optimize_strategies.py --symbols AAPL,MSFT
    python scripts/optimize_strategies.py --interval 30m
    python scripts/optimize_strategies.py --resume              # skip done combos (default)
    python scripts/optimize_strategies.py --no-resume           # rerun everything
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import itertools
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    sys.stdout.reconfigure(encoding="utf-8")                            # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from agents.detectors.external._base import simulate_trades, summarize_trades
from services import optimization_db


BELLWETHER_16 = ["AAPL", "AMD", "AMZN", "BA", "COST", "GS", "HD", "INTC",
                 "IWM", "META", "MSFT", "NVDA", "ORCL", "SPY", "TSLA", "XLF"]

EXTERNAL_DETECTORS = [
    "agents.detectors.external.bollinger_rsi_chartart",
    "agents.detectors.external.macd_sma200_chartart",
    "agents.detectors.external.pmax_explorer",
    "agents.detectors.external.supertrend_kivanc",
]


# --------------------------------------------------------------------------- #
# Grid generation
# --------------------------------------------------------------------------- #


def make_grid(param_spec: dict) -> list[dict]:
    """Cartesian product of each param's `sweep` list."""
    names = list(param_spec.keys())
    values = [param_spec[n]["sweep"] for n in names]
    out: list[dict] = []
    for combo in itertools.product(*values):
        out.append({n: v for n, v in zip(names, combo)})
    return out


def hash_combo(combo: dict) -> str:
    """Stable hash of a param combo, for checkpointing."""
    j = json.dumps(combo, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(j.encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# Bar loading
# --------------------------------------------------------------------------- #


def load_bars(symbol: str, interval: str) -> pd.DataFrame:
    p = ROOT / "data" / "historical" / f"{symbol}_{interval}.csv"
    if not p.exists():
        raise FileNotFoundError(p)
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    df.columns = [c.strip().lower() for c in df.columns]
    if "adj_close" in df.columns and "close" in df.columns:
        df["close"] = df["adj_close"]
    cols = ["open", "high", "low", "close", "volume"]
    df = df[[c for c in cols if c in df.columns]].dropna()
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


# --------------------------------------------------------------------------- #
# Per-pair sweep
# --------------------------------------------------------------------------- #


def reason_for_combo(combo: dict, param_spec: dict) -> list[dict]:
    """Build per-param reasoning rows for the DB.

    For each param in this combo, record:
      - the value chosen (this combo's value)
      - whether it equals the author default ('author_default') or not ('optimizer')
      - the spec's reasoning text describing why that range was chosen
    """
    rows = []
    for name, value in combo.items():
        spec = param_spec[name]
        is_default = (value == spec["default"])
        rows.append({
            "param_name": name,
            "param_value": value,
            "reasoning": spec["reasoning"],
            "source": "author_default" if is_default else "optimizer",
        })
    return rows


def sweep_one_pair(
    detector_module,
    symbol: str,
    bars: pd.DataFrame,
    *,
    resume: bool,
    interval: str,
) -> int:
    """Run the full grid for (strategy, symbol). Returns count of combos run."""
    slug = detector_module.META["slug"]
    spec = detector_module.PARAMETER_SPEC
    grid = make_grid(spec)
    grid_hashes = {hash_combo(c): c for c in grid}

    done = optimization_db.get_done_combos(slug, symbol) if resume else set()
    todo_hashes = [h for h in grid_hashes if h not in done]
    if not todo_hashes:
        return 0

    window_start = bars.index[0].strftime("%Y-%m-%d")
    window_end = bars.index[-1].strftime("%Y-%m-%d")
    print(f"  [{slug}/{symbol}] {len(todo_hashes)} combos to run "
          f"({len(done)}/{len(grid)} already done)")

    for h in todo_hashes:
        combo = grid_hashes[h]
        t0 = time.time()
        try:
            sigs = detector_module.detect(bars, combo)
            trades = simulate_trades(bars, sigs)
            summary = summarize_trades(trades)
        except Exception as exc:                                       # noqa: BLE001
            optimization_db.log_analysis(
                "warn", f"pair:{slug}:{symbol}",
                f"combo {h} failed: {type(exc).__name__}: {exc}",
            )
            continue
        dur = time.time() - t0

        record = optimization_db.RunRecord(
            run_id=str(uuid4()),
            strategy_slug=slug,
            symbol=symbol,
            bars_interval=interval,
            params_json=json.dumps(combo, sort_keys=True),
            n_trades=summary["n_trades"],
            wins=summary["wins"],
            losses=summary["losses"],
            wr_pct=summary["wr_pct"],
            profit_factor=summary["profit_factor"],
            net_pnl_usd=summary["net_pnl_usd"],
            gross_profit_usd=summary["gross_profit_usd"],
            gross_loss_usd=summary["gross_loss_usd"],
            avg_r_multiple=summary["avg_r_multiple"],
            max_drawdown_pct=summary["max_drawdown_pct"],
            score=summary["score"],
            window_start=window_start,
            window_end=window_end,
            ran_at=datetime.now(timezone.utc).isoformat(),
            duration_seconds=round(dur, 3),
            notes=None,
        )
        optimization_db.insert_run(record, reason_for_combo(combo, spec))
        done.add(h)

    optimization_db.upsert_checkpoint(slug, symbol, done, len(grid))

    # Rank top-1 and write to best_per_symbol with rationale text
    top = optimization_db.fetch_top_n(slug, symbol, n=3)
    eligible = [r for r in top if r["n_trades"] >= 30 and r["profit_factor"] > 1.0]
    if eligible:
        best = eligible[0]
        runner_up = eligible[1] if len(eligible) > 1 else None
        rationale = (
            f"Picked params {best['params_json']} — "
            f"score {best['score']:.3f} (PF {best['profit_factor']:.2f}, "
            f"WR {best['wr_pct']:.1f}%, n={best['n_trades']})"
        )
        if runner_up:
            rationale += (
                f". Runner-up: score {runner_up['score']:.3f} "
                f"(PF {runner_up['profit_factor']:.2f}, n={runner_up['n_trades']})."
            )
        else:
            rationale += ". No other eligible combo (PF>1, n≥30)."
        optimization_db.upsert_best_per_symbol(slug, symbol, best["run_id"], rationale)
    else:
        optimization_db.log_analysis(
            "finding", f"pair:{slug}:{symbol}",
            f"No eligible combo (n≥30 AND PF>1) across {len(grid)} sweeps. "
            f"Strategy may not work on this symbol or grid is too narrow.",
        )

    return len(todo_hashes)


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default=None,
                    help="single strategy slug to run (default: all)")
    ap.add_argument("--symbols", default=None,
                    help="comma-separated symbols (default: bellwether-16)")
    ap.add_argument("--interval", default="1d", choices=["1d", "30m"],
                    help="bar interval to use")
    ap.add_argument("--no-resume", action="store_true",
                    help="rerun everything, ignoring checkpoints")
    args = ap.parse_args()

    optimization_db.ensure_schema()

    selected_modules: list[Any] = []
    for mod_path in EXTERNAL_DETECTORS:
        mod = importlib.import_module(mod_path)
        if args.strategy and mod.META["slug"] != args.strategy:
            continue
        selected_modules.append(mod)
    if not selected_modules:
        print(f"no strategy matched --strategy={args.strategy!r}")
        return 1

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols else BELLWETHER_16
    )

    total_grid = sum(len(make_grid(m.PARAMETER_SPEC)) for m in selected_modules) * len(symbols)
    print(f"OPTIMIZER START — {len(selected_modules)} strategies × "
          f"{len(symbols)} symbols × interval={args.interval}")
    print(f"  total combos planned: {total_grid}")
    print(f"  resume: {not args.no_resume}")
    print(f"  DB: {optimization_db.DB_PATH}")
    print("-" * 78)

    t_start = time.time()
    total_run = 0
    for mod in selected_modules:
        slug = mod.META["slug"]
        natural = mod.META.get("natural_interval", "1d")
        if natural != args.interval:
            print(f"\nNOTE: {slug} natural interval is {natural} but --interval={args.interval}; "
                  f"running anyway.")
        for sym in symbols:
            try:
                bars = load_bars(sym, args.interval)
            except FileNotFoundError:
                print(f"  [{slug}/{sym}] missing bars; skipping")
                optimization_db.log_analysis(
                    "warn", f"pair:{slug}:{sym}",
                    f"missing data/historical/{sym}_{args.interval}.csv — skipped",
                )
                continue
            n = sweep_one_pair(mod, sym, bars,
                               resume=not args.no_resume,
                               interval=args.interval)
            total_run += n

    elapsed = time.time() - t_start
    print(f"\nOPTIMIZER DONE — ran {total_run} new combos in {elapsed:.1f}s")
    print(f"  best_per_symbol rows: query via fetch_best_per_symbol_table()")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
