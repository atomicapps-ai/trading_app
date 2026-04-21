"""Phase 4 universe_filter smoke test.

Exercises:
  1. Load criteria for liquid_momentum_core (multi-doc YAML parse).
  2. Load ticker list from the tickers YAML.
  3. Fetch daily bars for the seed list (downloads if cold; subsequent
     runs hit the CSV cache).
  4. Apply hard filters + score.
  5. Assert shape + determinism of the result.

The first run will download ~25 tickers' worth of daily history from
yfinance — expect 30-60s. Subsequent runs finish in single digits.

Run:  .venv\\Scripts\\python.exe -m scripts.smoke_phase4_universe
"""
from __future__ import annotations

import asyncio
import logging
import sys

import pandas as pd

from agents.universe_filter import UniverseFilter
from services.settings_service import Settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main() -> int:
    print("=" * 70)
    print("Phase 4 universe_filter smoke test")
    print("=" * 70)

    settings = Settings()
    uf = UniverseFilter(settings)

    # ---- 1. Live run (as_of_ts=None) -----------------------------------
    print("\n[1/3] run(liquid_momentum_core)  live")
    result = await uf.run("liquid_momentum_core", shortlist_size=10)
    assert result.preset_name == "liquid_momentum_core"
    assert result.total_screened == 25, (
        f"expected 25 seed tickers screened, got {result.total_screened}"
    )
    assert result.universe_size + result.rejected_count <= result.total_screened + 0
    print(
        f"  OK - screened={result.total_screened}, "
        f"passed={result.universe_size}, "
        f"shortlist={result.shortlist_size} ({result.run_duration_seconds:.2f}s)"
    )
    print(f"  top10: {result.shortlist}")
    if result.rejection_reasons:
        print(f"  rejections: {dict(result.rejection_reasons)}")

    # ---- 2. Backtest run (as_of_ts=2023-01-15) -------------------------
    print("\n[2/3] run(liquid_momentum_core)  as_of_ts=2023-01-15")
    historical_ts = pd.Timestamp("2023-01-15", tz="UTC")
    result_hist = await uf.run(
        "liquid_momentum_core",
        as_of_ts=historical_ts,
        shortlist_size=10,
    )
    assert result_hist.as_of_ts is not None
    assert result_hist.as_of_ts.startswith("2023-01-15"), (
        f"as_of_ts roundtrip broken: {result_hist.as_of_ts}"
    )
    print(
        f"  OK - screened={result_hist.total_screened}, "
        f"passed={result_hist.universe_size}, "
        f"shortlist={result_hist.shortlist_size} "
        f"({result_hist.run_duration_seconds:.2f}s)"
    )
    print(f"  top10 (historical): {result_hist.shortlist}")

    # Backtest result must differ from live — different bar window → different
    # rankings. Equal lists would indicate as_of_ts isn't actually slicing.
    if result.universe and result_hist.universe:
        assert result.shortlist != result_hist.shortlist or (
            result.prescreener_scores != result_hist.prescreener_scores
        ), "live and historical shortlists are identical — as_of_ts not applied?"
        print("  OK - historical ranking diverges from live (as_of_ts applied)")

    # ---- 3. Determinism: same call twice == same output ----------------
    print("\n[3/3] determinism  run(liquid_momentum_core) x2 at fixed as_of_ts")
    r1 = await uf.run("liquid_momentum_core", as_of_ts=historical_ts,
                      shortlist_size=10)
    r2 = await uf.run("liquid_momentum_core", as_of_ts=historical_ts,
                      shortlist_size=10)
    assert r1.shortlist == r2.shortlist, (
        f"non-deterministic: {r1.shortlist} vs {r2.shortlist}"
    )
    assert r1.prescreener_scores == r2.prescreener_scores, (
        "non-deterministic: prescreener_scores differ across runs"
    )
    print(f"  OK - identical output across two runs ({len(r1.shortlist)} symbols)")

    # ---- Bonus: empty preset returns empty shortlist ------------------
    print("\n[bonus] empty preset returns empty result")
    result_empty = await uf.run("mean_reversion_oversold", shortlist_size=10)
    assert result_empty.shortlist == []
    assert result_empty.total_screened == 0
    print("  OK - empty ticker list - empty shortlist (no crash)")

    print("\n" + "=" * 70)
    print("ALL GREEN - universe_filter is wired up correctly.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
