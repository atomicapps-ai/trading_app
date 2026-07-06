"""APScheduler service — Phase 4 remaining item + Capitol Trades polling.

Two categories of jobs:

  1. Workflow jobs — read the ``schedule:`` cron field from each
     workflow YAML (morning_run, evening_run, research_run) and fire
     ``pipeline_service.run_workflow_by_id()`` on schedule.

  2. Copy-trading poll — every 30 minutes during market hours (Mon–Fri
     08:30–17:00 ET), fetch Capitol Trades for new disclosures from the
     monitored politician and queue copy-trade plans.

APScheduler's AsyncIOScheduler runs in the same event loop as FastAPI,
so jobs that ``await`` async functions work correctly.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


# --------------------------------------------------------------------------- #
# Scheduler lifecycle
# --------------------------------------------------------------------------- #


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="America/New_York")
    return _scheduler


def start_scheduler() -> None:
    """Register all jobs and start the scheduler.

    Safe to call multiple times — skips if already running.
    """
    sched = get_scheduler()
    if sched.running:
        return

    _register_copy_trading_jobs(sched)
    _register_senate_diff_job(sched)
    _register_workflow_jobs(sched)
    _register_daily_digest_job(sched)
    _register_gateway_watchdog_job(sched)
    _register_candle_refresh_jobs(sched)

    sched.start()
    logger.info("Scheduler started — %d jobs registered", len(sched.get_jobs()))

    # Catch up missed runs from earlier today. APScheduler doesn't replay
    # cron triggers across restarts — if the app was stopped at 16:15 ET
    # while the wf_momentum_breakout_scan job was supposed to fire, that day
    # is silently skipped on every subsequent restart. We don't want that.
    import asyncio as _asyncio
    try:
        _asyncio.create_task(_catch_up_missed_runs(sched))
    except Exception as exc:                                      # noqa: BLE001
        logger.warning("catch-up scheduling failed: %s", exc)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    _scheduler = None


# --------------------------------------------------------------------------- #
# Job: broker gateway watchdog (unattended resilience)
# --------------------------------------------------------------------------- #


def _register_gateway_watchdog_job(sched: AsyncIOScheduler) -> None:
    """Poll the broker connection so an IBKR gateway that dies while the
    operator is away is detected, auto-reconnected, and — on a real outage —
    pushed to their phone via ntfy. No-ops in research mode."""
    from services.gateway_watchdog import CHECK_INTERVAL_MINUTES
    sched.add_job(
        _gateway_watchdog_job,
        IntervalTrigger(minutes=CHECK_INTERVAL_MINUTES),
        id="gateway_watchdog",
        name="Broker gateway watchdog",
        replace_existing=True,
        misfire_grace_time=60,
        coalesce=True,          # a backlog of missed ticks collapses to one
        max_instances=1,        # never overlap two health checks
    )
    logger.info("Registered gateway watchdog (every %d min)", CHECK_INTERVAL_MINUTES)


async def _gateway_watchdog_job() -> None:
    from services.gateway_watchdog import check_gateway_health
    try:
        await check_gateway_health()
    except Exception as exc:  # noqa: BLE001 — a watchdog must never crash the loop
        logger.warning("gateway_watchdog job raised: %s", exc)


# --------------------------------------------------------------------------- #
# Job: candle-cache refresh (keep bar history current)
# --------------------------------------------------------------------------- #

def _register_candle_refresh_jobs(sched: AsyncIOScheduler) -> None:
    """Keep the bar cache current with two cheap top-up jobs:

      • daily — after the US close, refresh 1d bars for the whole active
        universe (one pass, appends the new session's daily bar).
      • intraday — during market hours, every N minutes, refresh the
        intraday bars (30m/15m/5m) for just the symbols that matter now:
        the pending queue, open positions, and the FX set.

    Disable with CANDLE_REFRESH_ENABLED=0. Tunables:
        CANDLE_REFRESH_INTRADAY_MIN   (default 20)
        CANDLE_REFRESH_DAILY_CRON     (default "35 16 * * 1-5", ET)
        CANDLE_REFRESH_DAILY_SOURCE   (default "yfinance")
    """
    import os
    if os.getenv("CANDLE_REFRESH_ENABLED", "1") not in ("1", "true", "True"):
        logger.info("Candle refresh disabled (CANDLE_REFRESH_ENABLED=0)")
        return

    daily_cron = os.getenv("CANDLE_REFRESH_DAILY_CRON", "35 16 * * 1-5")
    intraday_min = int(os.getenv("CANDLE_REFRESH_INTRADAY_MIN", "20"))

    sched.add_job(
        _candle_refresh_daily_job,
        CronTrigger.from_crontab(daily_cron, timezone="America/New_York"),
        id="candle_refresh_daily",
        name="Candle refresh — daily universe",
        replace_existing=True, misfire_grace_time=3600, coalesce=True, max_instances=1,
    )
    sched.add_job(
        _candle_refresh_intraday_job,
        IntervalTrigger(minutes=intraday_min),
        id="candle_refresh_intraday",
        name="Candle refresh — intraday watchlist",
        replace_existing=True, misfire_grace_time=120, coalesce=True, max_instances=1,
    )
    logger.info("Registered candle refresh (daily cron %r, intraday every %d min)",
                daily_cron, intraday_min)


def _is_market_hours_et() -> bool:
    """True during RTH (Mon-Fri 09:30–16:00 ET). Cheap gate so the intraday
    job doesn't hammer Alpaca/IBKR overnight and on weekends."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= hm <= 16 * 60


async def _active_universe_symbols() -> list[str]:
    from services import universe_service
    try:
        for p in await universe_service.list_presets_db():
            if p.get("is_active"):
                full = await universe_service.get_preset_db(p["name"])
                seen: dict[str, None] = {}
                for s in (full.get("tickers", []) if full else []) or []:
                    u = str(s).upper().strip()
                    if u:
                        seen.setdefault(u, None)
                return list(seen)
    except Exception as exc:  # noqa: BLE001
        logger.warning("candle refresh: universe read failed: %s", exc)
    return []


async def _intraday_watchlist() -> list[str]:
    """Pending-queue symbols + open positions + FX — the set worth keeping
    fresh intraday (best-effort; a failing source just yields fewer names)."""
    from services.candle_refresh_service import _FX_SET
    seen: dict[str, None] = {}
    # Pending queue
    try:
        from services.db_service import get_pending_plans
        for p in await get_pending_plans(status_filter="pending", limit=500):
            s = (p.get("symbol") or "").upper().strip()
            if s:
                seen.setdefault(s, None)
    except Exception as exc:  # noqa: BLE001
        logger.info("candle refresh: pending read failed: %s", exc)
    # Open positions
    try:
        from services.broker_service import get_adapter_async
        adapter = await get_adapter_async()
        acct = await adapter.get_account_state()
        for pos in getattr(acct, "open_positions", []) or []:
            s = (getattr(pos, "symbol", "") or "").upper().strip()
            if s:
                seen.setdefault(s, None)
    except Exception as exc:  # noqa: BLE001
        logger.info("candle refresh: positions read failed: %s", exc)
    # Always keep FX fresh (fvg_continuation is intraday)
    for s in _FX_SET:
        seen.setdefault(s, None)
    return list(seen)


async def _candle_refresh_daily_job() -> None:
    import os
    from services.candle_refresh_service import refresh_many
    try:
        symbols = await _active_universe_symbols()
        if not symbols:
            logger.info("candle refresh (daily): no active universe — skipping")
            return
        src = os.getenv("CANDLE_REFRESH_DAILY_SOURCE", "yfinance")
        await refresh_many(symbols, ["1d"], daily_source=src)
    except Exception as exc:  # noqa: BLE001 — must never crash the loop
        logger.warning("candle_refresh_daily raised: %s", exc)


async def _candle_refresh_intraday_job() -> None:
    import os
    from services.candle_refresh_service import refresh_many
    try:
        if not _is_market_hours_et():
            return
        symbols = await _intraday_watchlist()
        if not symbols:
            return
        intervals = [iv.strip() for iv in
                     os.getenv("CANDLE_REFRESH_INTERVALS_INTRADAY", "30m,15m,5m").split(",")
                     if iv.strip()]
        await refresh_many(symbols, intervals)
    except Exception as exc:  # noqa: BLE001
        logger.warning("candle_refresh_intraday raised: %s", exc)


# --------------------------------------------------------------------------- #
# Job: Capitol Trades polling
# --------------------------------------------------------------------------- #


def _register_copy_trading_jobs(sched: AsyncIOScheduler) -> None:
    # Poll every 30 min Mon–Fri during market hours (ET).
    # 08:30–17:00 covers pre-market news + regular session + post-close.
    sched.add_job(
        _poll_capitol_trades_job,
        CronTrigger(
            day_of_week="mon-fri",
            hour="8-17",
            minute="0,30",
            timezone="America/New_York",
        ),
        id="ct_poll",
        name="Capitol Trades poll",
        replace_existing=True,
        misfire_grace_time=120,
    )
    # Also run once at 07:00 ET to catch overnight disclosures
    sched.add_job(
        _poll_capitol_trades_job,
        CronTrigger(
            day_of_week="mon-fri",
            hour="7",
            minute="0",
            timezone="America/New_York",
        ),
        id="ct_morning",
        name="Capitol Trades morning scan",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("Registered Capitol Trades polling jobs")


async def _poll_capitol_trades_job() -> None:
    """Fetch recent disclosures for all followed politicians; queue new copy-trade plans."""
    from services import db_service
    from services.capitol_trades_service import CapitolTradesService
    from services.settings_service import get_settings

    logger.info("Capitol Trades poll: starting")
    try:
        cfg = await db_service.get_all_copy_config()
        enabled = cfg.get("enabled", "true").lower() == "true"
        if not enabled:
            logger.info("Capitol Trades poll: disabled via config — skipping")
            return

        followed = await db_service.list_followed_politicians()
        active = [p for p in followed if p.get("enabled", 1)]
        if not active:
            logger.info("Capitol Trades poll: no politicians followed — skipping")
            return

        # Auto-suggest gate: only queue copies from TOP-RATED insiders. We reuse
        # the SAME composite 1–10 decile the rankings UI shows, so "top-rated"
        # means the same thing everywhere. auto_suggest_min_rank defaults to 7
        # (top ~3 deciles). Set auto_suggest_enabled=false to copy every followed
        # insider regardless of rank (the pre-gate behavior).
        auto_suggest = cfg.get("auto_suggest_enabled", "true").lower() == "true"
        try:
            min_rank = int(float(cfg.get("auto_suggest_min_rank", "7")))
        except (TypeError, ValueError):
            min_rank = 7
        rank_map: dict[str, int] = {}
        try:
            from types import SimpleNamespace
            from routers.copy_trading import _compute_composite_ranks
            perf_cache = await db_service.get_member_performance_cache_map()
            members = [
                SimpleNamespace(politician_slug=p["slug"],
                                trade_count_90d=p.get("trade_count_90d", 0))
                for p in active
            ]
            rank_map = _compute_composite_ranks(members, perf_cache)
        except Exception as e:                                        # noqa: BLE001
            logger.warning("auto-suggest rank map failed: %s", e)

        svc = CapitolTradesService()
        known_ids = await db_service.get_known_trade_ids()
        total_fetched = 0
        total_queued = 0

        for pol in active:
            pol_slug = pol["slug"]
            pol_trades = await svc.fetch_politician_trades(pol_slug, pages=10)
            total_fetched += len(pol_trades)
            logger.info("Capitol Trades poll: fetched %d trades for %s", len(pol_trades), pol_slug)

            new_trades = [t for t in pol_trades if t.trade_id not in known_ids]
            for trade in new_trades:
                queued = await _process_one_trade(
                    trade, cfg, rank_map=rank_map,
                    min_rank=min_rank, auto_suggest=auto_suggest,
                )
                known_ids.add(trade.trade_id)
                if queued:
                    total_queued += 1

        await db_service.set_copy_config("last_scan_ts", datetime.now(timezone.utc).isoformat())
        await db_service.set_copy_config("last_scan_count", str(total_queued))
        await db_service.set_copy_config("last_scan_total_fetched", str(total_fetched))
        await db_service.set_copy_config("last_scan_error", "")
        logger.info(
            "Capitol Trades poll: done — %d politicians, %d fetched, %d queued",
            len(active), total_fetched, total_queued,
        )

    except Exception as exc:
        logger.exception("Capitol Trades poll failed: %s", exc)
        # Record failure so the UI can show it
        try:
            await db_service.set_copy_config(
                "last_scan_error",
                f"{datetime.now(timezone.utc).isoformat()}: {exc}",
            )
        except Exception:
            pass


async def _process_one_trade(
    trade, cfg: dict, *, rank_map: dict[str, int] | None = None,
    min_rank: int = 0, auto_suggest: bool = False,
) -> bool:
    """Save a new trade to DB, evaluate it, and queue as TradePlan if it passes.

    Returns True iff a plan was queued to /pending. When ``auto_suggest`` is on,
    only trades from TOP-RATED insiders (composite decile >= ``min_rank``) are
    queued; the rest are recorded as skipped so the operator can see why.
    """
    from agents.compliance_officer import ComplianceOfficer
    from agents.copy_trader import CopyTrader
    from agents.risk_manager import RiskManager
    from models.account import LULDBand, MarketState
    from services import db_service
    from services.broker_service import get_adapter
    from services.settings_service import get_settings

    # Always persist first so we don't re-process on next poll
    is_new = await db_service.upsert_politician_trade(
        trade.trade_id,
        politician_name=trade.politician_name,
        politician_slug=trade.politician_slug,
        party=trade.party,
        chamber=trade.chamber,
        ticker=trade.ticker,
        asset_name=trade.asset_name,
        asset_type=trade.asset_type,
        transaction_type=trade.transaction_type,
        transaction_date=trade.transaction_date,
        published_date=trade.published_date,
        amount_min=trade.amount_min,
        amount_max=trade.amount_max,
    )
    if not is_new:
        return False  # Race condition — another poll already inserted it

    max_usd = float(cfg.get("max_per_trade_usd", "5000"))
    trader = CopyTrader(max_per_trade_usd=max_usd)

    ok, skip_reason = trader.should_copy(trade)
    if not ok:
        logger.info("Copy skip %s %s: %s", trade.ticker, trade.transaction_type, skip_reason)
        await db_service.update_politician_trade_copy(
            trade.trade_id, copy_status="skipped", skip_reason=skip_reason
        )
        return False

    # ── Auto-suggest gate: only top-rated insiders get a queued suggestion ──
    insider_rank = (rank_map or {}).get(trade.politician_slug)
    if auto_suggest and (insider_rank is None or insider_rank < min_rank):
        reason = (
            f"insider not top-rated (rank "
            f"{insider_rank if insider_rank is not None else 'n/a'} < {min_rank})"
        )
        logger.info("Copy skip %s %s: %s", trade.ticker, trade.transaction_type, reason)
        await db_service.update_politician_trade_copy(
            trade.trade_id, copy_status="skipped", skip_reason=reason
        )
        return False

    try:
        adapter = get_adapter()
        if not adapter.connected:
            await adapter.connect()
        quote = await adapter.get_quote(trade.ticker)
    except Exception as exc:
        logger.warning("Could not get quote for %s: %s — skipping copy", trade.ticker, exc)
        await db_service.update_politician_trade_copy(
            trade.trade_id, copy_status="skipped", skip_reason=f"quote error: {exc}"
        )
        return False

    s = get_settings()
    plan = trader.generate_plan(trade, quote, mode=s.app.mode)

    # Run compliance gate
    try:
        account = await adapter.get_account()
        market_state = MarketState(
            is_open=True,
            halted_symbols=[],
            luld_bands={},
            session="regular",
        )
        compliance = ComplianceOfficer()
        cv = compliance.check(plan, account, market_state)
        if cv.result != "pass":
            logger.info("Copy trade %s blocked by compliance: %s", trade.ticker, cv.reason)
            await db_service.update_politician_trade_copy(
                trade.trade_id,
                copy_status="skipped",
                skip_reason=f"compliance: {cv.reason}",
            )
            return False

        risk_mgr = RiskManager()
        rv = risk_mgr.pre_trade_check(plan, account)
        if rv.result == "rejected":
            logger.info("Copy trade %s blocked by risk: %s", trade.ticker, rv.reason)
            await db_service.update_politician_trade_copy(
                trade.trade_id,
                copy_status="skipped",
                skip_reason=f"risk: {rv.reason}",
            )
            return False

    except Exception as exc:
        logger.warning("Gate check for %s raised: %s — queuing anyway", trade.ticker, exc)
        cv = None
        rv = None

    # Persist plan for human review (or auto-execute in paper mode)
    await db_service.upsert_pending_plan(
        plan.model_dump(),
        compliance_verdict=cv.model_dump() if cv else None,
        risk_verdict=rv.model_dump() if rv else None,
        status="pending",
        strategy="copy_trading",
    )
    await db_service.update_politician_trade_copy(
        trade.trade_id, copy_status="queued", copy_plan_id=plan.plan_id
    )
    logger.info(
        "Copy trade queued (insider rank %s): %s %s %s plan_id=%s",
        insider_rank if insider_rank is not None else "n/a",
        trade.politician_name, trade.transaction_type, trade.ticker, plan.plan_id,
    )
    return True


# --------------------------------------------------------------------------- #
# Job: Senate eFD daily diff
# --------------------------------------------------------------------------- #


def _register_senate_diff_job(sched: AsyncIOScheduler) -> None:
    """Daily 06:00 ET diff against efdsearch.senate.gov.

    Fetches the last 30 days of PTR filings, compares to the cached
    ``senate_filings`` table, and writes:
      copy_trading_config.senate_last_refresh_at  -> now (ISO)
      copy_trading_config.senate_new_filings_count -> #new since last manual refresh
      copy_trading_config.senate_last_diff_at     -> now (ISO)
      copy_trading_config.senate_last_diff_error  -> exception text on failure

    The "new since last manual refresh" semantics keep the counter
    monotonic across daily diffs — it only resets when the user clicks
    "Refresh Senate" on the rankings page (see
    ``routers/copy_trading.refresh_senate``).
    """
    sched.add_job(
        _senate_diff_job,
        CronTrigger(
            day_of_week="mon-sat",  # eFD doesn't update Sundays
            hour="6", minute="0",
            timezone="America/New_York",
        ),
        id="senate_daily_diff",
        name="Senate eFD daily diff",
        replace_existing=True,
        misfire_grace_time=900,   # 15 min — not time-critical
    )
    logger.info("Registered Senate eFD daily diff job (06:00 ET Mon-Sat)")


async def _senate_diff_job() -> None:
    """Fetch last-30-days PTR filings, diff, persist, update config."""
    from dataclasses import asdict
    from services import db_service
    from services.senate_efd_service import SenateEFDService

    logger.info("Senate diff: starting")
    started = datetime.now(timezone.utc).isoformat()
    try:
        svc = SenateEFDService()
        # 30-day window is enough for daily diffs; the manual Refresh
        # Senate button uses 365d for a full backfill.
        filings = await svc.fetch_ptr_filings(
            days_back=30, page_size=100, max_pages=10,
        )
    except Exception as exc:
        logger.exception("Senate diff: fetch failed")
        try:
            await db_service.set_copy_config(
                "senate_last_diff_error",
                f"{started}: {exc}",
            )
        except Exception:
            pass
        return

    # Compute the true new count by diffing PTR ids against the cache
    # before the upsert (the upsert's own counter mis-attributes due to
    # SQLite ON CONFLICT rowcount behavior).
    fetched_ids = {f.ptr_id for f in filings}
    known_ids = await db_service.get_known_senate_ptr_ids()
    new_ids = fetched_ids - known_ids

    # Persist (idempotent — the upsert no-ops on existing PTRs)
    filing_dicts = []
    for f in filings:
        from routers.copy_trading import _slug_from_name
        d = asdict(f)
        d["senator_slug"] = _slug_from_name(f.senator_name)
        filing_dicts.append(d)
    await db_service.upsert_senate_filings(filing_dicts)

    cfg = await db_service.get_all_copy_config()
    prior = int(cfg.get("senate_new_filings_count", "0") or 0)
    new_total = prior + len(new_ids)

    now = datetime.now(timezone.utc).isoformat()
    await db_service.set_copy_config("senate_last_diff_at", now)
    await db_service.set_copy_config("senate_new_filings_count", str(new_total))
    # Clear any prior error so the UI can stop showing it
    await db_service.set_copy_config("senate_last_diff_error", "")

    logger.info(
        "Senate diff: fetched=%d new=%d (running unread=%d)",
        len(filings), len(new_ids), new_total,
    )


# --------------------------------------------------------------------------- #
# Job: scheduled workflow runs
# --------------------------------------------------------------------------- #


def _register_workflow_jobs(sched: AsyncIOScheduler) -> None:
    """Read workflow YAMLs and register cron jobs for any that have a schedule."""
    import glob
    import yaml

    from services.settings_service import PROJECT_ROOT

    workflow_dir = PROJECT_ROOT / "workflows"
    yaml_files = list(workflow_dir.glob("*.yaml")) + list(workflow_dir.glob("*.yml"))

    for path in yaml_files:
        try:
            with open(path) as f:
                wf = yaml.safe_load(f)
            schedule = wf.get("schedule")
            wf_id = wf.get("id") or path.stem
            if not schedule:
                continue
            sched.add_job(
                _run_workflow_job,
                CronTrigger.from_crontab(schedule, timezone="America/New_York"),
                id=f"wf_{wf_id}",
                name=f"Workflow: {wf.get('name', wf_id)}",
                args=[wf_id],
                replace_existing=True,
                misfire_grace_time=300,
            )
            logger.info("Scheduled workflow %s: %s", wf_id, schedule)
        except Exception as exc:
            logger.warning("Could not register schedule for %s: %s", path.name, exc)


async def _run_workflow_job(workflow_id: str) -> None:
    from services.pipeline_service import run_workflow_by_id
    from services.job_log_buffer import capture

    with capture(f"wf_{workflow_id}"):
        logger.info("Scheduled workflow run: %s", workflow_id)
        try:
            result = await run_workflow_by_id(workflow_id)
            logger.info("Workflow %s complete: %s", workflow_id, result.get("status"))
        except Exception as exc:
            logger.exception("Workflow %s failed: %s", workflow_id, exc)


# --------------------------------------------------------------------------- #
# Catch-up on restart
# --------------------------------------------------------------------------- #


async def _catch_up_missed_runs(sched: AsyncIOScheduler) -> None:
    """For each registered cron job, fire it once if its trigger time
    earlier today has already passed AND no pipeline_run exists for
    today. Avoids the silent-skip behavior where restarting the app
    after the cron window kills that day's run.

    Scope: only ``wf_*`` (workflow) jobs —
    stuff with side effects we want to actually happen. Capitol Trades
    polling and Senate diff are skipped because they're idempotent
    pollers — missing one is fine.
    """
    import asyncio
    from datetime import datetime, timedelta, timezone

    import pandas as pd

    from services import db_service

    # Brief delay so app lifespan can finish bootstrapping (e.g. broker
    # connect) before we fire workflows that depend on it.
    await asyncio.sleep(5)

    et_now = pd.Timestamp.now(tz="America/New_York")
    if et_now.weekday() >= 5:                                    # Sat/Sun
        logger.info("catch-up: weekend, skipping")
        return

    today_iso = et_now.strftime("%Y-%m-%d")

    # Build a map of workflow_id -> latest run today (if any) so we
    # don't re-fire a job that already ran. Scan recent runs only.
    runs = await db_service.list_pipeline_runs(limit=50)
    ran_today: set[str] = set()
    for r in runs:
        wf = r.get("workflow_id")
        ts = (r.get("ts_start") or "")
        if wf and ts.startswith(today_iso):
            ran_today.add(wf)

    fired = 0
    for job in list(sched.get_jobs()):
        jid = getattr(job, "id", "") or ""
        # Only catch up the strategy-firing workflow jobs.
        if not jid.startswith("wf_"):
            continue

        next_run = job.next_run_time
        # Compute today's scheduled fire time. APScheduler's CronTrigger
        # exposes ``get_next_fire_time`` we can use to peek what *would*
        # have fired today — by comparing against now.
        try:
            today_start = et_now.normalize().tz_convert("UTC")
            tomorrow_start = (et_now.normalize() + pd.Timedelta(days=1)).tz_convert("UTC")
            scheduled_today = job.trigger.get_next_fire_time(
                None, today_start.to_pydatetime(),
            )
        except Exception as exc:                                  # noqa: BLE001
            logger.debug("catch-up: %s next-fire lookup failed: %s", jid, exc)
            continue
        if scheduled_today is None:
            continue
        if scheduled_today >= tomorrow_start.to_pydatetime():
            continue                                              # not due today
        if scheduled_today > datetime.now(timezone.utc):
            continue                                              # still upcoming

        wf_id_for_run = jid[3:] if jid.startswith("wf_") else jid
        if wf_id_for_run in ran_today:
            logger.info(
                "catch-up: %s already ran today, skipping", jid,
            )
            continue

        logger.warning(
            "catch-up: firing %s (cron at %s ET passed without execution)",
            jid, scheduled_today.astimezone(
                __import__("zoneinfo").ZoneInfo("America/New_York")
            ).strftime("%H:%M"),
        )
        try:
            await _run_workflow_job(wf_id_for_run)
            fired += 1
        except Exception as exc:                                  # noqa: BLE001
            logger.error("catch-up: %s raised during catch-up: %s", jid, exc)

    if fired:
        logger.warning("catch-up: fired %d missed run(s) this morning", fired)
    else:
        logger.info("catch-up: nothing to fire (all on schedule or future)")


# --------------------------------------------------------------------------- #
# Daily digest — single ntfy push at 16:30 ET summarizing the day
# --------------------------------------------------------------------------- #


def _register_daily_digest_job(sched: AsyncIOScheduler) -> None:
    """Register the 16:30 ET Mon-Fri digest job.

    Fires after the session close so it can include EOD broker state
    (positions flat, day P&L) plus today's pipeline activity. One
    push per weekday — keeps the operator aware on quiet days too.
    """
    sched.add_job(
        _daily_digest_job,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=30,
                    timezone="America/New_York"),
        id="daily_digest",
        name="Daily digest (16:30 ET)",
        replace_existing=True,
        misfire_grace_time=1800,  # 30-min grace — late summary is still useful
    )
    logger.info("Scheduled daily_digest at 16:30 ET Mon-Fri")


async def _daily_digest_job() -> None:
    """Build today's digest from DB + broker, fire one ntfy push."""
    from datetime import datetime as _dt, timezone as _tz
    import zoneinfo as _zi
    from services import alert_service, db_service

    et_now = _dt.now(_zi.ZoneInfo("America/New_York"))
    today_iso = et_now.strftime("%Y-%m-%d")

    # Pipeline runs today
    runs = await db_service.list_pipeline_runs(limit=20)
    today_runs = [r for r in runs if (r.get("ts_start") or "").startswith(today_iso)]
    sigs = sum(r.get("signals_generated", 0) or 0 for r in today_runs)
    plans = sum(r.get("plans_proposed", 0) or 0 for r in today_runs)
    approved = sum(r.get("plans_approved", 0) or 0 for r in today_runs)
    error_runs = [r for r in today_runs if r.get("status") == "error"]

    # Today's alerts breakdown
    since = et_now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    alerts = await alert_service.list_alerts(since_ts=since, limit=200)
    armed_count    = sum(1 for a in alerts if a["kind"] == "armed")
    rejected_count = sum(1 for a in alerts if a["kind"] == "rejected")
    filled_count   = sum(1 for a in alerts if a["kind"] == "filled")
    closed_count   = sum(1 for a in alerts if a["kind"] == "closed")

    # Broker state (best effort)
    equity = cash = None
    positions_n = 0
    fills_today_n = 0
    try:
        from services import broker_service
        adapter = await broker_service.get_adapter_async()
        if not adapter.connected:
            await adapter.connect()
        if adapter.connected:
            state = await adapter.get_account_state()
            equity = float(state.equity or 0)
            cash = float(state.cash or 0)
            positions_n = len(state.open_positions or [])
            fills = await adapter.get_fills(since_ts=since)
            fills_today_n = len(fills)
    except Exception as exc:                                          # noqa: BLE001
        logger.warning("digest: broker fetch failed: %s", exc)

    # Headline
    headline_bits = []
    if approved > 0:
        headline_bits.append(f"{approved} fired")
    if rejected_count > 0:
        headline_bits.append(f"{rejected_count} rejected")
    if filled_count > 0:
        headline_bits.append(f"{filled_count} filled")
    if not headline_bits:
        headline_bits.append("quiet day, 0 fires")
    title = f"Daily digest {today_iso} — " + " · ".join(headline_bits)

    # Body — readable on phone notification
    lines = []
    if today_runs:
        for r in today_runs:
            wf = r.get("workflow_id", "?")
            s = r.get("signals_generated", 0) or 0
            p = r.get("plans_proposed", 0) or 0
            st = r.get("status", "?")
            lines.append(f"• {wf}: {s} sig, {p} plans, {st}")
    else:
        lines.append("• No pipeline runs today")
    lines.append(
        f"• Plans: {armed_count} armed, {rejected_count} rejected, "
        f"{filled_count} filled, {closed_count} closed"
    )
    if equity is not None:
        lines.append(f"• Account: ${equity:,.2f} equity, ${cash:,.2f} cash, "
                     f"{positions_n} positions, {fills_today_n} fills today")
    if error_runs:
        lines.append(f"• ⚠ {len(error_runs)} run(s) errored — check /jobs")
    body = "\n".join(lines)

    try:
        await alert_service.record_alert(
            kind="digest", strategy="meta", symbol=None, direction=None,
            plan_id=None, title=title, body=body,
            payload={
                "date": today_iso,
                "signals": sigs, "plans": plans, "approved": approved,
                "armed": armed_count, "rejected": rejected_count,
                "filled": filled_count, "closed": closed_count,
                "errors": len(error_runs), "fills_today": fills_today_n,
                "equity": equity, "cash": cash, "positions": positions_n,
            },
        )
        logger.info("daily_digest: %s", title)
    except Exception as exc:                                          # noqa: BLE001
        logger.warning("daily_digest record_alert failed: %s", exc)
