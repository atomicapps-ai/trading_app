"""universe_service.py — preset + history operations for the /universe UI.

Responsibilities
----------------
1. Load the Finviz filter catalog from ``services/finviz_catalog.json``.
2. Enumerate presets from SQLite (primary) or YAML (legacy read-only).
3. CRUD for SQLite-backed presets: create / update / delete / set-active.
4. Test-run: scrape Finviz with given filters, return ticker list without persisting.
5. Save tickers: persist ticker list to SQLite + write back to YAML for pipeline compat.
6. Archive snapshots on every write.
"""
from __future__ import annotations

import json
import logging
import re
import time
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from bs4 import BeautifulSoup

from services.settings_service import (
    DATA_DIR,
    PROJECT_ROOT,
    UniverseUISettings,
    get_settings,
)

logger = logging.getLogger(__name__)

CRITERIA_FILE: Path = PROJECT_ROOT / "universe_filter_presets.yaml"
TICKERS_FILE: Path = PROJECT_ROOT / "universe_filter_presets_tickers.yaml"
# Authoritative backup of every screener row in SQLite. This is the
# git-tracked source of truth — mutations re-write this file so a fresh
# checkout (or DB loss) can replay the entire screener registry.
SCREENERS_FILE: Path = PROJECT_ROOT / "universe_screeners.yaml"
LATEST_RESULT_FILE: Path = DATA_DIR / "universe_latest.json"
HISTORY_DIR: Path = DATA_DIR / "universe_history"
CATALOG_FILE: Path = Path(__file__).parent / "finviz_catalog.json"
FILTER_CONFIG_FILE: Path = PROJECT_ROOT / "universe_filter_config.yaml"

NON_REFRESH_PRESETS = {"sentiment_catalyst", "etf_sector_rotation"}

FINVIZ_BASE = "https://finviz.com/screener.ashx"
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
# Finviz quietly migrated their ticker links from `quote.ashx?t=SYMBOL`
# to `quote?t=SYMBOL` (dropped the .ashx extension). The .ashx form
# returned zero matches starting around 2026-04 and the screener page
# now uses the bare path. We accept either so the parser stays robust
# if Finviz ever rolls back. Anchored to a query-string boundary so
# we don't match unrelated `quote` substrings.
_TICKER_HREF_RE = re.compile(r"quote(?:\.ashx)?\?t=([A-Z][A-Z0-9\.\-]{0,9})")


# ---------------------------------------------------------------------- #
# Finviz catalog
# ---------------------------------------------------------------------- #


_catalog_cache: dict | None = None


def load_finviz_catalog() -> dict:
    """Return the full catalog dict (cached after first load)."""
    global _catalog_cache
    if _catalog_cache is None:
        if not CATALOG_FILE.exists():
            logger.warning("finviz_catalog.json not found at %s", CATALOG_FILE)
            _catalog_cache = {"filters": [], "total": 0}
        else:
            _catalog_cache = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    return _catalog_cache


def get_catalog_grouped() -> list[dict]:
    """Return filters organised as [{tab, categories: [{name, filters: [...]}]}]."""
    catalog = load_finviz_catalog()
    tree: dict[str, dict[str, list]] = {}
    for f in catalog.get("filters", []):
        tree.setdefault(f["tab"], {}).setdefault(f["category"], []).append(f)
    tab_order = ["Descriptive", "Fundamental", "Technical"]
    return [
        {
            "tab": tab,
            "categories": [
                {"name": cat, "filters": flist}
                for cat, flist in tree[tab].items()
            ],
        }
        for tab in tab_order
        if tab in tree
    ]


def get_catalog_flat() -> dict[str, dict]:
    """Return {filter_id: filter_dict} for fast lookup."""
    return {f["id"]: f for f in load_finviz_catalog().get("filters", [])}


def load_filter_config() -> list[str]:
    """Return the ordered list of default-visible filter IDs from the config file."""
    if not FILTER_CONFIG_FILE.exists():
        return []
    raw = yaml.safe_load(FILTER_CONFIG_FILE.read_text(encoding="utf-8")) or {}
    return [entry["id"] for entry in (raw.get("default_visible") or [])]


# ---------------------------------------------------------------------- #
# SQLite-backed preset CRUD (wrappers over db_service)
# ---------------------------------------------------------------------- #


async def seed_from_yaml_if_empty() -> None:
    """On first startup, populate SQLite presets from YAML criteria file."""
    from services import db_service
    docs = _load_criteria_docs()
    if not docs:
        return
    yaml_presets = [
        {
            "name": name,
            "description": doc.get("description", ""),
            "output_tags": doc.get("output_tags") or [],
            "notes": doc.get("notes", ""),
        }
        for name, doc in docs.items()
    ]
    inserted = await db_service.seed_universe_presets_from_yaml(yaml_presets)
    if inserted:
        logger.info("universe_service: seeded %d presets from YAML", inserted)


# --------------------------------------------------------------------------- #
# Screener backup — git-tracked YAML reflects DB state
# --------------------------------------------------------------------------- #
# The DB row is the source of truth at runtime, but the DB file is
# gitignored — losing it loses every screener. The functions below mirror
# the DB to ``universe_screeners.yaml`` after every mutation, so the
# committed YAML is always current. On a fresh checkout (or after a DB
# loss), ``import_screeners_from_yaml()`` recreates rows that are present
# in the YAML but absent from the DB. It NEVER overwrites existing DB
# rows — auto-import is purely additive.


async def export_screeners_to_yaml() -> int:
    """Write every DB screener row to SCREENERS_FILE. Returns count.

    Best-effort: any error is logged and swallowed so the mutation that
    triggered the export never fails because of a write hiccup.
    """
    from services import db_service
    try:
        rows = await db_service.list_universe_presets()
    except Exception as exc:                                          # noqa: BLE001
        logger.warning("export_screeners_to_yaml: list failed: %s", exc)
        return 0

    payload = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "screeners": [
            {
                "name":         r.get("name"),
                "title":        r.get("title") or "",
                "description":  r.get("description") or "",
                "notes":        r.get("notes") or "",
                "is_active":    bool(r.get("is_active")),
                "filters":      r.get("filters") or {},
                "output_tags":  r.get("output_tags") or [],
                "tickers":      r.get("tickers") or [],
                "tickers_refreshed_at": r.get("tickers_refreshed_at"),
                "updated_at":   r.get("updated_at"),
            }
            for r in rows
        ],
    }
    try:
        SCREENERS_FILE.write_text(
            yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
    except Exception as exc:                                          # noqa: BLE001
        logger.warning("export_screeners_to_yaml: write failed: %s", exc)
        return 0
    logger.info("export_screeners_to_yaml: wrote %d screener(s) to %s",
                len(rows), SCREENERS_FILE.name)
    return len(rows)


async def import_screeners_from_yaml() -> int:
    """Read SCREENERS_FILE and create any rows missing from the DB.

    Additive only — never overwrites an existing row. Returns the count
    of rows newly created. Run from app lifespan so a fresh checkout
    (or rebuilt DB) restores the screener registry automatically.
    """
    if not SCREENERS_FILE.exists():
        return 0
    from services import db_service
    try:
        payload = yaml.safe_load(SCREENERS_FILE.read_text(encoding="utf-8")) or {}
    except Exception as exc:                                          # noqa: BLE001
        logger.warning("import_screeners_from_yaml: parse failed: %s", exc)
        return 0

    existing = {r.get("name") for r in await db_service.list_universe_presets()}
    created = 0
    active_to_set: str | None = None
    for s in payload.get("screeners") or []:
        name = (s or {}).get("name")
        if not name or name in existing:
            continue
        try:
            await db_service.create_universe_preset(
                name=name,
                title=s.get("title") or "",
                description=s.get("description") or "",
                notes=s.get("notes") or "",
                filters=s.get("filters") or {},
                output_tags=s.get("output_tags") or [],
            )
            tickers = s.get("tickers") or []
            if tickers:
                await db_service.save_universe_preset_tickers(
                    name=name, tickers=tickers,
                    source="restore:universe_screeners.yaml",
                )
            if s.get("is_active") and active_to_set is None:
                active_to_set = name
            created += 1
            logger.info(
                "import_screeners_from_yaml: restored %s with %d tickers",
                name, len(tickers),
            )
        except Exception as exc:                                      # noqa: BLE001
            logger.warning("import: %s failed: %s", name, exc)

    # Restore "active" flag last, since each create() doesn't set it.
    if active_to_set:
        try:
            await db_service.set_active_universe_preset(active_to_set)
        except Exception as exc:                                      # noqa: BLE001
            logger.warning("import: set_active(%s) failed: %s",
                           active_to_set, exc)

    if created:
        logger.warning(
            "Restored %d screener(s) from %s on boot",
            created, SCREENERS_FILE.name,
        )
    return created


async def list_presets_db() -> list[dict]:
    from services import db_service
    return await db_service.list_universe_presets()


async def get_preset_db(name: str) -> dict | None:
    from services import db_service
    return await db_service.get_universe_preset(name)


async def get_core_universe() -> dict | None:
    """The master 'core' universe — the base pool strategies filter from."""
    from services import db_service
    return await db_service.get_core_universe_preset()


async def set_core_universe(name: str) -> bool:
    from services import db_service
    ok = await db_service.set_core_universe_preset(name)
    if ok:
        await export_screeners_to_yaml()
    return ok


async def set_manual_lists(
    name: str,
    *,
    manual_includes: list[str] | None = None,
    manual_excludes: list[str] | None = None,
) -> bool:
    from services import db_service
    ok = await db_service.set_universe_manual_lists(
        name, manual_includes=manual_includes, manual_excludes=manual_excludes,
    )
    if ok:
        await export_screeners_to_yaml()
    return ok


async def create_preset_db(
    *,
    name: str,
    title: str = "",
    description: str = "",
    filters: dict | None = None,
    output_tags: list[str] | None = None,
    notes: str = "",
) -> int:
    from services import db_service
    rid = await db_service.create_universe_preset(
        name=name, title=title, description=description,
        filters=filters, output_tags=output_tags, notes=notes,
    )
    await export_screeners_to_yaml()
    return rid


async def update_preset_db(
    name: str,
    *,
    title: str | None = None,
    description: str | None = None,
    filters: dict | None = None,
    output_tags: list[str] | None = None,
    notes: str | None = None,
) -> bool:
    from services import db_service
    ok = await db_service.update_universe_preset(
        name, title=title, description=description, filters=filters,
        output_tags=output_tags, notes=notes,
    )
    if ok:
        await export_screeners_to_yaml()
    return ok


async def delete_preset_db(name: str) -> bool:
    from services import db_service
    ok = await db_service.delete_universe_preset(name)
    if ok:
        await export_screeners_to_yaml()
    return ok


async def set_active_preset_db(name: str) -> bool:
    from services import db_service
    ok = await db_service.set_active_universe_preset(name)
    if ok:
        await export_screeners_to_yaml()
    return ok


async def save_preset_tickers_db(
    name: str, tickers: list[str], source: str,
) -> bool:
    """Persist tickers to SQLite, write back to the legacy YAML tickers
    file, and refresh the authoritative screeners YAML backup."""
    from services import db_service
    ok = await db_service.save_universe_preset_tickers(name, tickers, source)
    if ok:
        _sync_tickers_to_yaml(name, tickers, source)
        await export_screeners_to_yaml()
    return ok


def _sync_tickers_to_yaml(name: str, tickers: list[str], source: str) -> None:
    """Write tickers back to the YAML file so the pipeline can still read it."""
    try:
        data: dict = {}
        if TICKERS_FILE.exists():
            data = yaml.safe_load(TICKERS_FILE.read_text(encoding="utf-8")) or {}
        data.setdefault("presets", {})[name] = {
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "tickers": tickers,
        }
        TICKERS_FILE.write_text(
            yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        logger.info("universe_service: synced %d tickers → YAML for %s", len(tickers), name)
    except Exception as e:  # noqa: BLE001
        logger.warning("universe_service: YAML sync failed for %s: %s", name, e)


# ---------------------------------------------------------------------- #
# Finviz test-run scraping
# ---------------------------------------------------------------------- #


def scrape_finviz_filters(
    filters: dict[str, str],
    *,
    max_pages: int = 50,
    delay_seconds: float = 1.5,
) -> tuple[list[str], bool]:
    """Scrape Finviz with {filter_id: option_value} dict.

    Returns ``(tickers, truncated)`` where ``truncated`` is True if we hit
    ``max_pages`` while the last page was still full — i.e. more results
    exist beyond the cap. Non-destructive — does NOT write to any file.
    """
    tokens = [f"{fid}_{val}" for fid, val in filters.items() if val]
    filter_str = ",".join(tokens)
    session = requests.Session()
    session.headers.update({"User-Agent": _DEFAULT_UA})
    tickers: list[str] = []
    seen: set[str] = set()
    truncated = False

    for page in range(max_pages):
        row_offset = page * 20 + 1
        params: dict[str, str] = {"v": "111", "r": str(row_offset)}
        if filter_str:
            params["f"] = filter_str
        try:
            resp = _get_with_backoff(session, FINVIZ_BASE, params)
        except RuntimeError as e:
            logger.warning("scrape_finviz_filters: %s", e)
            break
        page_tickers = _parse_tickers(resp)
        if not page_tickers:
            break
        for t in page_tickers:
            if t not in seen:
                seen.add(t)
                tickers.append(t)
        if len(page_tickers) < 20:
            break
        if page == max_pages - 1:
            # Last allowed page was still full → more results exist
            truncated = True
            break
        time.sleep(delay_seconds)

    return tickers, truncated


def _get_with_backoff(session: requests.Session, url: str, params: dict) -> str:
    for attempt in range(4):
        resp = session.get(url, params=params, timeout=20)
        if resp.status_code == 200:
            return resp.text
        if resp.status_code in (429, 503):
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
    raise RuntimeError(f"Finviz GET failed after 4 attempts")


def _parse_tickers(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_=lambda c: bool(c) and "screener_table" in c)
    if table is None:
        return []
    tickers: list[str] = []
    seen: set[str] = set()
    for a in table.find_all("a", href=True):
        m = _TICKER_HREF_RE.search(a["href"])
        if not m:
            continue
        sym = m.group(1).upper()
        if sym not in seen:
            seen.add(sym)
            tickers.append(sym)
    return tickers


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
