"""analysis_service.py — failure-analysis data layer for /trades/analysis.

Loads closed trades + their feature vector at entry from one of two sources:

  1. ``data/claude_trades_dump.csv`` — backtest dump (81 trades + 10 features).
     Default for the pre-launch period before live trades exist. Lets the
     analysis page be useful TODAY against the data we already have.

  2. ``trade_logs/*.jsonl`` — production trade journal written by the
     executioner once paper trading goes live. Schema is the canonical
     ``models.trade_record.TradeRecord``. Activated by passing
     ``source="jsonl"``.

The service computes the same cuts on either source so the UI is identical
either way; only the data underneath differs.

Public surface
--------------
    load_trades(source="auto") -> pandas.DataFrame
    summary(df) -> dict
    by_quartile(df, column, label) -> list[dict]
    by_binary(df, column) -> list[dict]
    by_symbol(df) -> list[dict]
    loser_clusters(df) -> list[dict]
    equity_curve(df) -> list[dict]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from services.settings_service import PROJECT_ROOT, TRADE_LOG_DIR

logger = logging.getLogger(__name__)

DUMP_CSV: Path = PROJECT_ROOT / "claude_trades_dump.csv"

Source = Literal["auto", "dump", "jsonl"]

# Canonical column set every cut function expects. Used to produce a
# well-typed empty frame when no data source is available, so the
# /trades/analysis page renders an empty state instead of 500-ing.
_CANONICAL_COLS = [
    "sym", "date", "dir", "pnl_pct", "win",
    "rsi14_d", "vix_level", "adx14_d",
    "spy_aligned", "above_sma50_d", "prior_day_match",
    "rs_vs_spy", "gap_pct", "or_size_vs_atr",
    "entry", "exit", "exit_reason", "mfe_pct", "mae_pct",
    "source",
]


def _empty_frame() -> pd.DataFrame:
    """Properly-shaped empty DataFrame so cut functions don't KeyError."""
    return pd.DataFrame({c: pd.Series(dtype="object") for c in _CANONICAL_COLS})


# ── Loaders ────────────────────────────────────────────────────────────────
def load_trades(
    source: Source = "auto",
    filter_to_production: bool = True,
) -> pd.DataFrame:
    """Return a normalized DataFrame of closed trades.

    Columns: sym, date, dir (LONG/SHORT), pnl_pct, win (0/1), and as many
    feature columns as the source provides (rsi14_d, vix_level, adx14_d,
    etc. from the dump; entry/exit/exit_reason/mfe/mae from JSONL).

    ``filter_to_production`` only applies when source resolves to "dump":
    JSONL trades are already production-filtered (the executioner only
    writes records for trades the strategy actually took).
    """
    if source == "auto":
        source = "jsonl" if _jsonl_files() else "dump"

    if source == "dump":
        return _load_dump(apply_production_filter=filter_to_production)
    return _load_jsonl()


def _jsonl_files() -> list[Path]:
    if not TRADE_LOG_DIR.exists():
        return []
    return sorted(TRADE_LOG_DIR.glob("*.jsonl"))


def _load_dump(apply_production_filter: bool = True) -> pd.DataFrame:
    """Load the backtest dump CSV.

    The dump contains every DL-S2 candle hit (81 trades), not just the
    ones the production strategy filter would actually trade (17 trades).
    By default we apply the same filter the production detector uses
    so the analysis page shows what live data will look like — matching
    the strategy_configs/double_lock.yaml thresholds exactly.

    Toggle off via load_trades(filter_to_production=False) for a raw
    "all signals" view (useful for "should we relax the filter?" debate).
    """
    if not DUMP_CSV.exists():
        return _empty_frame()
    df = pd.read_csv(DUMP_CSV)
    for col in ("entry", "exit", "exit_reason", "mfe_pct", "mae_pct"):
        if col not in df.columns:
            df[col] = np.nan

    if apply_production_filter:
        # Mirror strategy_configs/double_lock.yaml thresholds.
        long_ok = (
            (df["dir"].str.upper() == "LONG")
            & (df["rsi14_d"] >= 40) & (df["rsi14_d"] <= 65)
        )
        short_ok = (
            (df["dir"].str.upper() == "SHORT")
            & (df["rsi14_d"] >= 20) & (df["rsi14_d"] <= 40)
        )
        df = df[
            (df["vix_level"] >= 20)
            & (df["adx14_d"] <= 35)
            & (long_ok | short_ok)
        ].reset_index(drop=True)

    df["source"] = "dump (production-filter)" if apply_production_filter else "dump (all signals)"
    return df


def _load_jsonl() -> pd.DataFrame:
    """Flatten TradeRecord JSONL into the same shape as the dump."""
    rows: list[dict] = []
    for path in _jsonl_files():
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning("bad JSONL row in %s: %s", path.name, e)
                    continue
                rows.append(_flatten_record(rec))
    if not rows:
        return _empty_frame()
    df = pd.DataFrame(rows)
    df["source"] = "jsonl"
    return df


def _flatten_record(rec: dict) -> dict:
    """Map a TradeRecord dict to the analysis row schema."""
    inst    = rec.get("instrument", {}) or {}
    setup   = rec.get("setup_snapshot", {}) or {}
    feats   = setup.get("entry_features", {}) or {}
    exec_   = rec.get("execution", {}) or {}
    out     = rec.get("outcome", {}) or {}
    life    = rec.get("lifecycle", {}) or {}

    pnl_pct = out.get("pnl_pct")
    if pnl_pct is None and out.get("pnl_usd") is not None and exec_.get("planned_entry_notional"):
        pnl_pct = (out["pnl_usd"] / exec_["planned_entry_notional"]) * 100

    return {
        "sym":            inst.get("symbol", ""),
        "date":           (life.get("ts_entered") or "")[:10],
        "dir":            (setup.get("direction") or "").upper(),
        "pnl_pct":        float(pnl_pct) if pnl_pct is not None else 0.0,
        "win":            int(out.get("win", 0)) if "win" in out else int((pnl_pct or 0.0) > 0),
        "entry":          exec_.get("entry_price_actual") or exec_.get("entry_price_planned"),
        "exit":           exec_.get("exit_price_actual"),
        "exit_reason":    out.get("exit_reason"),
        "mfe_pct":        out.get("mfe_pct"),
        "mae_pct":        out.get("mae_pct"),
        # entry features — keep names compatible with the dump
        "rsi14_d":        feats.get("rsi14_d"),
        "vix_level":      feats.get("vix_level"),
        "adx14_d":        feats.get("adx14_d"),
        "spy_aligned":    feats.get("spy_aligned"),
        "rs_vs_spy":      feats.get("rs_vs_spy"),
        "above_sma50_d":  feats.get("above_sma50_d"),
        "gap_pct":        feats.get("gap_pct"),
        "prior_day_match": feats.get("prior_day_match"),
        "or_size_vs_atr": feats.get("or_size_vs_atr"),
        "strategy":       setup.get("strategy_name", ""),
        "trade_id":       rec.get("trade_id"),
    }


# ── Cuts ───────────────────────────────────────────────────────────────────
def summary(df: pd.DataFrame, backtest_wr: float = 82.4,
            backtest_ci_lo: float = 64.7) -> dict:
    """Headline metrics + drift indicator vs backtest claim."""
    if len(df) == 0:
        return dict(n=0, wr=None, pf=None, avg=None, sum=None,
                    backtest_wr=backtest_wr, backtest_ci_lo=backtest_ci_lo,
                    drift=None, drift_status="no-data", source="—")
    pnls = df["pnl_pct"].astype(float)
    wins = pnls[pnls > 0].sum()
    losses = -pnls[pnls < 0].sum()
    pf = (wins / losses) if losses > 0 else float("inf")
    wr = float(df["win"].mean() * 100)
    drift = wr - backtest_wr
    if wr >= backtest_wr:
        drift_status = "above-backtest"
    elif wr >= backtest_ci_lo:
        drift_status = "within-ci"
    else:
        drift_status = "below-ci"        # alarm — strategy may have broken
    return dict(
        n=len(df),
        wr=round(wr, 1),
        pf=round(pf, 2) if pf != float("inf") else None,
        avg=round(float(pnls.mean()), 2),
        sum=round(float(pnls.sum()), 2),
        backtest_wr=backtest_wr,
        backtest_ci_lo=backtest_ci_lo,
        drift=round(drift, 1),
        drift_status=drift_status,
        source=df["source"].iloc[0] if "source" in df.columns else "—",
    )


def by_quartile(df: pd.DataFrame, column: str, label: str | None = None) -> list[dict]:
    """Bucket trades into quartiles of `column` and report WR/PF per bucket."""
    if column not in df.columns:
        return []
    s = df[column].dropna()
    if len(s) < 8 or s.std() == 0:
        return []
    try:
        labels = ["Q1 (low)", "Q2", "Q3", "Q4 (high)"]
        qs = pd.qcut(s, 4, labels=labels, duplicates="drop")
    except ValueError:
        return []
    out: list[dict] = []
    for q in labels:
        sub = df.loc[qs.index[qs == q]]
        if len(sub) == 0:
            continue
        pnls = sub["pnl_pct"].astype(float)
        wr = float(sub["win"].mean() * 100)
        wins = pnls[pnls > 0].sum()
        losses = -pnls[pnls < 0].sum()
        pf = (wins / losses) if losses > 0 else float("inf")
        rng = (float(s[qs == q].min()), float(s[qs == q].max()))
        out.append(dict(
            label=label or column,
            bucket=str(q),
            range=f"{rng[0]:.2f} – {rng[1]:.2f}",
            n=len(sub),
            wr=round(wr, 1),
            pf=round(pf, 2) if pf != float("inf") else None,
            avg=round(float(pnls.mean()), 2),
        ))
    return out


def by_binary(df: pd.DataFrame, column: str) -> list[dict]:
    if column not in df.columns:
        return []
    s = df[column].dropna()
    if len(s) == 0:
        return []
    out: list[dict] = []
    for v in (0, 1):
        sub = df.loc[s.index[s == v]]
        if len(sub) == 0:
            continue
        pnls = sub["pnl_pct"].astype(float)
        wins = pnls[pnls > 0].sum()
        losses = -pnls[pnls < 0].sum()
        pf = (wins / losses) if losses > 0 else float("inf")
        out.append(dict(
            label=column,
            bucket=f"{column}={v}",
            n=len(sub),
            wr=round(float(sub["win"].mean() * 100), 1),
            pf=round(pf, 2) if pf != float("inf") else None,
            avg=round(float(pnls.mean()), 2),
        ))
    return out


def by_direction(df: pd.DataFrame) -> list[dict]:
    if len(df) == 0 or "dir" not in df.columns:
        return []
    out: list[dict] = []
    for d in ("LONG", "SHORT"):
        sub = df[df["dir"].astype(str).str.upper() == d]
        if len(sub) == 0:
            continue
        pnls = sub["pnl_pct"].astype(float)
        wins = pnls[pnls > 0].sum()
        losses = -pnls[pnls < 0].sum()
        pf = (wins / losses) if losses > 0 else float("inf")
        out.append(dict(
            direction=d,
            n=len(sub),
            wr=round(float(sub["win"].mean() * 100), 1),
            pf=round(pf, 2) if pf != float("inf") else None,
            avg=round(float(pnls.mean()), 2),
        ))
    return out


def by_symbol(df: pd.DataFrame, min_trades: int = 1) -> list[dict]:
    if len(df) == 0 or "sym" not in df.columns:
        return []
    out: list[dict] = []
    for sym, sub in df.groupby("sym"):
        if len(sub) < min_trades:
            continue
        pnls = sub["pnl_pct"].astype(float)
        wins = pnls[pnls > 0].sum()
        losses = -pnls[pnls < 0].sum()
        pf = (wins / losses) if losses > 0 else float("inf")
        out.append(dict(
            sym=sym,
            n=len(sub),
            wr=round(float(sub["win"].mean() * 100), 1),
            pf=round(pf, 2) if pf != float("inf") else None,
            avg=round(float(pnls.mean()), 2),
            sum=round(float(pnls.sum()), 2),
        ))
    return sorted(out, key=lambda r: -r["n"])


def loser_clusters(df: pd.DataFrame) -> dict:
    """Group losing trades by feature buckets — surfaces failure modes."""
    if len(df) == 0 or "pnl_pct" not in df.columns:
        return dict(n=0, clusters=[])
    losers = df[df["pnl_pct"] < 0].copy()
    if len(losers) == 0:
        return dict(n=0, clusters=[])

    clusters: list[dict] = []

    # By exit reason (only meaningful with JSONL data)
    if "exit_reason" in losers.columns and losers["exit_reason"].notna().any():
        for r, sub in losers.groupby("exit_reason", dropna=True):
            clusters.append(dict(
                kind="exit_reason",
                bucket=str(r),
                n=len(sub),
                avg_loss=round(float(sub["pnl_pct"].mean()), 2),
            ))

    # By RSI quartile
    if "rsi14_d" in losers.columns and losers["rsi14_d"].notna().sum() >= 4:
        try:
            qs = pd.qcut(losers["rsi14_d"], 4, labels=["Q1", "Q2", "Q3", "Q4"],
                         duplicates="drop")
            for q, sub in losers.groupby(qs):
                clusters.append(dict(
                    kind="rsi_quartile",
                    bucket=str(q),
                    n=len(sub),
                    avg_loss=round(float(sub["pnl_pct"].mean()), 2),
                ))
        except ValueError:
            pass

    # By VIX quartile
    if "vix_level" in losers.columns and losers["vix_level"].notna().sum() >= 4:
        try:
            qs = pd.qcut(losers["vix_level"], 4, labels=["Q1", "Q2", "Q3", "Q4"],
                         duplicates="drop")
            for q, sub in losers.groupby(qs):
                clusters.append(dict(
                    kind="vix_quartile",
                    bucket=str(q),
                    n=len(sub),
                    avg_loss=round(float(sub["pnl_pct"].mean()), 2),
                ))
        except ValueError:
            pass

    return dict(n=len(losers), clusters=clusters)


def equity_curve(df: pd.DataFrame) -> list[dict]:
    """Cumulative PnL over time — for the chart on the analysis page."""
    if "date" not in df.columns or len(df) == 0:
        return []
    sorted_df = df.sort_values("date").reset_index(drop=True)
    cum = 0.0
    out: list[dict] = []
    for _, r in sorted_df.iterrows():
        cum += float(r["pnl_pct"])
        out.append(dict(
            date=str(r["date"]),
            sym=r["sym"],
            dir=r["dir"],
            pnl_pct=round(float(r["pnl_pct"]), 2),
            cum_pnl_pct=round(cum, 2),
            win=int(r["win"]),
        ))
    return out


def per_trade(df: pd.DataFrame, only_losses: bool = False) -> list[dict]:
    """Full per-trade ledger with the entry-feature vector."""
    if len(df) == 0 or "pnl_pct" not in df.columns or "date" not in df.columns:
        return []
    if only_losses:
        df = df[df["pnl_pct"] < 0]
    rows: list[dict] = []
    for _, r in df.sort_values("date", ascending=False).iterrows():
        rows.append(dict(
            date=str(r.get("date", "")),
            sym=str(r.get("sym", "")),
            dir=str(r.get("dir", "")).upper(),
            pnl_pct=round(float(r["pnl_pct"]), 2),
            win=int(r["win"]),
            rsi14_d=_fmt(r.get("rsi14_d"), 1),
            adx14_d=_fmt(r.get("adx14_d"), 1),
            vix_level=_fmt(r.get("vix_level"), 2),
            gap_pct=_fmt(r.get("gap_pct"), 2),
            spy_aligned=int(r["spy_aligned"]) if pd.notna(r.get("spy_aligned")) else None,
            exit_reason=r.get("exit_reason") if pd.notna(r.get("exit_reason")) else None,
            mfe_pct=_fmt(r.get("mfe_pct"), 2),
            mae_pct=_fmt(r.get("mae_pct"), 2),
        ))
    return rows


def _fmt(v, places: int):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return None
    try:
        return round(float(v), places)
    except (TypeError, ValueError):
        return None
