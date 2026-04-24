"""Run the vcp_absorption detector across cached daily bars.

Walks every bar in the cached series (with ``as_of_ts`` set to that
bar) and asks the detector if it fires. Prints each detection with its
full diagnostic dict so we can see exactly why it fired (or didn't).

Usage:
    python -m scripts.smoke_vcp_absorption SMCI
    python -m scripts.smoke_vcp_absorption SMCI --from 2023-08-01 --to 2024-02-01
    python -m scripts.smoke_vcp_absorption SMCI --check-date 2024-01-17
    python -m scripts.smoke_vcp_absorption SMCI CROX AVGO
    python -m scripts.smoke_vcp_absorption SMCI --csv detections.csv

With ``--check-date`` the script stops at that specific bar, runs the
detector once, and prints full pass/fail reasoning for every gate —
the programmatic equivalent of using TradingView Replay.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
from pathlib import Path

import pandas as pd

# Allow running from project root as `python -m scripts.smoke_vcp_absorption`
from agents.detectors.vcp_absorption import (
    DEFAULTS,
    PATTERN_NAME,
    detect_vcp_absorption,
)
from services.data_service import get_bars
from services.indicator_service import add_indicators

logging.basicConfig(level=logging.WARNING, format="%(message)s")
log = logging.getLogger("smoke_vcp_absorption")


async def _load(symbol: str) -> pd.DataFrame:
    df = await get_bars(symbol, "1d", min_bars=100)
    return add_indicators(df)


def _format_row(ts: pd.Timestamp, result) -> dict:
    diag = {}
    for ev in result.evidence_items:
        if ev.get("type") == "diagnostic":
            diag = ev.get("ref", {})
            break
    return {
        "date":            ts.strftime("%Y-%m-%d"),
        "pqs":             result.pqs_total,
        "entry":           result.entry_price,
        "stop":            result.stop_price,
        "tp1":             result.tp1_price,
        "tp2":             result.tp2_price,
        "resistance":      diag.get("resistance"),
        "touches":         diag.get("touch_count"),
        "contractions":    diag.get("contractions"),
        "first_depth_pct": diag.get("first_depth_pct"),
        "final_depth_pct": diag.get("final_depth_pct"),
        "compression":     diag.get("compression"),
        "vol_ratio":       diag.get("vol_ratio"),
        "base_bars":       diag.get("base_bars"),
    }


async def _scan(
    symbol: str,
    date_from: pd.Timestamp | None,
    date_to: pd.Timestamp | None,
) -> list[dict]:
    df = await _load(symbol)
    if date_from is None:
        date_from = df.index[100]  # need at least 100 bars of history before first check
    if date_to is None:
        date_to = df.index[-1]

    rows: list[dict] = []
    for ts in df.index:
        if ts < date_from or ts > date_to:
            continue
        result = detect_vcp_absorption(df, as_of_ts=ts)
        if result is not None:
            rows.append({"symbol": symbol, **_format_row(ts, result)})
    return rows


async def _diagnose_single_bar(
    symbol: str,
    check_date: pd.Timestamp,
) -> None:
    """Print a gate-by-gate walkthrough for a single as_of_ts."""
    df = await _load(symbol)
    # Find nearest bar (check_date might be a weekend)
    if check_date not in df.index:
        idx = df.index.searchsorted(check_date)
        if idx >= len(df.index):
            print(f"  [{symbol}] {check_date.date()} is after last cached bar")
            return
        check_date = df.index[idx]

    result = detect_vcp_absorption(df, as_of_ts=check_date)
    header = f"{symbol} — gate walkthrough @ {check_date.strftime('%Y-%m-%d')}"
    print("\n" + header)
    print("-" * len(header))

    if result is None:
        # Re-run with each gate individually disabled to see which one
        # is the blocker. We do this by progressively relaxing the
        # thresholds toward "any" and reporting what gate rejected.
        print("  DETECT: NO  —  running per-gate diagnostic…")
        _per_gate_diagnostic(df, check_date)
    else:
        print("  DETECT: YES")
        for k, v in _format_row(check_date, result).items():
            print(f"    {k:>18}: {v}")
        for ev in result.evidence_items:
            if ev.get("type") == "diagnostic":
                print("    diagnostic:")
                for k, v in ev["ref"].items():
                    print(f"      {k:>18}: {v}")


def _per_gate_diagnostic(df: pd.DataFrame, check_date: pd.Timestamp) -> None:
    """Identify ALL blocking gates at this bar.

    Strategy: fully relax every threshold first to confirm SOMETHING
    fires, then re-tighten one knob at a time to default. Each knob
    that flips the result from YES back to NO is an INDEPENDENT
    blocker under default settings. That gives a clean per-gate
    verdict — not just "the last relaxation that mattered."
    """
    cumulative_gates: list[tuple[str, dict]] = [
        ("context (use_strength + use_stage2 OFF)",
         {"use_strength": False, "use_stage2": False}),
        ("min_touches -> 2",        {"min_touches": 2}),
        ("min_t -> 2",              {"min_t": 2}),
        ("cluster_atr -> 2.5",      {"cluster_atr": 2.5}),
        ("compression_max -> 1.0",  {"compression_max": 1.0}),
        ("max_final_depth -> 0.25", {"max_final_depth": 0.25}),
        ("max_lowerlow_violations -> 99", {"max_lowerlow_violations": 99}),
        ("use_vol_dryup OFF",       {"use_vol_dryup": False}),
        ("min_base_bars -> 10",     {"min_base_bars": 10}),
        ("max_base_bars -> 500",    {"max_base_bars": 500}),
        ("max_drawdown_pct -> 0.99",{"max_drawdown_pct": 0.99}),
    ]
    cfg_patch: dict = {}
    fired_at: str | None = None
    for label, patch in cumulative_gates:
        cfg_patch.update(patch)
        cfg = {"pattern_thresholds": {PATTERN_NAME: cfg_patch}}
        r = detect_vcp_absorption(df, config=cfg, as_of_ts=check_date)
        status = "YES" if r else " NO"
        print(f"    {status}  cumulative+ relax: {label}")
        if r and fired_at is None:
            fired_at = label
            print("       -- result on first YES --")
            for k, v in _format_row(check_date, r).items():
                print(f"           {k:>18}: {v}")
    if fired_at is None:
        print("    [x] no detection even fully relaxed -- "
              "likely pivot extraction or history length issue")
        return

    # Per-gate independent verdict
    print("\n    Per-gate independent test (fully-relaxed config, "
          "then re-tighten one knob to its default):")
    full_relaxed = {}
    for _, patch in cumulative_gates:
        full_relaxed.update(patch)
    individual: list[tuple[str, str, object]] = [
        ("use_strength",         "use_strength",         True),
        ("min_touches",          "min_touches",          DEFAULTS["min_touches"]),
        ("min_t",                "min_t",                DEFAULTS["min_t"]),
        ("cluster_atr",          "cluster_atr",          DEFAULTS["cluster_atr"]),
        ("compression_max",      "compression_max",      DEFAULTS["compression_max"]),
        ("max_final_depth",      "max_final_depth",      DEFAULTS["max_final_depth"]),
        ("max_lowerlow_violations", "max_lowerlow_violations", DEFAULTS["max_lowerlow_violations"]),
        ("use_vol_dryup",        "use_vol_dryup",        True),
        ("min_base_bars",        "min_base_bars",        DEFAULTS["min_base_bars"]),
        ("max_base_bars",        "max_base_bars",        DEFAULTS["max_base_bars"]),
        ("max_drawdown_pct",     "max_drawdown_pct",     DEFAULTS["max_drawdown_pct"]),
    ]
    for label, key, default_value in individual:
        cfg_dict = dict(full_relaxed)
        cfg_dict[key] = default_value
        cfg = {"pattern_thresholds": {PATTERN_NAME: cfg_dict}}
        r = detect_vcp_absorption(df, config=cfg, as_of_ts=check_date)
        verdict = "PASS" if r else "BLOCK"
        print(f"      {verdict:<5}  re-tighten {label:<22} to default "
              f"({default_value})")
    return
    # (The lines below are unreachable; left intentionally empty.)
    print("    [x] still NO detection even with everything relaxed— "
          "check pivot extraction / history length")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _parse_date(s: str | None) -> pd.Timestamp | None:
    return None if s is None else pd.Timestamp(s, tz="UTC")


async def _main_async(args: argparse.Namespace) -> int:
    all_rows: list[dict] = []
    for symbol in args.symbols:
        if args.check_date:
            await _diagnose_single_bar(symbol, _parse_date(args.check_date))
            continue
        rows = await _scan(
            symbol,
            _parse_date(args.date_from),
            _parse_date(args.date_to),
        )
        print(f"\n=== {symbol}: {len(rows)} detections ===")
        for r in rows:
            print(
                f"  {r['date']}  pqs={r['pqs']:3d}  entry=${r['entry']:<8.2f} "
                f"stop=${r['stop']:<8.2f}  touches={r['touches']} "
                f"contractions={r['contractions']} "
                f"depths={r['first_depth_pct']}->{r['final_depth_pct']}% "
                f"compress={r['compression']} "
                f"vol={r['vol_ratio']} base={r['base_bars']}b"
            )
        all_rows.extend(rows)

    if args.csv and all_rows:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            w.writeheader()
            w.writerows(all_rows)
        print(f"\nwrote {len(all_rows)} rows to {args.csv}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("symbols", nargs="+")
    p.add_argument("--from", dest="date_from", default=None,
                   help="Start date (YYYY-MM-DD)")
    p.add_argument("--to", dest="date_to", default=None,
                   help="End date (YYYY-MM-DD)")
    p.add_argument("--check-date", default=None,
                   help="Single-bar diagnostic at this date")
    p.add_argument("--csv", default=None, help="Write detections to CSV")
    args = p.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
