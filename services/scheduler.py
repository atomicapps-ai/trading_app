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
    _register_workflow_jobs(sched)

    sched.start()
    logger.info("Scheduler started — %d jobs registered", len(sched.get_jobs()))


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    _scheduler = None


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
                await _process_one_trade(trade, cfg)
                known_ids.add(trade.trade_id)
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


async def _process_one_trade(trade, cfg: dict) -> None:
    """Save a new trade to DB, evaluate it, and queue as TradePlan if it passes."""
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
        return  # Race condition — another poll already inserted it

    max_usd = float(cfg.get("max_per_trade_usd", "5000"))
    trader = CopyTrader(max_per_trade_usd=max_usd)

    ok, skip_reason = trader.should_copy(trade)
    if not ok:
        logger.info("Copy skip %s %s: %s", trade.ticker, trade.transaction_type, skip_reason)
        await db_service.update_politician_trade_copy(
            trade.trade_id, copy_status="skipped", skip_reason=skip_reason
        )
        return

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
        return

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
            return

        risk_mgr = RiskManager()
        rv = risk_mgr.pre_trade_check(plan, account)
        if rv.result == "rejected":
            logger.info("Copy trade %s blocked by risk: %s", trade.ticker, rv.reason)
            await db_service.update_politician_trade_copy(
                trade.trade_id,
                copy_status="skipped",
                skip_reason=f"risk: {rv.reason}",
            )
            return

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
        "Copy trade queued: %s %s %s plan_id=%s",
        trade.politician_name, trade.transaction_type, trade.ticker, plan.plan_id,
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
    logger.info("Scheduled workflow run: %s", workflow_id)
    try:
        result = await run_workflow_by_id(workflow_id)
        logger.info("Workflow %s complete: %s", workflow_id, result.get("status"))
    except Exception as exc:
        logger.exception("Workflow %s failed: %s", workflow_id, exc)
