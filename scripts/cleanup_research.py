"""cleanup_research — remove dead research/experiment one-off scripts.

These are leftover CLI scripts from the Kronos, pivot, opening-candle, random-search,
and DL-optimization research eras. None are imported by the running app (verified:
the app only imports replay_dl, replay_swing, and kronos_poc — all KEPT). Pipeline
scripts, data utilities, smoke tests, and app-imported modules are all kept.

Preview by default; --yes to delete. Git-tracked → reversible with `git checkout -- scripts`.

    python scripts/cleanup_research.py          # preview
    python scripts/cleanup_research.py --yes     # apply
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

# Dead research one-offs to remove (NOT imported by any router/service/agent).
REMOVE = [
    # Kronos research CLIs (kronos_poc KEPT — imported by services/kronos_pipeline)
    "kronos_backtest.py", "kronos_diag.py", "kronos_pnl_sim.py", "kronos_queue.py",
    "kronos_scan.py", "build_kronos_universe.py", "reactivate_kronos.py",
    # Pivot research
    "pivot_backtest.py", "pivot_check.py", "pivot_finder.py",
    # Opening-candle / first-hour research
    "test_opening_candle_theory.py", "scan_opening_patterns.py", "find_explosive_first_hour.py",
    "measure_setup_structure.py", "label_breakouts.py", "dedup_breakouts.py",
    "distribution_analysis.py",
    # Strategy-2 backtest experiments
    "backtest_strategy2_dl.py", "backtest_strategy2_indicators.py",
    "backtest_strategy2_round2.py", "backtest_strategy2_round3.py",
    # DL optimization research
    "optimize_dl_per_symbol.py", "cross_validate_dl.py", "compare_winner_vs_random.py",
    "optimize_strategies.py",
    # Random-search / archetype research
    "random_search.py", "report_random_search.py", "report_best_per_symbol.py",
    "vector_analyze.py", "synthesize_optimization.py", "inspect_top_archetype.py",
    "strategy_lab.py",
    # State-memory research
    "build_state_memory.py", "query_state_memory.py",
    # Superseded replay experiments (replay_dl + replay_swing KEPT)
    "replay_strategies.py", "replay_strategies_full.py", "replay_active_screener.py",
    # Misc one-offs
    "create_high_atr_screener.py", "diagnose_finviz_filter.py", "diagnose_mag7.py",
    "demo_bracket_orders.py", "validate_empirical.py", "test_trailing_stops.py",
    "bulk_fetch_bellwether_30m.py",
]

# Kept on purpose (for the message): pipeline (strategy_suite/filters/harden, replay_swing,
# video_ingest, populate_universe, cleanup_app, cleanup_research), app-imported (replay_dl,
# kronos_poc), data utils (download_history, refresh_universe, build_core_universe_100,
# bulk_fetch_screener, fetch_*), and all smoke_*.py tests.


def main() -> None:
    do = "--yes" in sys.argv
    verb = "DELETING" if do else "would delete"
    removed = missing = 0
    print(f"== Dead research scripts ({verb}) ==")
    for name in REMOVE:
        p = SCRIPTS / name
        if not p.exists():
            print(f"  (missing) {name}")
            missing += 1
            continue
        print(f"  {verb} {name}")
        if do:
            p.unlink()
            removed += 1
    total = len([n for n in REMOVE if (SCRIPTS / n).exists() or not do])
    if do:
        print(f"\nRemoved {removed} scripts ({missing} already gone). "
              f"Kept pipeline, app-imported, data utils, and smoke tests.")
    else:
        print(f"\n{len(REMOVE)-missing} script(s) would be removed. "
              f"Re-run with --yes to apply. (Edit the REMOVE list to veto any.)")


if __name__ == "__main__":
    main()
