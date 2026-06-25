"""Kronos proof-of-concept — see real forecast output vs a Brownian baseline.

Build-order step 1 from strategies/KRONOS_UPGRADE_PROPOSAL.md. Fetches daily bars,
runs Kronos-small and the GBM baseline, defines a simple ATR-based entry/stop/TP
(2:1 R), and prints the probability metrics the Scan/Forecast UI would show — so you
can eyeball whether Kronos produces something non-random on names you know.

USAGE:
    # one-time setup
    git clone https://github.com/shiyu-coder/Kronos vendor/kronos
    pip install torch safetensors huggingface_hub einops yfinance

    # run (defaults: AAPL NVDA SPY, 10-day horizon, 30 paths)
    python -m scripts.kronos_poc
    python -m scripts.kronos_poc --symbols MSFT AVGO LLY --paths 50 --pred-len 10

First run downloads ~100MB of weights from Hugging Face. CPU is fine for the POC;
30 paths/symbol on daily bars takes well under a minute on most machines.

This is research scaffolding — it does NOT touch the broker, gates, or any live path.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Make the script runnable from ANY directory: put the project root
# (the folder containing services/, models/, vendor/) on sys.path.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

logger = logging.getLogger("kronos_poc")


def fetch_daily_bars(symbol: str, period: str = "2y") -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(symbol, period=period, interval="1d", auto_adjust=False, progress=False)
    if raw is None or raw.empty:
        raise ValueError(f"no data returned for {symbol}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.droplevel(1)
    raw = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    raw.index.name = "timestamps"
    return raw.dropna()


def atr(bars: pd.DataFrame, period: int = 14) -> float:
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return float(tr.tail(period).mean())


def run_symbol(symbol: str, pred_len: int, n_paths: int) -> None:
    from services import baseline_service, kronos_service

    bars = fetch_daily_bars(symbol)
    last_close = float(bars["close"].iloc[-1])
    a = atr(bars)

    t0 = time.time()
    k = kronos_service.forecast(
        symbol=symbol, interval="1d", bars=bars, pred_len=pred_len, n_paths=n_paths
    )
    g = baseline_service.gbm_forecast(
        symbol=symbol, interval="1d", bars=bars, pred_len=pred_len, n_paths=n_paths, seed=7
    )

    # Direction from Kronos, then a simple 2:1 ATR setup for both forecasters.
    direction = "long" if k.p_up >= 0.5 else "short"
    if direction == "long":
        entry, stop, tp = last_close, last_close - 1.5 * a, last_close + 3.0 * a
    else:
        entry, stop, tp = last_close, last_close + 1.5 * a, last_close - 3.0 * a

    kh = k.hit_probabilities(entry=entry, stop=stop, take_profit=tp, direction=direction)
    gh = g.hit_probabilities(entry=entry, stop=stop, take_profit=tp, direction=direction)

    logger.info("")
    logger.info("=== %s  (last close %.2f · ATR %.2f · %s setup) ===", symbol, last_close, a, direction.upper())
    logger.info("setup: entry %.2f  stop %.2f  TP %.2f  (2:1 R)", entry, stop, tp)
    logger.info("%-14s %12s %12s", "metric", "Kronos", "GBM base")
    logger.info("%-14s %11.0f%% %11.0f%%", "p_up (horizon)", k.p_up * 100, g.p_up * 100)
    logger.info("%-14s %11.1f%% %11.1f%%", "exp return", k.expected_return_pct, g.expected_return_pct)
    logger.info("%-14s %11.1f%% %11.1f%%", "path sigma", k.path_sigma_pct, g.path_sigma_pct)
    logger.info("%-14s %11.0f%% %11.0f%%", "P(profit)", kh.p_profit * 100, gh.p_profit * 100)
    logger.info("%-14s %12.2f %12.2f", "expected R", kh.expected_r, gh.expected_r)
    logger.info("(%.1fs · %d paths each)", time.time() - t0, n_paths)


def main() -> None:
    ap = argparse.ArgumentParser(description="Kronos vs Brownian baseline POC")
    ap.add_argument("--symbols", nargs="+", default=["AAPL", "NVDA", "SPY"])
    ap.add_argument("--pred-len", type=int, default=10)
    ap.add_argument("--paths", type=int, default=30)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")

    for sym in args.symbols:
        try:
            run_symbol(sym, args.pred_len, args.paths)
        except Exception as exc:  # noqa: BLE001 — POC: report and continue
            logger.error("%s failed: %s", sym, exc)

    logger.info("")
    logger.info("Reminder: a real edge means Kronos beats GBM on a chronological")
    logger.info("out-of-sample split after costs — not on a single day's snapshot.")


if __name__ == "__main__":
    main()
