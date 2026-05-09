"""scripts/vector_analyze.py — Phase F.5 vector analysis on random_search_trials.

Queries the DB to produce:

1. Information coefficient (rank correlation) between each param and OOS score
2. Per-(entry_primitive) win rate of each regime/stop/tp combo
3. "Archetype" cluster of top-50 OOS-robust trials → spec card
4. Markdown report at strategies/VECTOR_ANALYSIS.md

No external ML deps — uses pandas/numpy and rank correlation. Heavier
clustering (UMAP/t-SNE) can be added later if scipy/scikit-learn become
reasonable to depend on.
"""
from __future__ import annotations

import json
import sqlite3
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

import numpy as np
import pandas as pd

from services import optimization_db


def load_df() -> pd.DataFrame:
    optimization_db.ensure_schema()
    with sqlite3.connect(optimization_db.DB_PATH) as c:
        df = pd.read_sql("SELECT * FROM random_search_trials", c)
    if df.empty:
        return df
    # Expand meta_config_json into columns
    cfgs = df["meta_config_json"].apply(json.loads)
    cfg_df = pd.DataFrame(list(cfgs))
    df = pd.concat([df.drop(columns=["meta_config_json"]), cfg_df.add_prefix("p_")], axis=1)
    fvs = df["feature_vector_json"].apply(json.loads)
    fv_df = pd.DataFrame(list(fvs))
    df = pd.concat([df.drop(columns=["feature_vector_json"]), fv_df.add_prefix("f_")], axis=1)
    return df


def spearman(x: pd.Series, y: pd.Series) -> float:
    """Spearman rank correlation. Falls back to NaN on all-equal x or y."""
    if x.nunique(dropna=True) < 2 or y.nunique(dropna=True) < 2:
        return float("nan")
    rx = x.rank(method="average")
    ry = y.rank(method="average")
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(rx.corr(ry))


def info_coef_table(df: pd.DataFrame, target_col: str) -> pd.DataFrame:
    """Spearman rank correlation between each numeric param and target."""
    candidates = [c for c in df.columns if c.startswith("p_")
                  and df[c].dtype in (np.float64, np.int64)]
    rows = []
    for c in candidates:
        rho = spearman(df[c], df[target_col])
        rows.append({"param": c[2:], "spearman": round(rho, 4) if not np.isnan(rho) else None,
                     "n": int(df[[c, target_col]].dropna().shape[0])})
    out = pd.DataFrame(rows).sort_values(
        by="spearman",
        key=lambda s: s.abs().fillna(-1),
        ascending=False,
    )
    return out


def categorical_score_table(df: pd.DataFrame, col: str, target: str) -> pd.DataFrame:
    """For a categorical column, group by value and report mean target."""
    g = df.groupby(col)[target].agg(["count", "mean", "median"])
    g.columns = ["n", "mean_score", "median_score"]
    return g.sort_values("mean_score", ascending=False).round(3).reset_index()


def find_archetypes(df: pd.DataFrame, n_top: int = 50) -> pd.DataFrame:
    """Return the top-N OOS-robust trials sorted by `oos_score` descending.

    Filters: PF>1, n_trades>=30, oos_score>0, |is_oos_gap_pct|<=0.5.
    """
    mask = (
        (df["profit_factor"] > 1.0)
        & (df["n_trades"] >= 30)
        & (df["oos_score"] > 0)
        & (df["is_oos_gap_pct"].abs() <= 0.5)
    )
    return df[mask].sort_values("oos_score", ascending=False).head(n_top).copy()


def archetype_summary(top: pd.DataFrame) -> str:
    if top.empty:
        return "(no OOS-robust trials yet)"

    out = [
        f"Top {len(top)} OOS-robust trials. Distribution of choices:",
        "",
    ]
    # Frequency of categorical configs in winners
    for col in ["entry_primitive", "stop_type", "tp_type"]:
        cnt = top[col].value_counts()
        out.append(f"### {col}")
        for v, n in cnt.items():
            out.append(f"  {v:<22s}  {n:>3d}/{len(top)}  ({100*n/len(top):.0f}%)")
        out.append("")

    # Regime filter usage
    cnt = top["regime_filter_count"].value_counts().sort_index()
    out.append("### regime_filter_count")
    for v, n in cnt.items():
        out.append(f"  {v} filters     {n:>3d}/{len(top)}")
    out.append("")
    n_vol = int(top["uses_volume_filter"].sum())
    out.append(f"### uses_volume_filter")
    out.append(f"  on:  {n_vol}/{len(top)}")
    out.append(f"  off: {len(top) - n_vol}/{len(top)}")
    out.append("")
    # Symbol-class spread
    cnt = top["f_symbol_class"].value_counts() if "f_symbol_class" in top.columns else None
    if cnt is not None:
        out.append("### symbol_class")
        for v, n in cnt.items():
            out.append(f"  {v:<12s}  {n:>3d}/{len(top)}")
    return "\n".join(out)


def main() -> int:
    df = load_df()
    if df.empty:
        print("no rows yet — run scripts/random_search.py first")
        return 1

    n_total = len(df)
    n_eligible = int(((df["profit_factor"] > 1.0) & (df["n_trades"] >= 30)).sum())
    archetypes = find_archetypes(df, n_top=50)

    sections = [
        f"# Vector Analysis — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"Read from `data/optimization_results.db::random_search_trials`.",
        f"Trials in DB: **{n_total:,}** · eligible (PF>1, N≥30): **{n_eligible:,}** · "
        f"OOS-robust archetypes: **{len(archetypes)}**",
        "",
        "---",
        "",
        "## 1. Information coefficient — params vs full-window score",
        "",
        "Spearman rank correlation. |IC| > 0.05 is meaningful at this sample size.",
        "Positive = larger value → higher score.",
        "",
        "```",
        info_coef_table(df, "score").head(15).to_string(index=False),
        "```",
        "",
        "## 2. IC vs OOS score (the version that actually matters)",
        "",
        "```",
        info_coef_table(df, "oos_score").head(15).to_string(index=False),
        "```",
        "",
        "## 3. Categorical config rankings (mean score per choice)",
        "",
        "### entry_primitive",
        "```",
        categorical_score_table(df[df["n_trades"] >= 30], "entry_primitive", "score").to_string(index=False),
        "```",
        "",
        "### stop_type",
        "```",
        categorical_score_table(df[df["n_trades"] >= 30], "stop_type", "score").to_string(index=False),
        "```",
        "",
        "### tp_type",
        "```",
        categorical_score_table(df[df["n_trades"] >= 30], "tp_type", "score").to_string(index=False),
        "```",
        "",
        "## 4. OOS-robust archetypes",
        "",
        archetype_summary(archetypes),
        "",
        "## 5. Top 20 individual archetype configs",
        "",
    ]

    if not archetypes.empty:
        for _, r in archetypes.head(20).iterrows():
            sections.append(
                f"- **{r['symbol']}** · `{r['entry_primitive']}` · "
                f"stop={r['stop_type']} · tp={r['tp_type']} · "
                f"rf={int(r['regime_filter_count'])} · vol={int(r['uses_volume_filter'])} "
                f"→ N={int(r['n_trades'])} WR={r['wr_pct']:.1f}% PF={r['profit_factor']:.2f} "
                f"OOS={r['oos_score']:.2f} IS={r['is_score']:.2f} gap={r['is_oos_gap_pct']:.2f}"
            )

    text = "\n".join(sections)
    out = ROOT / "strategies" / "VECTOR_ANALYSIS.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nWritten to: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
