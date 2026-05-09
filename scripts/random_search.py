"""scripts/random_search.py — sample meta-strategy configs at random,
score each on each bellwether-16 symbol, persist every trial.

Designed to run for hours/days accumulating data. Resumable; never
deduplicates trials (each random sample is its own row, even if the
config happens to be identical to a prior one — they're cheap).

Usage:
    python scripts/random_search.py --trials-per-symbol 1000
    python scripts/random_search.py --trials-per-symbol 5000 --symbols AAPL,SPY
    python scripts/random_search.py --forever      # until you ctrl-C
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

try:
    sys.stdout.reconfigure(encoding="utf-8")                            # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from agents.detectors.external import meta_strategy
from agents.detectors.external._base import simulate_trades, summarize_trades
from services import optimization_db


BELLWETHER_16 = ["AAPL", "AMD", "AMZN", "BA", "COST", "GS", "HD", "INTC",
                 "IWM", "META", "MSFT", "NVDA", "ORCL", "SPY", "TSLA", "XLF"]

# Hand-mapped symbol class for feature vectors
SYMBOL_CLASS = {
    "AAPL": "tech", "AMD": "tech", "AMZN": "tech", "META": "tech",
    "MSFT": "tech", "NVDA": "tech", "ORCL": "tech", "TSLA": "tech",
    "INTC": "tech", "GS": "financial", "XLF": "financial",
    "BA": "industrial", "COST": "consumer", "HD": "consumer",
    "IWM": "index", "SPY": "index",
}


# --------------------------------------------------------------------------- #
# Config sampling
# --------------------------------------------------------------------------- #


ENTRY_PRIMITIVES = ["atr_band", "bb_extreme", "rsi_extreme",
                    "macd_zero_cross", "n_day_breakout"]
REGIME_FILTER_OPTIONS = ["long_ma_filter", "adx_filter", "vol_pct_filter"]
STOP_TYPES = ["atr_mult", "opposite_band", "fixed_pct"]
TP_TYPES = ["r_multiple_single", "mean_revert", "time_only"]


def sample_config(rng: random.Random) -> dict:
    """Sample one random meta-strategy config from the design space."""
    entry = rng.choice(ENTRY_PRIMITIVES)
    n_regime = rng.choice([0, 0, 1, 1, 1, 2, 2, 3])  # bias toward 1-2 filters
    regime_filters = rng.sample(REGIME_FILTER_OPTIONS, n_regime)
    use_vol = rng.random() < 0.4

    cfg = {
        "entry_primitive": entry,
        "regime_filters": regime_filters,
        "use_volume_filter": use_vol,
        "stop_type": rng.choice(STOP_TYPES),
        "tp_type": rng.choice(TP_TYPES),
        # all primitive-specific params (only the chosen entry's are used,
        # but sampling them all lets us see variance for unused ones)
        "atr_period": rng.choice([7, 10, 14, 21]),
        "atr_mult": round(rng.uniform(1.5, 5.0), 2),
        "ma_length": rng.choice([8, 10, 14, 21, 50]),
        "ma_type": rng.choice(["SMA", "EMA", "WMA"]),
        "bb_length": rng.choice([10, 20, 50, 100, 200]),
        "bb_mult": round(rng.uniform(1.2, 3.0), 2),
        "rsi_length": rng.choice([4, 6, 8, 14, 20]),
        "rsi_lo": rng.choice([20, 30, 40, 50]),
        "rsi_hi": rng.choice([50, 60, 70, 80]),
        "macd_fast": rng.choice([8, 12, 21]),
        "macd_slow": rng.choice([21, 26, 34, 50]),
        "macd_signal": rng.choice([6, 9, 14]),
        "breakout_length": rng.choice([10, 20, 50, 100]),
        # regime params
        "regime_ma_length": rng.choice([50, 100, 150, 200, 300]),
        "adx_min": rng.choice([0, 15, 20, 25]),
        "adx_max": rng.choice([25, 35, 50, 100]),
        "vol_pct_min": round(rng.uniform(0.0, 0.4), 2),
        "vol_pct_max": round(rng.uniform(0.6, 1.0), 2),
        # volume
        "vol_lookback": rng.choice([10, 20, 50]),
        "vol_mult": round(rng.uniform(1.0, 2.5), 2),
        # stop / tp
        "stop_atr_mult": round(rng.uniform(1.0, 4.0), 2),
        "stop_pct": round(rng.uniform(0.01, 0.08), 3),
        "tp_r_multiple": round(rng.uniform(1.0, 5.0), 1),
        # exit overlay
        "time_stop_bars": rng.choice([20, 60, 100, 150, 250]),
        "long_only": rng.random() < 0.3,
    }
    return cfg


# --------------------------------------------------------------------------- #
# Bar loading + symbol feature vector
# --------------------------------------------------------------------------- #


def load_bars(symbol: str, interval: str = "1d") -> pd.DataFrame:
    p = ROOT / "data" / "historical" / f"{symbol}_{interval}.csv"
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    df.columns = [c.strip().lower() for c in df.columns]
    if "adj_close" in df.columns and "close" in df.columns:
        df["close"] = df["adj_close"]
    cols = ["open", "high", "low", "close", "volume"]
    df = df[[c for c in cols if c in df.columns]].dropna()
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


def compute_symbol_features(symbol: str, bars: pd.DataFrame) -> dict:
    """Pre-compute static feature vector — same for every trial on this symbol."""
    rets = bars["close"].pct_change()
    vol_avg = float(rets.std() * (252 ** 0.5))
    sma200 = bars["close"].rolling(200).mean()
    bull_pct = float((bars["close"] > sma200).mean())
    yoy_ret = float(bars["close"].iloc[-1] / bars["close"].iloc[0] - 1.0)
    avg_atr_pct = float((bars["high"] - bars["low"]).mean() / bars["close"].mean())
    return {
        "symbol_class": SYMBOL_CLASS.get(symbol, "other"),
        "annualized_vol_pct": round(vol_avg * 100, 2),
        "bull_regime_pct": round(bull_pct * 100, 2),
        "total_return_pct": round(yoy_ret * 100, 2),
        "avg_daily_range_pct": round(avg_atr_pct * 100, 3),
    }


# --------------------------------------------------------------------------- #
# IS / OOS scoring
# --------------------------------------------------------------------------- #


def split_window(bars: pd.DataFrame, oos_start: str = "2025-01-01"):
    cutoff = pd.Timestamp(oos_start, tz="UTC")
    return bars.loc[bars.index < cutoff], bars.loc[bars.index >= cutoff]


def score_window(bars: pd.DataFrame, cfg: dict) -> dict:
    sigs = meta_strategy.detect(bars, cfg)
    trades = simulate_trades(bars, sigs)
    return summarize_trades(trades)


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #


def _load_symbols_from_screener(name: str) -> list[str]:
    """Read tickers from a named screener via universe_service (sync wrapper)."""
    import asyncio as _a
    from services import universe_service
    preset = _a.run(universe_service.get_preset_db(name))
    if preset is None:
        raise ValueError(f"screener {name!r} not found")
    tickers = preset.get("tickers", []) or []
    return [s.strip().upper() for s in tickers if s.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials-per-symbol", type=int, default=500)
    ap.add_argument("--symbols", default=None,
                    help="comma-separated; overrides --screener")
    ap.add_argument("--screener", default=None,
                    help="load symbols from this named screener "
                         "(e.g. 'high_atr_liquid')")
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--forever", action="store_true",
                    help="loop until interrupted; ignore --trials-per-symbol cap")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--commit-every", type=int, default=50)
    args = ap.parse_args()

    optimization_db.ensure_schema()
    rng = random.Random(args.seed)

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    elif args.screener:
        symbols = _load_symbols_from_screener(args.screener)
        print(f"loaded {len(symbols)} symbols from screener {args.screener!r}")
    else:
        symbols = BELLWETHER_16

    # Pre-load bars + features once (avoid disk I/O in hot loop)
    sym_data: dict[str, dict] = {}
    for sym in symbols:
        try:
            bars = load_bars(sym, args.interval)
        except FileNotFoundError:
            print(f"  [skip] no bars for {sym}")
            continue
        is_bars, oos_bars = split_window(bars)
        sym_data[sym] = {
            "bars_full": bars,
            "bars_is": is_bars,
            "bars_oos": oos_bars,
            "features": compute_symbol_features(sym, bars),
            "window_start": bars.index[0].strftime("%Y-%m-%d"),
            "window_end": bars.index[-1].strftime("%Y-%m-%d"),
        }
    print(f"random_search: {len(sym_data)} symbols loaded; interval={args.interval}")
    print(f"  initial trial counts in DB:")
    for sym in sym_data:
        n = optimization_db.random_trial_count(sym)
        print(f"    {sym:5s}: {n:>6d}")

    target_per_sym = args.trials_per_symbol
    batch_buf: list[dict] = []
    total_run = 0
    t0 = time.time()

    try:
        while True:
            for sym, sd in sym_data.items():
                # If not in --forever mode, stop once each symbol has enough trials
                if not args.forever:
                    cur = optimization_db.random_trial_count(sym)
                    if cur >= target_per_sym:
                        continue

                cfg = sample_config(rng)
                t_start = time.time()

                full_summary = score_window(sd["bars_full"], cfg)
                is_summary = score_window(sd["bars_is"], cfg)
                oos_summary = score_window(sd["bars_oos"], cfg)
                gap = None
                if is_summary["score"] > 0.01:
                    gap = (is_summary["score"] - oos_summary["score"]) / is_summary["score"]

                trial = {
                    "trial_id": str(uuid4()),
                    "symbol": sym,
                    "bars_interval": args.interval,
                    "meta_config_json": json.dumps(cfg, sort_keys=True),
                    "entry_primitive": cfg["entry_primitive"],
                    "stop_type": cfg["stop_type"],
                    "tp_type": cfg["tp_type"],
                    "regime_filter_count": len(cfg["regime_filters"]),
                    "uses_volume_filter": int(cfg["use_volume_filter"]),
                    "n_trades": full_summary["n_trades"],
                    "wr_pct": full_summary["wr_pct"],
                    "profit_factor": full_summary["profit_factor"],
                    "net_pnl_usd": full_summary["net_pnl_usd"],
                    "avg_r_multiple": full_summary["avg_r_multiple"],
                    "max_drawdown_pct": full_summary["max_drawdown_pct"],
                    "score": full_summary["score"],
                    "is_score": is_summary["score"],
                    "oos_score": oos_summary["score"],
                    "is_oos_gap_pct": round(gap, 4) if gap is not None else None,
                    "feature_vector_json": json.dumps(sd["features"], sort_keys=True),
                    "ran_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": int((time.time() - t_start) * 1000),
                    "window_start": sd["window_start"],
                    "window_end": sd["window_end"],
                }
                batch_buf.append(trial)
                total_run += 1

                if len(batch_buf) >= args.commit_every:
                    optimization_db.insert_random_trials_batch(batch_buf)
                    batch_buf.clear()
                    rate = total_run / (time.time() - t0)
                    print(f"  +{total_run} trials  ({rate:.1f}/s)")

            # Exit condition (non-forever)
            if not args.forever:
                if all(
                    optimization_db.random_trial_count(s) >= target_per_sym
                    for s in sym_data
                ):
                    break
    except KeyboardInterrupt:
        print("\ninterrupted; flushing buffer...")

    if batch_buf:
        optimization_db.insert_random_trials_batch(batch_buf)
        batch_buf.clear()

    elapsed = time.time() - t0
    print(f"\nrandom_search done: ran {total_run} trials in {elapsed:.1f}s "
          f"({total_run / max(elapsed, 1):.1f}/s)")
    print(f"final trial counts:")
    for sym in sym_data:
        n = optimization_db.random_trial_count(sym)
        print(f"    {sym:5s}: {n:>6d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
