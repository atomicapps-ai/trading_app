"""kronos_queue — run the Kronos scan and QUEUE survivors to /pending (Alpaca paper).

This is the daily paper-trading entrypoint. Unlike kronos_scan.py (which only prints),
this builds real TradePlans, runs them through compliance + risk, and writes the
survivors to the pending_approvals queue. You then open the app, review each one on
/pending, and click Approve — which places it on Alpaca paper via the executioner.
Nothing is auto-approved; every trade is human-approved.

PREREQUISITES:
  - The app must be configured for PAPER mode (settings.app.mode = "paper") with the
    Alpaca paper account active, and have been run at least once (creates the DB).
  - Run inside the project venv:  .venv\\Scripts\\activate

USAGE:
  # quick test (CPU is slow): 5 names
  python scripts/kronos_queue.py --limit 5 --paths 30

  # full core_universe_100 (slow on CPU — run pre-market / overnight)
  python scripts/kronos_queue.py

  # ad-hoc list
  python scripts/kronos_queue.py --symbols AAPL MSFT NVDA --paths 30

Then: start the app (python run.py dev), open /pending, review + approve.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("kronos_queue")


async def _run(args) -> None:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    from scripts.kronos_scan import load_universe
    from services import db_service, kronos_pipeline
    from services.settings_service import get_settings

    await db_service.ensure_tables()

    s = get_settings()
    if s.app.mode != "paper":
        logger.warning("App mode is '%s', not 'paper'. Plans will queue, but approval "
                       "will NOT place orders until you switch the app to paper mode.",
                       s.app.mode)

    symbols = args.symbols or load_universe(args.preset)
    if args.limit:
        symbols = symbols[: args.limit]
    device = None if args.device == "auto" else args.device

    logger.info("Queueing from %d symbols on %s (gate: P>=%.0f%% & R>=%.2f)\n",
                len(symbols), args.device, args.min_prob * 100, args.min_er)

    result = await kronos_pipeline.queue_candidates(
        symbols=symbols, pred_len=args.pred_len, n_paths=args.paths,
        device=device, min_prob=args.min_prob, min_er=args.min_er, settings=s,
    )

    logger.info("\n=== Queue summary ===")
    logger.info("equity used for sizing: $%s · mode: %s",
                f"{result['equity']:,.0f}", result["mode"])
    logger.info("QUEUED (awaiting your approval on /pending): %d", len(result["queued"]))
    for sym in result["queued"]:
        logger.info("   + %s", sym)
    logger.info("skipped (below gate): %d", len(result["skipped"]))
    if result["rejected"]:
        logger.info("rejected by gates/errors: %d", len(result["rejected"]))
        for sym, gate, reason in result["rejected"]:
            logger.info("   - %-6s [%s] %s", sym, gate, reason)
    logger.info("\nNext: start the app (python run.py dev), open /pending, review + Approve.")
    logger.info("Approving places the order on Alpaca paper. Nothing was auto-traded.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Queue Kronos candidates to /pending (paper)")
    ap.add_argument("--preset", default="core_universe_100")
    ap.add_argument("--symbols", nargs="+")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pred-len", type=int, default=10)
    ap.add_argument("--paths", type=int, default=30)
    ap.add_argument("--min-prob", type=float, default=0.60)
    ap.add_argument("--min-er", type=float, default=0.0)
    ap.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "cuda:0", "mps"])
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
