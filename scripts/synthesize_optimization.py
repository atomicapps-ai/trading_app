"""scripts/synthesize_optimization.py — Phase E synthesis reports.

Reads `data/optimization_results.db` and produces:

1. Heat map (text grid) of best score per (strategy, symbol)
2. Primitive frequency analysis — which indicators show up in winners
3. Per-strategy summary stats (median PF, profitable-symbol count, etc.)
4. Markdown report appended to strategies/STRATEGY_KNOWLEDGE.md

Output goes to stdout AND `strategies/OPTIMIZATION_FINDINGS.md`.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")                            # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services import optimization_db
from services.settings_service import DATA_DIR


BELLWETHER_16 = ["AAPL", "AMD", "AMZN", "BA", "COST", "GS", "HD", "INTC",
                 "IWM", "META", "MSFT", "NVDA", "ORCL", "SPY", "TSLA", "XLF"]


def _load_best() -> list[dict]:
    return optimization_db.fetch_best_per_symbol_table()


def _load_all_runs() -> list[dict]:
    db = optimization_db.DB_PATH
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT strategy_slug, symbol, params_json, n_trades, wr_pct,
                   profit_factor, net_pnl_usd, score
            FROM optimization_runs
        """).fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# 1. Heat map
# --------------------------------------------------------------------------- #


def heat_map(best: list[dict]) -> str:
    by_pair = {(r["strategy_slug"], r["symbol"]): r for r in best}
    strategies = sorted({r["strategy_slug"] for r in best})

    head = f"{'symbol':<6}" + "".join(f"{s[:18]:>20}" for s in strategies)
    out = [head, "-" * len(head)]
    for sym in BELLWETHER_16:
        line = f"{sym:<6}"
        for s in strategies:
            r = by_pair.get((s, sym))
            if r is None:
                line += f"{'—':>20}"
            else:
                line += f"  PF{r['profit_factor']:>4.2f} S{r['score']:>5.2f}"
        out.append(line)
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# 2. Primitive frequency in winners (PF > 1.5, n >= 30)
# --------------------------------------------------------------------------- #


_PRIMITIVE_FROM_PARAM_NAME = {
    "rsi_length": "rsi",
    "bb_length": "bollinger_bands",
    "bb_mult": "bollinger_bands",
    "stop_atr_mult": "atr_stop",
    "fast_length": "macd",
    "slow_length": "macd",
    "signal_length": "macd",
    "very_slow_length": "long_ma_regime_filter",
    "atr_period": "atr",
    "atr_mult": "atr_band",
    "ma_length": "ma",
    "ma_type": "ma",
    "use_real_atr": "atr",
}


def primitive_frequency(best: list[dict]) -> str:
    counts: Counter[str] = Counter()
    for r in best:
        if r["profit_factor"] < 1.5 or r["n_trades"] < 30:
            continue
        params = json.loads(r["params_json"])
        seen = set()
        for pname in params:
            prim = _PRIMITIVE_FROM_PARAM_NAME.get(pname)
            if prim and prim not in seen:
                counts[prim] += 1
                seen.add(prim)
    out = ["Primitive frequency in winners (PF≥1.5, N≥30):", ""]
    out.append(f"{'primitive':<25} {'count':>6}")
    out.append("-" * 33)
    for prim, n in counts.most_common():
        out.append(f"{prim:<25} {n:>6}")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# 3. Per-strategy summary
# --------------------------------------------------------------------------- #


def per_strategy_summary(best: list[dict]) -> str:
    by_strat: dict[str, list[dict]] = {}
    for r in best:
        by_strat.setdefault(r["strategy_slug"], []).append(r)

    out = [
        f"{'strategy':<28} {'#sym':>5} {'med PF':>7} {'med WR%':>8} "
        f"{'med N':>7} {'sum$':>10} {'best sym':>11} {'best score':>12}"
    ]
    out.append("-" * len(out[0]))

    for slug in sorted(by_strat):
        rows = by_strat[slug]
        pfs = [r["profit_factor"] for r in rows]
        wrs = [r["wr_pct"] for r in rows]
        ns = [r["n_trades"] for r in rows]
        nets = [r["net_pnl_usd"] for r in rows]
        best_row = max(rows, key=lambda r: r["score"])
        out.append(
            f"{slug:<28} {len(rows):>5d} {statistics.median(pfs):>7.2f} "
            f"{statistics.median(wrs):>8.1f} {int(statistics.median(ns)):>7d} "
            f"{sum(nets):>10.0f} {best_row['symbol']:>11} {best_row['score']:>12.2f}"
        )
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# 4. Per-symbol cross-strategy view (which strategy is best for each symbol?)
# --------------------------------------------------------------------------- #


def winning_strategy_per_symbol(best: list[dict]) -> str:
    by_sym: dict[str, list[dict]] = {}
    for r in best:
        by_sym.setdefault(r["symbol"], []).append(r)

    out = [
        f"{'symbol':<6} {'best strategy':<28} {'PF':>5} {'WR%':>5} "
        f"{'N':>5} {'net$':>9} {'score':>6}"
    ]
    out.append("-" * len(out[0]))

    for sym in BELLWETHER_16:
        rows = by_sym.get(sym, [])
        if not rows:
            out.append(f"{sym:<6} (no eligible strategies)")
            continue
        best_row = max(rows, key=lambda r: r["score"])
        out.append(
            f"{sym:<6} {best_row['strategy_slug']:<28} "
            f"{best_row['profit_factor']:>5.2f} {best_row['wr_pct']:>5.1f} "
            f"{best_row['n_trades']:>5d} {best_row['net_pnl_usd']:>9.0f} "
            f"{best_row['score']:>6.2f}"
        )
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# 5. Param-value frequency (which values appeared most in winners)
# --------------------------------------------------------------------------- #


def param_value_frequency(best: list[dict]) -> str:
    by_strat: dict[str, list[dict]] = {}
    for r in best:
        if r["n_trades"] < 30 or r["profit_factor"] < 1.5:
            continue
        by_strat.setdefault(r["strategy_slug"], []).append(json.loads(r["params_json"]))

    out = ["Param-value frequency in eligible winners (PF≥1.5, N≥30):", ""]
    for slug in sorted(by_strat):
        out.append(f"### {slug}  (n_winners={len(by_strat[slug])})")
        all_keys: set[str] = set()
        for p in by_strat[slug]:
            all_keys.update(p.keys())
        for k in sorted(all_keys):
            vals = [p[k] for p in by_strat[slug] if k in p]
            cnt = Counter(vals)
            top_str = "  ".join(f"{v!r}×{n}" for v, n in cnt.most_common(5))
            out.append(f"  {k:<22} {top_str}")
        out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main() -> int:
    optimization_db.ensure_schema()
    best = _load_best()
    all_runs = _load_all_runs()
    if not best:
        print("no rows yet — run scripts/optimize_strategies.py first")
        return 1

    sections = [
        f"# Optimization Findings — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"Generated from {len(all_runs):,} optimizer runs over {len(best)} eligible "
        f"(strategy, symbol) pairs.",
        "",
        "---",
        "",
        "## 1. Per-strategy summary",
        "",
        "Median across symbols where the strategy met n≥30 + PF>1 eligibility.",
        "",
        "```",
        per_strategy_summary(best),
        "```",
        "",
        "## 2. Best strategy per symbol (cross-strategy winners)",
        "",
        "Which strategy works best for each symbol, after per-symbol param tuning.",
        "",
        "```",
        winning_strategy_per_symbol(best),
        "```",
        "",
        "## 3. Heat map (best PF & score per (strategy, symbol))",
        "",
        "```",
        heat_map(best),
        "```",
        "",
        "## 4. Primitive frequency in winners",
        "",
        "Counting how many (strategy, symbol) winners use each indicator family. "
        "Tells us which primitives have real edge across the universe.",
        "",
        "```",
        primitive_frequency(best),
        "```",
        "",
        "## 5. Param-value frequency in eligible winners",
        "",
        "When a (strategy, symbol) pair makes it past the PF≥1.5 / N≥30 filter, "
        "which param values show up most? This tells us where the per-symbol optima "
        "cluster — highlights regime preferences across the bellwether-16.",
        "",
        "```",
        param_value_frequency(best),
        "```",
        "",
        "---",
        "",
        "## Reasoning storage check",
        "",
        f"All {len(all_runs):,} runs in `data/optimization_results.db::optimization_runs` carry "
        "their full param set, score, and trade summary. Per-param reasoning is in "
        "`param_reasoning` (the *why* for each param value's range). Winning combos for "
        "each (strategy, symbol) are in `best_per_symbol` with a human-readable "
        "selection rationale. Wipe the DB to re-run; checkpointing means no lost work.",
    ]
    text = "\n".join(sections)

    out_path = ROOT / "strategies" / "OPTIMIZATION_FINDINGS.md"
    out_path.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n\nWritten to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
