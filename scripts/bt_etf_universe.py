"""bt_etf_universe — re-test index/ETF-specific effects on the cached ETF universe.

IBS is documented as an *index/ETF* mean-reversion effect (weaker on broad single stocks). Test it
(and Turn-of-the-Month) on the liquid ETFs we have cached. strategy_suite rig (IS/OOS + control).
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, summarize, random_control
import bt_ibs, bt_tom

# Liquid ETFs currently cached in data/historical (broad index + sectors)
ETFS = ["SPY", "IWM", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "XLC"]


def main():
    have = [s for s in ETFS if load(s, "1d") is not None]
    res = {"universe": "cached ETFs", "n_symbols": len(have), "symbols": have, "results": {}}
    for name, t in {
        "ibs_etf": bt_ibs.run(have, trend=False),
        "ibs_etf_hold3": bt_ibs.run(have, trend=False, max_hold=3),
        "tom_etf_5_3": bt_tom.run(have, 5, 3),
    }.items():
        res["results"][name] = summarize(t, random_control(t))
    Path("data/research/strategy_results/etf_universe.json").write_text(json.dumps(res, indent=2, default=str))
    for k, v in res["results"].items():
        a = v["all"]; oo = v["out_sample"]; rc = v["random_control"]
        print(f"{k:16} n={a['n']:6} win%={a['win_pct']}  OOS_PF={oo['profit_factor']} avgR={oo['expectancy_R']} "
              f"IS_PF={v['in_sample']['profit_factor']} ctrl={rc['profit_factor']}")


if __name__ == "__main__":
    main()
