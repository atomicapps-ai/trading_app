"""Kronos basket diagnostic — is the model discriminating, or structurally biased?

The single-symbol POC showed SPY with p_up = 0% (every path down). That is either a
real bearish read or a model/normalization artifact. The only way to tell is to look at
a BASKET: if Kronos is bullish on some names and bearish on others, it's discriminating
(good). If p_up is ~0 (or ~1) on everything, that's a bias/bug to fix before we trust any
signal or invest in Stage 0.

Uses the batched forecast path (services.kronos_service.forecast → predict_batch), so
many paths per symbol is now cheap relative to the old per-path loop.

USAGE:
    python scripts/kronos_diag.py
    python scripts/kronos_diag.py --paths 100 --pred-len 10 \
        --symbols AAPL MSFT NVDA AMZN GOOGL META SPY XOM JPM LLY
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("kronos_diag")

DEFAULT_BASKET = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "SPY", "XOM", "JPM", "LLY"]


def main() -> None:
    ap = argparse.ArgumentParser(description="Kronos basket bias diagnostic")
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_BASKET)
    ap.add_argument("--pred-len", type=int, default=10)
    ap.add_argument("--paths", type=int, default=60)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from scripts.kronos_poc import fetch_daily_bars
    from services import kronos_service

    logger.info("%-7s %8s %10s %10s %7s", "symbol", "p_up", "exp_ret", "sigma", "secs")
    logger.info("-" * 46)
    rows = []
    for sym in args.symbols:
        try:
            t0 = time.time()
            bars = fetch_daily_bars(sym)
            f = kronos_service.forecast(
                symbol=sym, interval="1d", bars=bars,
                pred_len=args.pred_len, n_paths=args.paths,
            )
            dt = time.time() - t0
            rows.append(f.p_up)
            logger.info("%-7s %7.0f%% %9.1f%% %9.1f%% %7.0f",
                        sym, f.p_up * 100, f.expected_return_pct, f.path_sigma_pct, dt)
        except Exception as exc:  # noqa: BLE001
            logger.error("%-7s  failed: %s", sym, exc)

    if not rows:
        logger.info("\nno successful forecasts.")
        return

    lo, hi, avg = min(rows), max(rows), sum(rows) / len(rows)
    logger.info("-" * 46)
    logger.info("p_up  min %.0f%%  max %.0f%%  mean %.0f%%", lo * 100, hi * 100, avg * 100)
    logger.info("")
    if hi < 0.20 or lo > 0.80:
        logger.info("VERDICT: structurally biased — Kronos points the SAME way on")
        logger.info("nearly every name. Treat as a bug/normalization issue, not signal.")
        logger.info("Next: check input scaling, try Kronos-base, or finetune before Stage 0.")
    elif lo < 0.40 and hi > 0.60:
        logger.info("VERDICT: discriminating — bullish on some, bearish on others.")
        logger.info("Worth proceeding to Stage 0 (chronological OOS replay vs GBM, after costs).")
    else:
        logger.info("VERDICT: weakly discriminating — clustered near 50%.")
        logger.info("Plausibly low-signal; Stage 0 will quantify whether it beats GBM.")


if __name__ == "__main__":
    main()
