"""strategy_validation_service.py — run a real backtest from the UI and let
the "Validated" status be EARNED, with stored history/data as proof.

A strategy is not "validated" because a doc says so — it's validated because
a backtest over historical bars, run from the app, cleared the bar and the
result was persisted. This service runs that backtest:

  * fvg_continuation  -> scripts.replay_fvg over gold + 9 FX (30m), incl. a
                         random-direction control (the edge must beat a coin flip)
  * equity strategies -> scripts.replay_swing over the cached daily universe

It computes standardized metrics (n, win%, profit factor, OOS PF, expectancy,
net, control PF), decides PASS/FAIL against a profit-factor bar (the correct
metric for these payoff-geometry strategies — they win 25-55% BY DESIGN), and
writes a ``strategy_validations`` row. The Strategies page reads the latest
row to place each strategy in the Validated / In-Progress bucket.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path

from services import db_service
from services.settings_service import DATA_DIR, Settings, get_settings

logger = logging.getLogger(__name__)

# OOS profit-factor bar. These strategies make money on payoff geometry, so
# profit factor (not win rate) is the honest validation metric.
VALIDATION_PF_THRESHOLD = 1.20
# Recent fraction of trades (by time) treated as out-of-sample.
OOS_FRACTION = 0.30
# Cap the equity validation universe so a UI run stays responsive.
EQUITY_UNIVERSE_CAP = 120

FVG_STRATEGY = "fvg_continuation"
HIST_DIR = DATA_DIR / "historical"


def _stats(trades: list) -> dict | None:
    n = len(trades)
    if not n:
        return None
    pnls = [float(t.pnl_pct) for t in trades]
    gp = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p < 0)
    wins = sum(1 for t in trades if t.win)
    return {
        "n": n,
        "win_pct": round(wins / n * 100, 1),
        "pf": round(gp / gl, 3) if gl > 0 else float("inf"),
        "expectancy": round(sum(pnls) / n, 4),
        "net": round(sum(pnls), 2),
    }


def _oos_split(trades: list) -> list:
    """Return the recent OOS_FRACTION of trades, ordered by date."""
    ordered = sorted(trades, key=lambda t: getattr(t, "date_str", ""))
    cut = int(len(ordered) * (1 - OOS_FRACTION))
    return ordered[cut:]


def _cached_daily_universe(cap: int) -> list[str]:
    """Representative equity set = symbols with a cached daily bar file.

    Uses STRATIFIED sampling (every Nth across the sorted list) rather than
    the first-N — the first-N is alphabetically biased (all A-C names) and
    badly non-representative, which falsely fails a strategy. No network:
    validation must never stall on downloads.
    """
    syms = sorted(p.stem[:-3] for p in HIST_DIR.glob("*_1d.csv"))
    fx = {"EURUSD", "USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "EURAUD",
          "EURCAD", "GBPUSD", "AUDUSD", "XAUUSD"}
    syms = [s for s in syms if s not in fx]
    if len(syms) <= cap:
        return syms
    step = len(syms) / cap
    return [syms[int(i * step)] for i in range(cap)]


async def _validate_fvg(since: date, until: date) -> dict:
    from scripts.replay_fvg import _run_pair
    from services.fvg_scan_service import DEFAULT_SYMBOLS

    all_trades: list = []
    for sym in DEFAULT_SYMBOLS:
        try:
            all_trades += _run_pair(sym, since, until, interval="30m")
        except Exception as e:  # noqa: BLE001
            logger.warning("validate_fvg: %s failed: %s", sym, e)
    full = _stats(all_trades)
    oos = _stats(_oos_split(all_trades))

    # Random-direction control (mean of a couple seeds) — the edge must beat a coin flip.
    control_pfs: list[float] = []
    for seed in range(2):
        ctl: list = []
        for sym in DEFAULT_SYMBOLS:
            try:
                ctl += _run_pair(sym, since, until, interval="30m",
                                 control=True, seed=seed)
            except Exception:  # noqa: BLE001
                pass
        cst = _stats(ctl)
        if cst and cst["pf"] != float("inf"):
            control_pfs.append(cst["pf"])
    control_pf = round(sum(control_pfs) / len(control_pfs), 3) if control_pfs else None

    return {
        "universe_n": len(DEFAULT_SYMBOLS), "full": full, "oos": oos,
        "control_pf": control_pf,
        "params": {"engine": "replay_fvg", "interval": "30m", "target_R": 3.0,
                   "symbols": DEFAULT_SYMBOLS},
    }


async def _validate_equity(name: str, since: date, until: date,
                           universe_cap: int) -> dict:
    from scripts.replay_swing import replay

    universe = _cached_daily_universe(universe_cap)
    trades = await replay([s for s in universe], since.isoformat(),
                          until.isoformat(), strategy=name)
    full = _stats(trades)
    oos = _stats(_oos_split(trades))
    return {
        "universe_n": len(universe), "full": full, "oos": oos,
        "control_pf": None,
        "params": {"engine": "replay_swing", "strategy": name,
                   "universe_n": len(universe)},
    }


async def validate_strategy(
    name: str,
    settings: Settings | None = None,
    since: date | None = None,
    until: date | None = None,
    universe_cap: int = EQUITY_UNIVERSE_CAP,
) -> dict:
    """Run the backtest, score it, persist a strategy_validations row.

    Returns the persisted row (dict) including ``verdict`` and ``metrics``.
    """
    settings or get_settings()
    since = since or date(2010, 1, 1)
    until = until or date.today()

    if name == FVG_STRATEGY:
        res = await _validate_fvg(since, until)
    else:
        res = await _validate_equity(name, since, until, universe_cap)

    full = res["full"] or {}
    oos = res["oos"] or {}
    # Judge on OOS profit factor; fall back to full-sample PF if OOS is thin.
    oos_pf = oos.get("pf")
    judge_pf = oos_pf if (oos.get("n", 0) >= 30 and oos_pf not in (None, float("inf"))) \
        else full.get("pf")
    control_pf = res.get("control_pf")

    passed = False
    if judge_pf is not None and judge_pf != float("inf"):
        passed = judge_pf >= VALIDATION_PF_THRESHOLD
        # If a control was computed, require the edge to beat it clearly.
        if control_pf is not None and control_pf >= judge_pf:
            passed = False
    verdict = "validated" if passed else "failed"

    def _pf(v):  # inf -> None for storage/JSON
        return None if v == float("inf") else v

    row = {
        "strategy": name,
        "ts": datetime.now(timezone.utc).isoformat(),
        "window_start": since.isoformat(),
        "window_end": until.isoformat(),
        "universe_n": res["universe_n"],
        "n_trades": full.get("n", 0),
        "win_pct": full.get("win_pct"),
        "profit_factor": _pf(full.get("pf")),
        "oos_profit_factor": _pf(oos.get("pf")),
        "oos_win_pct": oos.get("win_pct"),
        "expectancy": full.get("expectancy"),
        "control_pf": control_pf,
        "net_pct": full.get("net"),
        "verdict": verdict,
        "threshold_pf": VALIDATION_PF_THRESHOLD,
        "metrics_json": {"full": full, "oos": oos, "judge_pf": _pf(judge_pf)},
        "params_json": res["params"],
    }
    try:
        row["id"] = await db_service.insert_validation(row)
    except Exception as e:  # noqa: BLE001
        logger.error("validate_strategy: persist failed for %s: %s", name, e)
        row["id"] = None

    logger.info("validate_strategy %s -> %s (n=%s judge_pf=%s control=%s)",
                name, verdict, full.get("n"), _pf(judge_pf), control_pf)
    return row
