"""broker_service.py — adapter factory and singleton access.

The active adapter is selected at startup based on the active row in the
``broker_accounts`` table (see ``services.account_service``). All other
code that needs broker access calls ``get_adapter()`` — never instantiates
adapters directly.

Switching accounts at runtime
-----------------------------
    await account_service.set_active(slug)
    await reset_adapter()       # tears down the old adapter
    await connect_adapter()     # rebuilds + connects with the new creds

Mode interaction
----------------
``settings.app.mode`` and the active account's ``account_type`` are kept
in sync by the broker page when the user picks an account: activating a
live row flips ``settings.app.mode`` to live (and vice versa for paper).
Research mode ignores the registry entirely and uses HistoricalAdapter.

Also owns the module-level ``TRADING_HALTED`` flag set by ``/broker/halt``
and read by the executioner.
"""
from __future__ import annotations

import logging
import os

from brokers.alpaca import AlpacaAdapter
from brokers.base import BrokerAdapter
from brokers.historical import HistoricalAdapter
from brokers.ibkr import IbkrAdapter
from brokers.oanda import OandaAdapter
from brokers.tradestation import TradeStationAdapter
from services import account_service
from services.settings_service import get_settings

logger = logging.getLogger(__name__)

_adapter: BrokerAdapter | None = None
_active_slug: str | None = None  # remembered so reset_adapter() can rebuild

# HALT flag — set True by POST /broker/halt; checked by executioner.
TRADING_HALTED: bool = False


# --------------------------------------------------------------------------- #
# Adapter construction
# --------------------------------------------------------------------------- #


async def build_adapter() -> BrokerAdapter:
    """Build the right BrokerAdapter for the current mode + active account.

    Mode-to-adapter routing:
      * research → HistoricalAdapter (no broker, cached bars only)
      * paper / live → adapter for the row currently flagged is_active
    """
    global _active_slug
    s = get_settings()
    mode = s.app.mode
    if mode == "research":
        _active_slug = None
        logger.info("Broker: using HistoricalAdapter (research mode)")
        return HistoricalAdapter()

    active = await account_service.get_active_account()
    if active is None:
        # No accounts in the registry yet — fall back to the legacy env-only
        # path so a fresh-checkout user without a populated DB still gets a
        # working adapter when they have .env creds.
        logger.warning(
            "No active broker account in registry — using legacy env-only path. "
            "Visit /broker to add an account."
        )
        return _legacy_env_adapter(mode)

    _active_slug = active["slug"]
    provider = active["provider"]
    paper = active["account_type"] == "paper"
    label = f"{provider}_{active['account_type']} ({active['label']})"

    if provider == "alpaca":
        logger.info("Broker: AlpacaAdapter (%s) account=%s",
                    "paper" if paper else "LIVE", active["slug"])
        return AlpacaAdapter(
            paper=paper,
            key_id=active["key_id"],
            secret=active["secret"],
            label=label,
        )

    if provider == "tradestation":
        # TradeStation is still env-driven for the OAuth refresh-token
        # rotation. Multi-account support for TS is a follow-up — for
        # now, the active row's existence selects sim vs live tier and we
        # log a warning if it disagrees with TS_SIM in the env.
        env_sim = os.getenv("TS_SIM", "true").lower() != "false"
        if env_sim != paper:
            logger.warning(
                "TradeStation account row says %s but TS_SIM env says %s; "
                "edit .env to match.",
                "paper" if paper else "live",
                "sim" if env_sim else "live",
            )
        logger.info("Broker: TradeStationAdapter (%s)",
                    "sim" if paper else "live")
        return TradeStationAdapter(sim=paper)

    if provider == "ibkr":
        logger.info("Broker: IbkrAdapter (%s) account=%s",
                    "paper" if paper else "LIVE", active["slug"])
        return IbkrAdapter(paper=paper, label=label)

    if provider == "oanda":
        logger.info("Broker: OandaAdapter (%s) account=%s",
                    "practice" if paper else "LIVE", active["slug"])
        return OandaAdapter(
            paper=paper,
            token=active.get("secret") or None,      # store the OANDA token in the secret field
            account_id=active.get("key_id") or None,  # store the OANDA account id in the key_id field
            label=label,
        )

    logger.warning(
        "Unknown provider %r in active account row — falling back to Alpaca paper",
        provider,
    )
    return AlpacaAdapter(paper=True)


def _legacy_env_adapter(mode: str) -> BrokerAdapter:
    """Original env-driven path — used only when the registry is empty."""
    provider = os.getenv("BROKER_PROVIDER", "alpaca").lower()
    if provider == "tradestation":
        ts_sim = os.getenv("TS_SIM", "true").lower() == "true"
        return TradeStationAdapter(sim=ts_sim)
    if provider == "oanda":
        env = (os.getenv("OANDA_ENV") or "practice").lower()
        return OandaAdapter(paper=(env != "live"))
    if provider == "ibkr":
        port = int(os.getenv("IBKR_PORT", "4002"))
        return IbkrAdapter(paper=(port in (4002, 7497)))  # paper ports
    paper = mode == "paper" or os.getenv("ALPACA_PAPER", "true").lower() == "true"
    return AlpacaAdapter(paper=paper)


# --------------------------------------------------------------------------- #
# Singleton accessors
# --------------------------------------------------------------------------- #


async def get_adapter_async() -> BrokerAdapter:
    """Async accessor — self-heals from a stale adapter when the DB's
    active broker_account row diverges from this worker's singleton.

    Why: in multi-worker prod each worker has its own ``_adapter``.
    Activating an account only updates the worker that serves that
    request; other workers would silently keep an old adapter without
    this check. We default to 1 worker (run.py) precisely to avoid
    that, but this guard makes the system correct even if someone
    runs --workers 2.
    """
    global _adapter
    if _adapter is None:
        _adapter = await build_adapter()
        return _adapter

    try:
        active = await account_service.get_active_account()
        active_slug_db = active["slug"] if active else None
    except Exception:                                                  # noqa: BLE001
        active_slug_db = None

    if active_slug_db is not None and active_slug_db != _active_slug:
        logger.info(
            "broker_service: active slug changed (%s -> %s); rebuilding adapter",
            _active_slug, active_slug_db,
        )
        try:
            await _adapter.disconnect()
        except Exception as exc:                                       # noqa: BLE001
            logger.debug("disconnect during self-heal: %s", exc)
        _adapter = await build_adapter()
    return _adapter


def get_adapter() -> BrokerAdapter:
    """Synchronous accessor for callers that don't await.

    The first call **must** happen on the lifespan path where an
    awaitable initialization runs (``connect_adapter()``). After that the
    sync accessor is safe — there's only ever one adapter instance.
    """
    if _adapter is None:
        # Synchronous fallback — research mode is sync-safe, and the
        # legacy env-only path is sync-safe too. We never call this
        # before the lifespan hook initializes the registry, so the
        # async account_service path is unreachable from here in normal
        # operation; this branch exists for tooling/scripts that import
        # the service before the app starts.
        s = get_settings()
        if s.app.mode == "research":
            return HistoricalAdapter()
        return _legacy_env_adapter(s.app.mode)
    return _adapter


async def connect_adapter() -> bool:
    adapter = await get_adapter_async()
    if adapter.connected:
        return True
    ok = await adapter.connect()
    # Stamp last_connected / last_error on the active row.
    if _active_slug:
        try:
            err = None if ok else "connect() returned False"
            await account_service.record_connect(_active_slug, error=err)
        except Exception as exc:  # noqa: BLE001
            logger.debug("record_connect failed: %s", exc)
    return ok


async def reset_adapter() -> None:
    """Force re-creation of the adapter (e.g. after activating a different
    account or changing mode)."""
    global _adapter
    if _adapter is not None:
        try:
            await _adapter.disconnect()
        except Exception as e:                                    # noqa: BLE001
            logger.warning("disconnect raised during reset: %s", e)
    _adapter = None


def set_halted(value: bool) -> None:
    """Mutate the global HALT flag. Called by /broker/halt."""
    global TRADING_HALTED
    TRADING_HALTED = value
    logger.warning("TRADING_HALTED set to %s", value)
