"""probability_service.py — single-source probability of success per strategy.

Combines two signals:

  1. **Backtest WR** — point estimate + bootstrap CI from
     ``strategy_configs/{name}.yaml.backtest_summary``. This is the
     prior — what we believed before any live trades happened.

  2. **Live WR** — observed win-rate of trades the strategy actually
     fired in production (read from ``analysis_service.load_trades``;
     filtered by ``strategy_name``). This is the evidence.

We expose all three numbers to the UI (backtest / live / blended) so the
caller can show each cleanly. The blended figure is **sample-size
weighted** — small live samples don't drown out a high-n backtest, but
they pull the estimate as more trades accumulate.

API
---
    compute(strategy_name) -> ProbabilityEstimate
    rating(estimate) -> str   ("strong", "moderate", "weak", "unknown")

Used by
-------
- /trades/{trade_id} detail page (Phase 4 — this session)
- StrategyHealthWidget could be refactored to use this (deferred — its
  current inline logic produces the same numbers).
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

import yaml

from services.settings_service import STRATEGY_CONFIG_DIR

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Data class
# --------------------------------------------------------------------------- #


@dataclass
class ProbabilityEstimate:
    """Probability of success for a strategy — backtest + live + blend."""

    strategy_name: str

    # Backtest (from strategy YAML)
    backtest_wr: float | None       = None     # %
    backtest_n: int                 = 0
    backtest_ci_lo: float | None    = None     # 95% CI lower bound, %
    backtest_ci_hi: float | None    = None     # 95% CI upper bound, %
    backtest_pf: float | None       = None     # profit factor
    backtest_window: str | None     = None     # e.g. "60d"

    # Live (from JSONL trade journal or dump CSV)
    live_wr: float | None           = None
    live_n: int                     = 0
    live_pf: float | None           = None

    # Blended — sample-size weighted average
    blended_wr: float | None        = None
    blended_n: int                  = 0

    # Status flags
    confidence: str                 = "unknown"   # strong | moderate | weak | unknown
    has_backtest: bool              = False
    has_live: bool                  = False
    notes: list[str]                = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Computation
# --------------------------------------------------------------------------- #


async def compute(strategy_name: str) -> ProbabilityEstimate:
    """Build a ProbabilityEstimate for ``strategy_name``.

    Reads strategy YAML for the prior, queries analysis_service for
    actual trades that match ``strategy_name``. Sample-size weighted
    blend.
    """
    est = ProbabilityEstimate(strategy_name=strategy_name)

    # ── Backtest prior ──────────────────────────────────────────────────
    bt = _load_backtest_summary(strategy_name)
    if bt:
        est.has_backtest    = True
        est.backtest_wr     = _f(bt.get("point_wr_pct"))
        est.backtest_n      = int(bt.get("filtered_trades_n", 0) or 0)
        est.backtest_ci_lo  = _f(bt.get("bootstrap_95_ci_lo"))
        est.backtest_ci_hi  = _f(bt.get("bootstrap_95_ci_hi"))
        est.backtest_pf     = _f(bt.get("profit_factor"))
        est.backtest_window = bt.get("window")
    else:
        est.notes.append("No backtest_summary block in strategy config.")

    # ── Live evidence ──────────────────────────────────────────────────
    live_n, live_wr, live_pf = await _live_stats_for(strategy_name)
    est.live_n = live_n
    if live_n > 0:
        est.has_live = True
        est.live_wr  = round(live_wr, 1)
        est.live_pf  = round(live_pf, 2) if live_pf != float("inf") else None

    # ── Sample-size weighted blend ──────────────────────────────────────
    if est.has_backtest and est.has_live and est.backtest_wr is not None:
        total_n = est.backtest_n + est.live_n
        if total_n > 0:
            est.blended_wr = round(
                (est.backtest_wr * est.backtest_n + est.live_wr * est.live_n) / total_n, 1,
            )
            est.blended_n = total_n
    elif est.has_backtest and est.backtest_wr is not None:
        est.blended_wr = est.backtest_wr
        est.blended_n  = est.backtest_n
    elif est.has_live:
        est.blended_wr = est.live_wr
        est.blended_n  = est.live_n

    # ── Confidence rating ───────────────────────────────────────────────
    est.confidence = rating(est)

    return est


def rating(est: ProbabilityEstimate) -> str:
    """Categorical confidence based on sample sizes + agreement.

    strong   — combined n >= 50 AND backtest+live agree (within 10pp)
    moderate — backtest exists with n >= 15, OR live n >= 30
    weak     — small backtest only (n < 15)
    unknown  — no backtest, no live
    """
    if not est.has_backtest and not est.has_live:
        return "unknown"
    n = est.blended_n
    if n >= 50 and est.has_backtest and est.has_live and est.backtest_wr is not None:
        gap = abs((est.live_wr or 0) - (est.backtest_wr or 0))
        if gap <= 10:
            return "strong"
    if (est.has_backtest and est.backtest_n >= 15) or est.live_n >= 30:
        return "moderate"
    return "weak"


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _load_backtest_summary(strategy_name: str) -> dict[str, Any] | None:
    """Read strategy_configs/{name}.yaml.backtest_summary."""
    path = STRATEGY_CONFIG_DIR / f"{strategy_name}.yaml"
    if not path.exists():
        return None
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        logger.warning("probability_service: bad yaml %s: %s", path.name, e)
        return None
    bt = cfg.get("backtest_summary")
    if not isinstance(bt, dict):
        return None
    return bt


async def _live_stats_for(strategy_name: str) -> tuple[int, float, float]:
    """Return (n, win_rate_pct, profit_factor) for live trades matching name.

    Falls through to dump CSV when no JSONL exists (pre-launch state).
    The dump represents one strategy at a time — currently only
    ``double_lock`` — so we treat the dump as "this strategy" if its
    rows are present and ``strategy_name`` matches.
    """
    # Local import — avoid a circular at module-load time.
    from services import analysis_service as A

    df = A.load_trades(source="auto", filter_to_production=True)
    if len(df) == 0:
        return 0, 0.0, 0.0

    if "strategy" in df.columns:
        sub = df[df["strategy"] == strategy_name]
    else:
        # Dump CSV has no strategy column — it represents the DL build's
        # signal set. Map it as `double_lock` for now; revisit when JSONL
        # trade journal carries an explicit strategy field per record.
        sub = df if strategy_name == "double_lock" else df.iloc[0:0]

    if len(sub) == 0:
        return 0, 0.0, 0.0

    pnls = sub["pnl_pct"].astype(float)
    wins = pnls[pnls > 0].sum()
    losses = -pnls[pnls < 0].sum()
    pf = (wins / losses) if losses > 0 else float("inf")
    wr = float(sub["win"].mean() * 100)
    return len(sub), wr, pf


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
