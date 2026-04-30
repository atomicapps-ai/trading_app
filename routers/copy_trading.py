"""copy_trading.py — Capitol Trades politician copy-trading routes.

Routes
------
GET  /copy-trading                          → dashboard page
GET  /api/copy-trading/config               → JSON: current config
POST /api/copy-trading/config               → update config (limits, enabled toggle)
GET  /api/copy-trading/followed             → JSON: all followed politicians
POST /api/copy-trading/follow               → add politician to followed list
DELETE /api/copy-trading/follow/{slug}      → remove politician
PATCH /api/copy-trading/follow/{slug}       → toggle enabled
GET  /api/copy-trading/politicians          → JSON: ranked politicians from recent CT trades
GET  /api/copy-trading/trades               → JSON: CT trades from DB (all or by politician)
POST /api/copy-trading/scan                 → manual trigger: fetch CT now, return summary
GET  /api/copy-trading/queue                → JSON: copy trade queue (recent DB records)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from services import db_service
from services.capitol_trades_service import CapitolTradesService
from services.senate_efd_service import SenateEFDService
from services.settings_service import TEMPLATES_DIR, Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)

_svc = CapitolTradesService()
_senate = SenateEFDService()

# How long Senate data can sit before we suggest a refresh
_SENATE_FRESHNESS_DAYS = 7

# --------------------------------------------------------------------------- #
# HTML page
# --------------------------------------------------------------------------- #


from fastapi.responses import RedirectResponse


@router.get("/copy-trading")
async def copy_trading_legacy_redirect():
    """Old URL — redirect to the new Politician Rankings page."""
    return RedirectResponse(url="/copy-insiders/rankings", status_code=307)


@router.get("/copy-insiders")
async def copy_insiders_index():
    """Section index — default child is Rankings."""
    return RedirectResponse(url="/copy-insiders/rankings", status_code=307)


@router.get("/copy-insiders/rankings", response_class=HTMLResponse)
async def politician_rankings_page(
    request: Request,
    s: Settings = Depends(get_settings),
) -> HTMLResponse:
    """Politician Rankings: leaderboard + follow + favorite + view-trades.

    Re-renders the most recently cached rankings server-side so the user
    doesn't have to click Reload again after an app restart.
    """
    import json as _json
    cfg = await db_service.get_all_copy_config()
    followed = await db_service.list_followed_politicians()
    cached_rankings = []
    cached_rankings_at = cfg.get("latest_rankings_at", "")
    raw = cfg.get("latest_rankings_json", "")
    if raw:
        try:
            cached_rankings = _json.loads(raw)
        except (ValueError, TypeError):
            cached_rankings = []
    return templates.TemplateResponse(
        request=request,
        name="copy_insiders/rankings.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "copy_insiders",
            "active_section": "copy_insiders",
            "tabs": _ci_tabs(),
            "active_tab": "rankings",
            "config": _enrich_config(cfg),
            "followed": followed,
            "cached_rankings": cached_rankings,
            "cached_rankings_at": cached_rankings_at,
        },
    )


def _ci_tabs() -> list[dict]:
    """Shared horizontal tabs for the Copy Insiders group of pages."""
    return [
        {"key": "rankings",    "label": "Rankings",    "href": "/copy-insiders/rankings", "count": None},
        {"key": "disclosures", "label": "Disclosures", "href": "/copy-insiders/trades",   "count": None},
    ]


@router.get("/copy-insiders/trades", response_class=HTMLResponse)
async def politician_trades_page(
    request: Request,
    s: Settings = Depends(get_settings),
) -> HTMLResponse:
    """Politician Trades: multi-select politicians, view their disclosures."""
    followed = await db_service.list_followed_politicians()
    return templates.TemplateResponse(
        request=request,
        name="copy_insiders/trades.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "copy_insiders",
            "active_section": "copy_insiders",
            "tabs": _ci_tabs(),
            "active_tab": "disclosures",
            "followed": followed,
        },
    )


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


class CopyConfigUpdate(BaseModel):
    max_per_trade_usd: float | None = None
    enabled: bool | None = None


class FollowRequest(BaseModel):
    slug: str
    name: str
    party: str = ""
    chamber: str = ""
    score: float = 0.0
    trade_count_90d: int = 0
    buy_ratio_pct: int = 0
    last_trade_date: str = ""


class FollowToggle(BaseModel):
    enabled: bool


@router.get("/api/copy-trading/config")
async def get_config() -> dict:
    cfg = await db_service.get_all_copy_config()
    return _enrich_config(cfg)


@router.post("/api/copy-trading/config")
async def update_config(body: CopyConfigUpdate) -> dict:
    if body.max_per_trade_usd is not None:
        await db_service.set_copy_config("max_per_trade_usd", str(body.max_per_trade_usd))
    if body.enabled is not None:
        await db_service.set_copy_config("enabled", "true" if body.enabled else "false")
    return {"ok": True, "config": _enrich_config(await db_service.get_all_copy_config())}


def _enrich_config(cfg: dict) -> dict:
    return {
        "max_per_trade_usd": float(cfg.get("max_per_trade_usd", "5000")),
        "enabled": cfg.get("enabled", "true") == "true",
        "last_scan_ts": cfg.get("last_scan_ts", ""),
        "last_scan_count": int(cfg.get("last_scan_count", "0")),
        "last_scan_total_fetched": cfg.get("last_scan_total_fetched", ""),
        "last_scan_error": cfg.get("last_scan_error", ""),
    }


# --------------------------------------------------------------------------- #
# Followed politicians
# --------------------------------------------------------------------------- #


@router.get("/api/copy-trading/followed")
async def list_followed() -> dict:
    rows = await db_service.list_followed_politicians()
    return {"ok": True, "politicians": rows}


async def _is_senator(slug: str) -> bool:
    """True if this slug appears in our cached Senate filings (vs a House member)."""
    rows = await db_service.list_senate_filings(senator_slug=slug, limit=1)
    return bool(rows)


async def _compute_and_save_performance(slug: str, name: str) -> None:
    """Background helper — compute performance for a politician (House or
    Senate) and persist to both followed_politicians and member_performance_cache."""
    try:
        if await _is_senator(slug):
            # Senate path: parse PTRs first, then compute via yfinance pipeline.
            # Reuses the /parse-senator endpoint logic via the helper service.
            perf_dict = await _senate.compute_senator_performance(slug, name)
            if not perf_dict:
                logger.warning("auto-compute senator %s: no perf returned", slug)
                return
            from services.capitol_trades_service import PoliticianPerformance
            perf = PoliticianPerformance(
                politician_slug=slug, politician_name=name,
                total_trades=perf_dict["total_trades"],
                win_rate_30d=perf_dict["win_rate_30d"],
                avg_return_30d=perf_dict["avg_return_30d"],
                avg_spy_return_30d=perf_dict["avg_spy_return_30d"],
            )
        else:
            perf = await _svc.fetch_politician_performance(slug, politician_name=name)
            if not perf:
                logger.warning("auto-compute %s: no perf returned", slug)
                return
        # Persist to followed_politicians (always — even when perf_trade_count=0,
        # so the UI knows we tried and there's no equity data to show)
        await db_service.update_followed_politician_performance(
            slug,
            win_rate_30d=perf.win_rate_30d,
            avg_return_30d=perf.avg_return_30d,
            avg_spy_return_30d=perf.avg_spy_return_30d,
            perf_trade_count=perf.total_trades,
        )
        # Also feed the dropdown's cache so this member's rank can be computed
        await db_service.upsert_member_performance(
            slug, name,
            win_rate_30d=perf.win_rate_30d,
            avg_return_30d=perf.avg_return_30d,
            avg_spy_return_30d=perf.avg_spy_return_30d,
            perf_trade_count=perf.total_trades,
        )
        logger.info("auto-compute %s: %d eligible trades, win=%s",
                    slug, perf.total_trades, perf.win_rate_30d)
    except Exception as exc:
        logger.warning("auto-compute %s failed: %s", slug, exc)


@router.post("/api/copy-trading/follow")
async def follow_politician(body: FollowRequest, background: BackgroundTasks) -> dict:
    await db_service.add_followed_politician(
        body.slug,
        body.name,
        party=body.party,
        chamber=body.chamber,
        score=body.score,
        trade_count_90d=body.trade_count_90d,
        buy_ratio_pct=body.buy_ratio_pct,
        last_trade_date=body.last_trade_date,
    )
    # Auto-compute performance in the background so the row populates
    # without the user having to click the ↻ button manually.
    background.add_task(_compute_and_save_performance, body.slug, body.name)
    return {"ok": True, "performance_compute_queued": True}


@router.delete("/api/copy-trading/follow/{slug}")
async def unfollow_politician(slug: str) -> dict:
    await db_service.remove_followed_politician(slug)
    return {"ok": True}


@router.patch("/api/copy-trading/follow/{slug}")
async def toggle_politician(slug: str, body: FollowToggle) -> dict:
    await db_service.toggle_followed_politician(slug, body.enabled)
    return {"ok": True}


class FavoriteToggle(BaseModel):
    is_favorite: bool


@router.patch("/api/copy-trading/favorite/{slug}")
async def toggle_favorite(slug: str, body: FavoriteToggle) -> dict:
    """Pin/unpin a followed politician — favorites sort to the top."""
    await db_service.toggle_followed_politician_favorite(slug, body.is_favorite)
    return {"ok": True, "is_favorite": body.is_favorite}


@router.get("/api/copy-trading/disclosures")
async def get_disclosures_for(slugs: str = "", limit: int = 200) -> dict:
    """Fetch disclosures for one or more politicians.

    `slugs` is a comma-separated list. Returns the union, sorted by
    transaction_date desc.
    """
    slug_list = [s.strip() for s in slugs.split(",") if s.strip()]
    if not slug_list:
        return {"ok": True, "trades": [], "by_politician": {}}

    # Fetch via the API for each politician (parallel)
    import asyncio
    results = await asyncio.gather(*[
        _svc.fetch_politician_trades(s, pages=4) for s in slug_list
    ])

    all_trades = []
    counts = {}
    for slug, trades in zip(slug_list, results):
        counts[slug] = len(trades)
        for t in trades:
            all_trades.append({
                "politician_slug": t.politician_slug,
                "politician_name": t.politician_name,
                "ticker": t.ticker,
                "asset_name": t.asset_name,
                "asset_type": t.asset_type,
                "transaction_type": t.transaction_type,
                "transaction_date": t.transaction_date,
                "published_date": t.published_date,
                "amount_min": t.amount_min,
                "amount_max": t.amount_max,
            })
    # Sort by transaction date desc, slice
    all_trades.sort(key=lambda x: x["transaction_date"], reverse=True)
    return {
        "ok": True,
        "trades": all_trades[:limit],
        "by_politician": counts,
        "total": len(all_trades),
    }


@router.post("/api/copy-trading/performance/{slug}")
async def compute_performance(slug: str) -> dict:
    """Compute & cache 30-day performance metrics for a followed politician.

    Routes to the right pipeline:
      - House members → ivanma9 API + yfinance (~5-15s)
      - Senators      → eFD HTML parse + yfinance (~15-30s, uses cached PTRs
                        when available; calls parse-senator first if not)
    """
    followed = await db_service.list_followed_politicians()
    target = next((p for p in followed if p["slug"] == slug), None)
    if not target:
        raise HTTPException(status_code=404, detail="not following that politician")

    # Senate path: if any Senate filings exist for this slug, treat as senator.
    if await _is_senator(slug):
        # Ensure trades are parsed first (no-op if already cached)
        result = await parse_senator(slug)
        perf_dict = result.get("performance") or {}
        from services.capitol_trades_service import PoliticianPerformance
        perf = PoliticianPerformance(
            politician_slug=slug,
            politician_name=target["name"],
            total_trades=perf_dict.get("total_trades", 0),
            win_rate_30d=perf_dict.get("win_rate_30d"),
            avg_return_30d=perf_dict.get("avg_return_30d"),
            avg_spy_return_30d=perf_dict.get("avg_spy_return_30d"),
        )
    else:
        perf = await _svc.fetch_politician_performance(slug, politician_name=target["name"])
        if not perf:
            raise HTTPException(status_code=502, detail="performance computation failed")

    await db_service.update_followed_politician_performance(
        slug,
        win_rate_30d=perf.win_rate_30d,
        avg_return_30d=perf.avg_return_30d,
        avg_spy_return_30d=perf.avg_spy_return_30d,
        perf_trade_count=perf.total_trades,
    )
    return {
        "ok": True,
        "slug": slug,
        "name": perf.politician_name,
        "trade_count": perf.total_trades,
        "win_rate_30d": perf.win_rate_30d,
        "avg_return_30d": perf.avg_return_30d,
        "avg_spy_return_30d": perf.avg_spy_return_30d,
    }


# --------------------------------------------------------------------------- #
# Politicians ranking
# --------------------------------------------------------------------------- #


@router.get("/api/copy-trading/all-members")
async def get_all_members() -> dict:
    """Full alphabetical list of available politicians (House + Senate) for the
    add-politician dropdown, enriched with cached performance + composite rank.

    House members: live from ivanma9 API + win-rate from yfinance computation.
    Senate members: from cached eFD filings (PDF parsing not yet implemented,
    so Senate rows have filing counts but no win-rate yet).
    """
    members = await _svc.fetch_ranked_members(limit=500)
    perf_cache = await db_service.get_member_performance_cache_map()
    rank_map = _compute_composite_ranks(members, perf_cache)

    # House (existing)
    out: list[dict] = []
    for p in members:
        out.append({
            "slug": p.politician_slug,
            "name": p.politician_name,
            "chamber": "House",
            "state": p.state,
            "district": p.district,
            "trade_count_90d": p.trade_count_90d,
            "last_trade_date": p.last_trade_date,
            "win_rate_30d": (perf_cache.get(p.politician_slug) or {}).get("win_rate_30d"),
            "avg_return_30d": (perf_cache.get(p.politician_slug) or {}).get("avg_return_30d"),
            "perf_trade_count": (perf_cache.get(p.politician_slug) or {}).get("perf_trade_count"),
            "perf_computed_at": (perf_cache.get(p.politician_slug) or {}).get("computed_at"),
            "composite_rank": rank_map.get(p.politician_slug),
        })

    # Senate (cached from eFD; no win-rate yet — PDF parsing is Phase 2)
    senate_filings = await db_service.list_senate_filings(limit=2000)
    if senate_filings:
        # Adapt the DB rows into pseudo-PoliticianScore dicts for aggregation
        from datetime import date as _date, timedelta as _td
        today = _date.today()
        cutoff_90 = (today - _td(days=90)).isoformat()
        from collections import defaultdict
        agg: dict[str, dict] = defaultdict(lambda: {"name": "", "filings": []})
        for f in senate_filings:
            d = agg[f["senator_slug"]]
            d["name"] = f["senator_name"]
            d["filings"].append(f)
        for slug, d in agg.items():
            filings = sorted(d["filings"], key=lambda x: x["filing_date"], reverse=True)
            last_date = filings[0]["filing_date"] if filings else ""
            count_90 = sum(1 for f in filings if f["filing_date"] >= cutoff_90)
            try:
                from datetime import datetime as _dt
                days_ago = max(0, (today - _dt.fromisoformat(last_date).date()).days)
            except (ValueError, TypeError):
                days_ago = 999
            out.append({
                "slug": slug,
                "name": d["name"],
                "chamber": "Senate",
                "state": "",
                "district": "",
                "trade_count_90d": count_90,  # Filings, not trades
                "last_trade_date": last_date,
                "win_rate_30d": None,
                "avg_return_30d": None,
                "perf_trade_count": None,
                "perf_computed_at": None,
                "composite_rank": None,
                "days_since_last_filing": days_ago,
                "filing_count_total": len(filings),
            })

    out.sort(key=lambda x: x["name"].lower())

    # Senate freshness signal for the UI banner. The auto-diff job runs
    # daily (services.scheduler._senate_diff_job) and bumps
    # senate_new_filings_count whenever it finds PTR ids not yet in the
    # cache. The count is reset by the manual Refresh Senate button.
    cfg = await db_service.get_all_copy_config()
    last_refresh = cfg.get("senate_last_refresh_at", "")
    last_diff = cfg.get("senate_last_diff_at", "")
    new_count = int(cfg.get("senate_new_filings_count", "0") or 0)
    needs_refresh = _senate_needs_refresh(last_refresh)

    return {
        "ok": True,
        "members": out,
        "senate_last_refresh_at": last_refresh,
        "senate_last_diff_at": last_diff,
        "senate_new_filings_count": new_count,
        "senate_needs_refresh": needs_refresh,
        "senate_count": sum(1 for m in out if m["chamber"] == "Senate"),
        "house_count": sum(1 for m in out if m["chamber"] == "House"),
    }


def _senate_needs_refresh(last_refresh_iso: str) -> bool:
    """True if Senate data is older than _SENATE_FRESHNESS_DAYS or missing."""
    if not last_refresh_iso:
        return True
    try:
        last = datetime.fromisoformat(last_refresh_iso)
        age = datetime.now(timezone.utc) - last
        return age.days >= _SENATE_FRESHNESS_DAYS
    except ValueError:
        return True


@router.post("/api/copy-trading/parse-senator/{slug}")
async def parse_senator(slug: str) -> dict:
    """On-demand: pull every uncached PTR for this senator, parse the HTML
    table into senate_trades, then compute win-rate via yfinance.

    Slow (~5-30s depending on # of PTRs and equity trades to look up).
    Caches results so a second call is fast.
    """
    # Find this senator's filings in the cache
    filings = await db_service.list_senate_filings(senator_slug=slug)
    if not filings:
        raise HTTPException(404, detail=f"no cached filings for senator '{slug}' — run Refresh Senate first")

    # Skip PTRs we've already parsed (de-dup work)
    parsed_ids = await db_service.get_parsed_ptr_ids()
    todo = [f for f in filings if f["ptr_id"] not in parsed_ids]

    senator_name = filings[0]["senator_name"]
    parsed_count = 0
    if todo:
        # Reuse one session across all PTR fetches for efficiency
        client, _csrf = await _senate._new_session()
        try:
            for f in todo:
                trades = await _senate.fetch_ptr_trades(f["ptr_id"], client=client)
                if not trades:
                    continue
                rows = [{
                    "ptr_id": t.ptr_id, "row_num": t.row_num,
                    "senator_slug": slug, "senator_name": senator_name,
                    "transaction_date": t.transaction_date, "owner": t.owner,
                    "ticker": t.ticker, "asset_name": t.asset_name,
                    "asset_type": t.asset_type,
                    "transaction_type": t.transaction_type,
                    "amount_min": t.amount_min, "amount_max": t.amount_max,
                    "comment": t.comment,
                } for t in trades]
                await db_service.upsert_senate_trades(rows)
                parsed_count += len(rows)
        finally:
            await client.aclose()

    # Compute performance from the now-cached trades
    perf = await _senate.compute_senator_performance(slug, senator_name)
    if not perf:
        return {"ok": True, "parsed": parsed_count, "performance": None}

    # Cache the result so the dropdown/leaderboard can show it
    await db_service.upsert_member_performance(
        slug, senator_name,
        win_rate_30d=perf["win_rate_30d"],
        avg_return_30d=perf["avg_return_30d"],
        avg_spy_return_30d=perf["avg_spy_return_30d"],
        perf_trade_count=perf["total_trades"],
    )
    # If they're already followed, also update followed_politicians row
    followed = await db_service.list_followed_politicians()
    if any(p["slug"] == slug for p in followed):
        await db_service.update_followed_politician_performance(
            slug,
            win_rate_30d=perf["win_rate_30d"],
            avg_return_30d=perf["avg_return_30d"],
            avg_spy_return_30d=perf["avg_spy_return_30d"],
            perf_trade_count=perf["total_trades"],
        )

    return {
        "ok": True,
        "slug": slug,
        "name": senator_name,
        "ptrs_parsed_now": len(todo),
        "trades_parsed_now": parsed_count,
        "performance": perf,
    }


@router.post("/api/copy-trading/refresh-senate")
async def refresh_senate(days_back: int = 365) -> dict:
    """Hit efdsearch.senate.gov, pull all PTR filings in the window, cache new
    ones to senate_filings. Returns counts of new vs already-known filings."""
    try:
        filings = await _senate.fetch_ptr_filings(days_back=days_back, page_size=100, max_pages=20)
    except Exception as exc:
        logger.exception("refresh_senate fetch failed")
        raise HTTPException(502, detail=f"eFD fetch failed: {exc}")

    # Convert dataclasses to dicts for the DB call
    from dataclasses import asdict
    filing_dicts = []
    for f in filings:
        d = asdict(f)
        d["senator_slug"] = _slug_from_name(f.senator_name)
        filing_dicts.append(d)

    # True new count via PTR-id diff (the upsert's own counter is unreliable
    # because SQLite returns rowcount=1 for both INSERT and ON CONFLICT UPDATE).
    fetched_ids = {f.ptr_id for f in filings}
    known_ids = await db_service.get_known_senate_ptr_ids()
    new_in_this_refresh = len(fetched_ids - known_ids)

    counts = await db_service.upsert_senate_filings(filing_dicts)
    now = datetime.now(timezone.utc).isoformat()
    await db_service.set_copy_config("senate_last_refresh_at", now)
    # Manual refresh acknowledges all new filings — reset the counter and clear errors
    await db_service.set_copy_config("senate_new_filings_count", "0")
    await db_service.set_copy_config("senate_last_diff_error", "")
    return {
        "ok": True,
        "fetched": len(filings),
        "new_filings": new_in_this_refresh,
        "updated_filings": counts["updated"],
        "senate_last_refresh_at": now,
        "unique_senators": len({f["senator_slug"] for f in filing_dicts}),
    }


def _slug_from_name(name: str) -> str:
    out = []
    for ch in (name or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")


def _compute_composite_ranks(members, perf_cache: dict) -> dict[str, int]:
    """Return {slug: rank_1_to_10} using percentile-then-weight across the
    cohort of members that have computed performance + at least one equity trade."""
    rows = []
    for m in members:
        perf = perf_cache.get(m.politician_slug) or {}
        n = perf.get("perf_trade_count") or 0
        wr = perf.get("win_rate_30d")
        ret = perf.get("avg_return_30d")
        # Skip members with no usable performance data
        if n <= 0 or wr is None or ret is None:
            continue
        rows.append({
            "slug": m.politician_slug,
            "trades": m.trade_count_90d or 0,
            "win": wr,
            "ret": ret,
        })
    if len(rows) < 2:
        # Need at least 2 to rank against each other
        return {}

    def percentile(values: list[float]) -> dict[float, float]:
        """Map raw value -> percentile (0-1) via rank-then-normalize."""
        sorted_vals = sorted(set(values))
        denom = max(1, len(sorted_vals) - 1)
        return {v: i / denom for i, v in enumerate(sorted_vals)}

    p_trades = percentile([r["trades"] for r in rows])
    p_win    = percentile([r["win"]    for r in rows])
    p_ret    = percentile([r["ret"]    for r in rows])

    out: dict[str, int] = {}
    for r in rows:
        composite = (
            0.25 * p_trades[r["trades"]]
            + 0.40 * p_win[r["win"]]
            + 0.35 * p_ret[r["ret"]]
        )
        # Bin into 1..10 (composite is 0..1)
        decile = max(1, min(10, int(round(composite * 9)) + 1))
        out[r["slug"]] = decile
    return out


@router.post("/api/copy-trading/compute-all-performance")
async def compute_all_performance(force: bool = False, limit: int = 100) -> dict:
    """Bulk-compute performance metrics for the dropdown.

    Iterates House + Senate members and runs the local yfinance computation
    for each. Senators are routed through the eFD HTML parse pipeline; House
    members go through the ivanma9 API. Skips members already in the cache
    unless `force=true`. Slow (~5-30s per member).
    """
    house_members = await _svc.fetch_ranked_members(limit=500)
    cache = await db_service.get_member_performance_cache_map()

    # Senate members come from the cached filings table — anyone we've seen a
    # PTR for is a candidate for performance computation.
    senate_filings = await db_service.list_senate_filings(limit=2000)
    senate_targets: dict[str, str] = {}
    for f in senate_filings:
        senate_targets.setdefault(f["senator_slug"], f["senator_name"])

    house_todo = [m for m in house_members if force or m.politician_slug not in cache]
    senate_todo = [(s, n) for s, n in senate_targets.items() if force or s not in cache]
    todo_total = house_todo + [("__senate__", s, n) for s, n in senate_todo]
    todo_total = todo_total[:limit]

    computed = 0
    skipped = 0
    failed = 0

    # House first
    for m in [t for t in todo_total if not (isinstance(t, tuple) and t[0] == "__senate__")]:
        try:
            perf = await _svc.fetch_politician_performance(
                m.politician_slug, politician_name=m.politician_name,
            )
            if perf is None:
                failed += 1
                continue
            if perf.total_trades == 0:
                await db_service.upsert_member_performance(
                    m.politician_slug, m.politician_name,
                    win_rate_30d=None, avg_return_30d=None,
                    avg_spy_return_30d=None, perf_trade_count=0,
                )
                skipped += 1
                continue
            await db_service.upsert_member_performance(
                m.politician_slug, m.politician_name,
                win_rate_30d=perf.win_rate_30d,
                avg_return_30d=perf.avg_return_30d,
                avg_spy_return_30d=perf.avg_spy_return_30d,
                perf_trade_count=perf.total_trades,
            )
            computed += 1
        except Exception as exc:
            logger.warning("compute_all_performance house(%s) failed: %s", m.politician_slug, exc)
            failed += 1

    # Then Senate — uses parse_senator which does PTR HTML parse + cache + compute
    for marker in [t for t in todo_total if isinstance(t, tuple) and t[0] == "__senate__"]:
        _, slug, name = marker
        try:
            res = await parse_senator(slug)
            perf = res.get("performance") or {}
            n = perf.get("total_trades", 0)
            if n == 0:
                await db_service.upsert_member_performance(
                    slug, name,
                    win_rate_30d=None, avg_return_30d=None,
                    avg_spy_return_30d=None, perf_trade_count=0,
                )
                skipped += 1
            else:
                # parse_senator already cached via member_performance_cache; just count
                computed += 1
        except Exception as exc:
            logger.warning("compute_all_performance senate(%s) failed: %s", slug, exc)
            failed += 1

    return {
        "ok": True,
        "computed": computed,
        "skipped_no_eligible_trades": skipped,
        "failed": failed,
        "total_house": len(house_members),
        "total_senate": len(senate_targets),
        "remaining_uncached": max(
            0,
            (len(house_members) + len(senate_targets)) - len(cache) - computed - skipped,
        ),
    }


@router.get("/api/copy-trading/politicians")
async def get_politicians(pages: int = 5) -> dict:
    """Fetch ranked politicians (most active over last 90 days).

    Caches the result in copy_trading_config so the rankings page can
    re-render the last successful pull on next visit (or after restart)
    without making the user click Reload again.
    """
    import json as _json
    try:
        ranked = await _svc.fetch_ranked_members(limit=50)
        politicians = [
            {
                "name": p.politician_name,
                "slug": p.politician_slug,
                "party": p.party,
                "chamber": p.chamber,
                "state": p.state,
                "district": p.district,
                "trade_count_90d": p.trade_count_90d,
                "last_trade_date": p.last_trade_date,
                "days_since_last_trade": p.days_since_last_trade,
                "unique_tickers": p.unique_tickers,
                "buy_ratio_pct": round(p.buy_ratio * 100, 0),
                "score": p.score,
            }
            for p in ranked
        ]
        cached_at = datetime.now(timezone.utc).isoformat()
        await db_service.set_copy_config("latest_rankings_json", _json.dumps(politicians))
        await db_service.set_copy_config("latest_rankings_at", cached_at)
        return {
            "ok": True,
            "total_trades_fetched": sum(p.trade_count_90d for p in ranked),
            "politicians": politicians,
            "cached_at": cached_at,
        }
    except Exception as exc:
        logger.exception("get_politicians failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Capitol Trades fetch failed: {exc}")


# --------------------------------------------------------------------------- #
# Recent trades feed
# --------------------------------------------------------------------------- #


@router.get("/api/copy-trading/trades")
async def get_politician_trades(politician_slug: str | None = None, limit: int = 50) -> dict:
    """Return trades from DB — optionally filtered by politician slug."""
    rows = await db_service.list_politician_trades(politician_slug=politician_slug or None, limit=limit)
    return {"ok": True, "trades": rows}


# --------------------------------------------------------------------------- #
# Manual scan trigger
# --------------------------------------------------------------------------- #


@router.post("/api/copy-trading/scan")
async def manual_scan(s: Settings = Depends(get_settings)) -> dict:
    """Fetch Capitol Trades right now and process any new trades."""
    from services.scheduler import _poll_capitol_trades_job

    try:
        await _poll_capitol_trades_job()
        cfg = await db_service.get_all_copy_config()
        return {
            "ok": True,
            "last_scan_ts": cfg.get("last_scan_ts", ""),
            "last_scan_count": int(cfg.get("last_scan_count", "0")),
            "error": cfg.get("last_scan_error", ""),
        }
    except Exception as exc:
        logger.exception("manual_scan failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# --------------------------------------------------------------------------- #
# Copy queue
# --------------------------------------------------------------------------- #


@router.get("/api/copy-trading/queue")
async def get_copy_queue(limit: int = 100) -> dict:
    """All politician trades we've seen with their copy status."""
    rows = await db_service.list_politician_trades(limit=limit)
    return {"ok": True, "trades": rows}
