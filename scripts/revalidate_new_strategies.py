"""revalidate_new_strategies — confirm the 3 promoted diversifiers clear the bar through the
APP's own replay engine (real detectors + real config + gates), not just the standalone rig.

For each strategy: run replay() over the daily universe, split trades chronologically IS/OOS,
report n / win% / expectancy-R / profit-factor + a random-direction control. Uses pnl_r from
the SwingTrade ledger (entry-to-stop R). Run: python scripts/revalidate_new_strategies.py [N]
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import asyncio, json, random, statistics, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import syms
from replay_swing import replay

random.seed(13)
STRATS = ["rsi_pullback", "band_extreme_fade", "hidden_divergence"]


def _stats(rs):
    if not rs:
        return {"n": 0}
    wins = [x for x in rs if x > 0]; losses = [x for x in rs if x <= 0]
    gp = sum(wins); gl = -sum(losses)
    return {"n": len(rs), "win_pct": round(len(wins) / len(rs) * 100, 1),
            "expectancy_R": round(statistics.mean(rs), 4),
            "profit_factor": round(gp / gl, 2) if gl > 0 else float("inf")}


def summarize(trades):
    rs = [t.pnl_r for t in sorted(trades, key=lambda t: t.entry_date)]
    mid = len(rs) // 2
    ctrl = [r * random.choice([1, -1]) for r in rs]
    return {"all": _stats(rs), "in_sample": _stats(rs[:mid]),
            "out_sample": _stats(rs[mid:]), "random_control": _stats(ctrl)}


async def main():
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    since = sys.argv[2] if len(sys.argv) > 2 else "2006-01-01"
    only = sys.argv[3].split(",") if len(sys.argv) > 3 else STRATS
    sl = syms("1d")[:cap]
    out = {"n_symbols": len(sl), "since": since, "results": {}}
    for strat in only:
        trades = await replay(sl, since, "2026-06-30", strategy=strat)
        out["results"][strat] = summarize(trades)
        s = out["results"][strat]
        print(f"{strat:20} n={s['all']['n']:6} winALL={s['all'].get('win_pct')}%  "
              f"OOS: n={s['out_sample']['n']} PF={s['out_sample'].get('profit_factor')} "
              f"avgR={s['out_sample'].get('expectancy_R')} win={s['out_sample'].get('win_pct')}%  "
              f"IS_PF={s['in_sample'].get('profit_factor')}  ctrlPF={s['random_control'].get('profit_factor')}")
    Path("data/research/strategy_results/revalidation_inapp.json").write_text(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
