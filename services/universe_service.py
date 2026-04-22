"""universe_service.py — preset + history operations for the /universe UI.

Responsibilities
----------------
1. Enumerate presets from ``universe_filter_presets.yaml``.
2. Load a preset's full record: criteria (from the criteria YAML) +
   current ticker list (from the tickers YAML) + prescreener state
   from the most recent pipeline run (``data/universe_latest.json``).
3. Archive snapshots on every write. Called by the refresh script and
   any future edit endpoints. Archive lives under
   ``data/universe_history/{preset}/{kind}/{iso_ts}.yaml`` where
   ``kind`` ∈ {``criteria``, ``tickers``}.
4. Expose history to the UI: list snapshots, load one, restore one.

History storage rationale
-------------------------
The criteria and tickers YAMLs are also committed to git, so git log
is already a source of truth. Mirroring snapshots into
``data/universe_history/`` gives the UI a fast listing without shelling
out to git on every page load, and makes "restore this version" a
pure file copy rather than a git checkout.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from services.settings_service import (
    DATA_DIR,
    PROJECT_ROOT,
    UniverseUISettings,
    get_settings,
)

logger = logging.getLogger(__name__)

CRITERIA_FILE: Path = PROJECT_ROOT / "universe_filter_presets.yaml"
TICKERS_FILE: Path = PROJECT_ROOT / "universe_filter_presets_tickers.yaml"
LATEST_RESULT_FILE: Path = DATA_DIR / "universe_latest.json"
HISTORY_DIR: Path = DATA_DIR / "universe_history"

# Presets that intentionally don't appear in the refresh flow. Still
# listed in the UI so the user can see what exists, but flagged so the
# "refresh" / "restore from history" actions are hidden for them.
NON_REFRESH_PRESETS = {"sentiment_catalyst", "etf_sector_rotation"}


# ---------------------------------------------------------------------- #
# Criteria YAML
# ---------------------------------------------------------------------- #


def _load_criteria_docs() -> dict[str, dict]:
    """Parse the multi-doc criteria YAML. Return {preset_name: doc}."""
    if not CRITERIA_FILE.exists():
        return {}
    out: dict[str, dict] = {}
    text = CRITERIA_FILE.read_text(encoding="utf-8")
    for doc in yaml.safe_load_all(text):
        if isinstance(doc, dict) and doc.get("preset_name"):
            out[doc["preset_name"]] = doc
    return out


def _load_tickers_doc() -> dict[str, dict]:
    """Return {preset_name: {refreshed_at, source, tickers}}."""
    if not TICKERS_FILE.exists():
        return {}
    data = yaml.safe_load(TICKERS_FILE.read_text(encoding="utf-8")) or {}
    return dict(data.get("presets") or {})


def _load_latest_result() -> dict | None:
    if not LATEST_RESULT_FILE.exists():
        return None
    try:
        return json.loads(LATEST_RESULT_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("universe_latest.json is malformed; ignoring")
        return None


# ---------------------------------------------------------------------- #
# Public API — list + detail
# ---------------------------------------------------------------------- #


def list_presets() -> list[dict]:
    """Summary row per preset — what /universe list page renders."""
    criteria_docs = _load_criteria_docs()
    tickers_doc = _load_tickers_doc()
    out: list[dict] = []
    for name, doc in criteria_docs.items():
        tickers_info = tickers_doc.get(name) or {}
        ticker_list = tickers_info.get("tickers") or []
        hist = _count_history(name)
        out.append({
            "preset_name": name,
            "description": (doc.get("description") or "").strip(),
            "strategy_affinity": _strategy_affinity_from_output_tags(
                doc.get("output_tags") or [],
            ),
            "version": doc.get("version"),
            "ticker_count": len(ticker_list),
            "refreshed_at": tickers_info.get("refreshed_at"),
            "source": tickers_info.get("source"),
            "refreshable": name not in NON_REFRESH_PRESETS,
            "criteria_versions": hist["criteria"],
            "ticker_versions": hist["tickers"],
        })
    # Stable order: refreshable first, then alphabetical
    out.sort(key=lambda p: (not p["refreshable"], p["preset_name"]))
    return out


def get_preset(preset_name: str) -> dict | None:
    """Full record for one preset — criteria + current tickers + last run."""
    docs = _load_criteria_docs()
    if preset_name not in docs:
        return None
    criteria_doc = docs[preset_name]
    tickers_info = _load_tickers_doc().get(preset_name) or {}
    latest = _load_latest_result()
    prescreener_scores: dict[str, float] = {}
    shortlist: list[str] = []
    latest_ts: str | None = None
    if latest and latest.get("preset_name") == preset_name:
        prescreener_scores = latest.get("prescreener_scores") or {}
        shortlist = latest.get("shortlist") or []
        latest_ts = latest.get("ts_run")
    tickers = list(tickers_info.get("tickers") or [])
    tickers_with_scores = [
        {
            "symbol": sym,
            "prescreener_score": prescreener_scores.get(sym),
            "in_shortlist": sym in shortlist,
        }
        for sym in tickers
    ]
    hist = _list_history(preset_name)
    ui_cfg = get_settings().universe.ui
    criteria = criteria_doc.get("criteria") or {}
    groups, hidden = _group_criteria(criteria, ui_cfg)
    return {
        "preset_name": preset_name,
        "description": (criteria_doc.get("description") or "").strip(),
        "version": criteria_doc.get("version"),
        "output_tags": criteria_doc.get("output_tags") or [],
        "notes": (criteria_doc.get("notes") or "").strip(),
        "criteria": criteria,
        "criteria_groups": groups,
        "hidden_criteria_keys": hidden,
        "ui_config": {
            "include_fields": list(ui_cfg.include_fields),
            "exclude_fields": list(ui_cfg.exclude_fields),
            "pinned_fields": list(ui_cfg.pinned_fields),
        },
        "refreshable": preset_name not in NON_REFRESH_PRESETS,
        "tickers_info": {
            "refreshed_at": tickers_info.get("refreshed_at"),
            "source": tickers_info.get("source"),
            "count": len(tickers),
        },
        "tickers": tickers_with_scores,
        "last_pipeline_run": {
            "ts_run": latest_ts,
            "shortlist_size": len(shortlist),
            "scores_available": bool(prescreener_scores),
        },
        "history": hist,
    }


# ---------------------------------------------------------------------- #
# History archive
# ---------------------------------------------------------------------- #


def archive_snapshot(kind: str, preset_name: str, payload: dict) -> Path:
    """Write a timestamped YAML snapshot of `payload` under
    ``data/universe_history/{preset}/{kind}/{iso_ts}.yaml``.

    ``kind`` must be ``criteria`` or ``tickers``. Returns the path
    written. Safe to call before mutating the live YAMLs — gives us
    a rollback point.
    """
    if kind not in ("criteria", "tickers"):
        raise ValueError(f"unsupported archive kind: {kind!r}")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst_dir = HISTORY_DIR / preset_name / kind
    dst_dir.mkdir(parents=True, exist_ok=True)
    path = dst_dir / f"{ts}.yaml"
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    logger.info("universe archive: wrote %s", path)
    return path


def _list_history(preset_name: str) -> dict[str, list[dict]]:
    """Return {'criteria': [...], 'tickers': [...]} for the UI history tab."""
    out = {"criteria": [], "tickers": []}
    base = HISTORY_DIR / preset_name
    if not base.exists():
        return out
    for kind in out.keys():
        sub = base / kind
        if not sub.exists():
            continue
        snapshots = []
        for f in sorted(sub.glob("*.yaml"), reverse=True):
            snapshots.append({
                "ts": f.stem,  # e.g. 20260421T185530Z
                "filename": f.name,
                "size_bytes": f.stat().st_size,
            })
        out[kind] = snapshots
    return out


def _count_history(preset_name: str) -> dict[str, int]:
    """Just the counts — for the list page (doesn't need full entries)."""
    base = HISTORY_DIR / preset_name
    if not base.exists():
        return {"criteria": 0, "tickers": 0}
    return {
        "criteria": len(list((base / "criteria").glob("*.yaml")))
                    if (base / "criteria").exists() else 0,
        "tickers":  len(list((base / "tickers").glob("*.yaml")))
                    if (base / "tickers").exists() else 0,
    }


def load_history_snapshot(
    preset_name: str, kind: str, ts: str,
) -> dict | None:
    """Read one archived snapshot. Used by the history-detail endpoint."""
    if kind not in ("criteria", "tickers"):
        return None
    path = HISTORY_DIR / preset_name / kind / f"{ts}.yaml"
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------- #
# Presentation helpers
# ---------------------------------------------------------------------- #


_CRITERIA_GROUPS: list[tuple[str, list[str]]] = [
    ("Price & Volume", [
        "price_min", "price_max",
        "avg_volume_min", "avg_dollar_volume_min",
        "relative_volume_min", "performance_today_max",
    ]),
    ("Size", ["market_cap", "asset_class"]),
    ("Profitability", [
        "eps_ttm_positive", "eps_growth_yoy_min", "eps_growth_qoq_min",
        "operating_margin_positive", "operating_margin_min",
        "roe_positive", "roe_min",
        "gross_margin_min",
        "debt_to_equity_max", "current_ratio_min",
        "insider_ownership_min",
        "ipo_date_before", "etf_inception_before",
    ]),
    ("Technical", [
        "sma20_relation", "sma50_relation", "sma200_relation",
        "rsi_min", "rsi_max",
        "performance_week_min", "performance_week_max",
        "performance_month_min", "performance_month_max",
        "performance_3month_min", "performance_6month_min", "performance_6month_max",
        "week_52_high_pct_min", "week_52_high_pct_max",
    ]),
    ("Volatility", [
        "atr_pct_min", "atr_pct_max",
        "beta_min", "beta_max",
    ]),
    ("Short interest", ["short_float_max"]),
    ("Exchange & sector", [
        "exchange", "exclude_otc", "exclude_pink_sheets",
        "sector_exclude", "elevated_risk_sectors",
        "elevated_risk_industries",
        "etf_leverage", "etf_symbol_whitelist",
    ]),
]


def _group_criteria(
    criteria: dict[str, Any], ui: UniverseUISettings,
) -> tuple[list[dict], list[str]]:
    """Arrange criteria into visual groups for rendering.

    Applies the operator's universe-UI settings:
      * ``include_fields`` — if non-empty, restrict visible fields to
        this set (order within the set is still dictated by the group
        schema below, except for pinned_fields which honor user order).
      * ``exclude_fields`` — always drop these.
      * ``pinned_fields`` — surface these first under a "Pinned" group,
        in user-specified order.

    Returns ``(groups, hidden_keys)`` — ``hidden_keys`` is the list of
    keys present on the preset but filtered out by the UI config, so
    the template can show a "N fields hidden by your settings" hint.
    """
    include = set(ui.include_fields or [])
    exclude = set(ui.exclude_fields or [])
    pinned_order = [k for k in (ui.pinned_fields or []) if k in criteria]

    def _visible(key: str) -> bool:
        if key in exclude:
            return False
        if include and key not in include and key not in pinned_order:
            return False
        return True

    entry = lambda k: {  # noqa: E731
        "key": k,
        "value": criteria[k],
        "display_value": _format_criterion_value(criteria[k]),
    }

    groups: list[dict] = []
    assigned: set[str] = set()

    # Pinned group first — explicit operator priority.
    if pinned_order:
        pinned_entries = [entry(k) for k in pinned_order if _visible(k)]
        if pinned_entries:
            groups.append({"name": "Pinned", "entries": pinned_entries})
            assigned.update(e["key"] for e in pinned_entries)

    # Standard groups (skip already-pinned keys).
    for group_name, keys in _CRITERIA_GROUPS:
        group_entries = []
        for k in keys:
            if k in criteria and k not in assigned and _visible(k):
                group_entries.append(entry(k))
                assigned.add(k)
        if group_entries:
            groups.append({"name": group_name, "entries": group_entries})

    # Other — unmapped keys that pass the visibility filter.
    others = [
        entry(k) for k in criteria
        if k not in assigned and _visible(k)
    ]
    if others:
        groups.append({"name": "Other", "entries": others})
        assigned.update(e["key"] for e in others)

    hidden_keys = sorted(k for k in criteria if k not in assigned)
    return groups, hidden_keys


def _format_criterion_value(v: Any) -> str:
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) if v else "—"
    if v is None:
        return "—"
    return str(v)


def _strategy_affinity_from_output_tags(tags: list[str]) -> str:
    """Shorten tags to a human-readable affinity line for the list page."""
    if not tags:
        return ""
    # Drop ``_`` and title-case; cap at 3 for brevity.
    return " · ".join(t.replace("_", " ") for t in tags[:3])
