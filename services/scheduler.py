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
    _register_senate_diff_job(sched)
    _register_workflow_jobs(sched)
    _register_dl_lock1_scout(sched)

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
# Job: DL Lock 1 scout — 10:00 ET early-warning before the 10:30 fire
# --------------------------------------------------------------------------- #


# Cron expression is read from this constant so a small env-var override
# can shift it for testing without a YAML edit. Default: 10:00 ET Mon-Fri.
import os
_DL_LOCK1_CRON = os.environ.get("DL_LOCK1_CRON", "0 10 * * 1-5")


def _register_dl_lock1_scout(sched: AsyncIOScheduler) -> None:
    sched.add_job(
        _dl_lock1_scout_job,
        CronTrigger.from_crontab(_DL_LOCK1_CRON, timezone="America/New_York"),
        id="dl_lock1_scout",
        name="DL Lock 1 Scout (10:00 ET)",
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info("Registered DL Lock 1 Scout: %s", _DL_LOCK1_CRON)


async def _dl_lock1_scout_job() -> None:
    """Evaluate candle 1 + regime filter for every symbol the DL workflow
    will scan at 10:30. Each pass writes one ``lock1_scouted`` alert.

    Reads the same screener / strategy config the 10:30 workflow uses
    so the scout never disagrees with the live fire — anything flagged
    here is a candidate the full detector will accept iff candle 2
    confirms direction.
    """
    from services.job_log_buffer import capture
    with capture("dl_lock1_scout"):
        await _dl_lock1_scout_job_impl()


async def _dl_lock1_scout_job_impl() -> None:
    import asyncio as _asyncio
    import yaml as _yaml
    import pandas as _pd

    from services import alert_service, data_service
    from services.settings_service import STRATEGY_CONFIG_DIR, PROJECT_ROOT
    from services.universe_service import get_preset_db
    from agents.lock1_scout import evaluate_lock1
    from services.indicator_service import add_indicators

    logger.info("DL Lock 1 Scout: starting")

    # Load strategy config — same yaml the 10:30 workflow reads.
    cfg_path = STRATEGY_CONFIG_DIR / "double_lock.yaml"
    try:
        cfg = _yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception as e:                                    # noqa: BLE001
        logger.error("DL Lock 1 Scout: bad config %s: %s", cfg_path, e)
        return

    # Symbols come from the active universe preset configured in the
    # workflow YAML — keep them in lockstep so the scout sees the same
    # list the 10:30 workflow will scan.
    workflow_path = PROJECT_ROOT / "workflows" / "double_lock_1030.yaml"
    try:
        wf = _yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
        preset = None
        for step in wf.get("steps", []):
            if step.get("kind") == "filter_universe":
                preset = (step.get("params") or {}).get("preset")
                break
        if not preset:
            preset = "liquid_momentum_core"
    except Exception:                                          # noqa: BLE001
        preset = "liquid_momentum_core"

    try:
        preset_row = await get_preset_db(preset)
        symbols = (preset_row or {}).get("tickers") or []
    except Exception as e:                                    # noqa: BLE001
        logger.warning("DL Lock 1 Scout: cant load preset %s: %s", preset, e)
        symbols = []
    if not symbols:
        # Fallback: a small bellwether list so the scout still runs in
        # smoke-testing setups without the full screener seeded.
        symbols = [
            "SPY", "QQQ", "AAPL", "NVDA", "MSFT",
            "TSLA", "AMZN", "META", "GOOGL", "AVGO",
        ]
        logger.info(
            "DL Lock 1 Scout: preset empty, using bellwether fallback (%d syms)",
            len(symbols),
        )

    # VIX previous close — same indicator service the full detector uses.
    try:
        vix_daily = await data_service.get_bars(
            "^VIX", "1d", min_bars=2, download_if_missing=False,
        )
        vix_prev_close = (
            float(vix_daily["close"].iloc[-2])
            if len(vix_daily) >= 2 else None
        )
    except Exception as e:                                    # noqa: BLE001
        logger.warning("DL Lock 1 Scout: VIX prev close unavailable: %s", e)
        vix_prev_close = None

    now_et = _pd.Timestamp.now(tz="America/New_York")
    candidates = 0

    async def _scan_one(sym: str) -> None:
        nonlocal candidates
        try:
            bars = await data_service.get_bars(sym, "30m", min_bars=2)
            daily = await data_service.get_bars(
                sym, "1d", min_bars=20, download_if_missing=False,
            )
            daily = add_indicators(daily)
            cand = evaluate_lock1(
                symbol=sym, bars_30m=bars, daily=daily,
                vix_prev_close=vix_prev_close,
                config=cfg, as_of_ts=now_et,
            )
        except Exception as e:                                # noqa: BLE001
            logger.debug("scout: %s skipped: %s", sym, e)
            return
        if cand is None:
            return
        candidates += 1
        await alert_service.record_alert(
            kind="lock1_scouted",
            strategy="double_lock",
            symbol=sym,
            direction=cand.direction,
            title=f"{sym} {cand.direction.upper()} — Lock 1 set, watch 10:30",
            body=(
                f"c1 close ${cand.candle_close} · "
                f"body {int(cand.candle_body_pct * 100)}% · "
                f"vol {cand.volume_ratio:.1f}x · "
                f"VIX {cand.vix_prev_close} · ADX {cand.adx_d} · "
                f"RSI {cand.rsi_d}"
            ),
            payload={
                "candle_close": cand.candle_close,
                "body_pct": cand.candle_body_pct,
                "close_pct": cand.candle_close_pct,
                "volume_ratio": cand.volume_ratio,
                "vix_prev_close": cand.vix_prev_close,
                "adx_d": cand.adx_d,
                "rsi_d": cand.rsi_d,
            },
        )

    await _asyncio.gather(*(_scan_one(s) for s in symbols),
                          return_exceptions=False)
    logger.info(
        "DL Lock 1 Scout: scanned %d symbols, %d candidates",
        len(symbols), candidates,
    )
