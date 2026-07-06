"""Settings: load/save settings.yaml, expose path constants.

Path constants are the single source of truth for where data lives.
Never hardcode a path elsewhere — import from here.

Settings are cached. Call `reload_settings()` after editing the YAML on disk;
`save_settings()` invalidates the cache automatically.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Path constants
# --------------------------------------------------------------------------- #

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

SETTINGS_FILE: Path = PROJECT_ROOT / "settings.yaml"
TRADE_LOG_DIR: Path = PROJECT_ROOT / "trade_logs"
FILTER_PRESET_DIR: Path = PROJECT_ROOT / "universe_filters"
STRATEGY_CONFIG_DIR: Path = PROJECT_ROOT / "strategy_configs"
DATA_DIR: Path = PROJECT_ROOT / "data"
LOCAL_LOGS_DIR: Path = DATA_DIR / "logs"
STATIC_DIR: Path = PROJECT_ROOT / "static"
TEMPLATES_DIR: Path = PROJECT_ROOT / "templates"
ENV_FILE: Path = PROJECT_ROOT / ".env"

# SQLite database path — in-project under data/. The Drive carve-out
# to C:/Temp/ was retired 2026-04-20 when the project moved off Drive
# to a local C: path (see CLAUDE.md storage table). The DB is gitignored
# and excluded from any backup script — it rebuilds from trade_logs/*.jsonl
# on startup per the original Phase 1 design.
LOCAL_DB_PATH: Path = DATA_DIR / "claude_trading_app.db"


# --------------------------------------------------------------------------- #
# Static-asset cache-busting
# --------------------------------------------------------------------------- #
def _compute_asset_version() -> str:
    """A token that changes whenever any CSS/JS on disk changes.

    Appended to /static URLs as ``?v=<token>`` so a deploy (git pull, which
    bumps the changed files' mtimes) produces new URLs and browsers fetch the
    fresh files on a normal reload — no manual cache-clearing.
    """
    latest = 0
    try:
        for p in STATIC_DIR.rglob("*"):
            if p.suffix in (".css", ".js") and p.is_file():
                latest = max(latest, int(p.stat().st_mtime))
    except Exception:
        pass
    return str(latest or 1)


ASSET_VERSION: str = _compute_asset_version()

# Expose ``asset_v`` as a Jinja global on EVERY Jinja2Templates instance, so
# any template can cache-bust with ``?v={{ asset_v }}`` without per-route
# wiring. Patch runs at import (before routers construct their templates).
try:
    from fastapi.templating import Jinja2Templates as _Jinja2Templates
    _j2_orig_init = _Jinja2Templates.__init__

    def _j2_init_with_asset_v(self, *args, **kwargs):  # noqa: ANN001
        _j2_orig_init(self, *args, **kwargs)
        try:
            self.env.globals.setdefault("asset_v", ASSET_VERSION)
        except Exception:
            pass

    _Jinja2Templates.__init__ = _j2_init_with_asset_v  # type: ignore[method-assign]
except Exception:
    pass


# --------------------------------------------------------------------------- #
# Settings schema (mirrors SKILL.md §9.5)
# --------------------------------------------------------------------------- #

Mode = Literal["research", "paper", "live"]


class AppSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 5000
    tailscale_hostname: str = "my-trading-pc"
    mode: Mode = "paper"
    # Public origin the app is reached at once deployed (e.g.
    # "https://app.tindex.ai"). Used to build absolute links in phone-push
    # notifications so tapping an alert opens the real site. Populated from the
    # PUBLIC_BASE_URL env var at load time (see _load_from_disk); empty = local.
    public_base_url: str = ""


class NtfyPriorityMap(BaseModel):
    pending_approval: str = "high"
    fill_received: str = "default"
    daily_loss_cap_hit: str = "urgent"
    agent_error: str = "urgent"


class NtfySettings(BaseModel):
    enabled: bool = True
    server: str = "https://ntfy.sh"
    topic: str = "trading-agent-julius"
    priority_map: NtfyPriorityMap = Field(default_factory=NtfyPriorityMap)


class RiskDefaults(BaseModel):
    max_risk_pct_per_trade: float = 0.50
    max_position_pct_of_equity: float = 10.0
    max_daily_loss_pct: float = 2.0
    max_open_positions: int = 8
    max_daily_trades: int = 10
    min_rr_ratio: float = 2.0
    participation_cap_pct_adv: float = 2.0
    max_spread_bps_to_cross: float = 20.0
    max_sector_concentration_pct: float = 30.0


class ComplianceSettings(BaseModel):
    earnings_blackout_hours: float = 24.0
    earnings_blackout_enabled: bool = True
    wash_sale_tracking_enabled: bool = True
    restricted_symbols: list[str] = []


class DataPaths(BaseModel):
    """Mirror of the path constants above; written into settings.yaml so the
    user can see (but not effectively change) where data lives. Treat the
    constants in this module as authoritative."""

    trade_logs_path: str = str(TRADE_LOG_DIR)
    universe_filters_path: str = str(FILTER_PRESET_DIR)
    strategy_configs_path: str = str(STRATEGY_CONFIG_DIR)
    local_db_path: str = str(LOCAL_DB_PATH)


class TradeWindow(BaseModel):
    label: str
    start: str  # HH:MM (ET)
    end: str  # HH:MM (ET)


class ExecutionSettings(BaseModel):
    human_ack_required: bool = True
    human_ack_timeout_minutes: int = 15
    stale_plan_timeout_minutes: int = 30
    default_algo: str = "vwap"
    do_not_trade_windows: list[TradeWindow] = Field(
        default_factory=lambda: [
            TradeWindow(label="open_5min", start="09:30", end="09:35"),
            TradeWindow(label="close_5min", start="15:55", end="16:00"),
        ]
    )
    # Enhanced Live Safeguards — when True (default), every action
    # that touches real money in live mode triggers an explicit
    # "We are in LIVE mode, are you sure..." confirmation prompt.
    # Applied client-side in the JS handlers (approve, close position,
    # activate live account, halt). Setting to False trusts the
    # operator and skips the extra prompt — recommended only after
    # you've used the system in live for a while.
    enhanced_live_safeguards: bool = True


class UniverseUISettings(BaseModel):
    """Operator-controlled UI config for the /universe/{preset} criteria
    panel.

    ``include_fields`` — if non-empty, ONLY these criterion keys appear
    in the panel (other keys are hidden but still in effect on the
    server). Use when you want a tight, opinionated view. Empty / null
    means "show everything present on the preset."

    ``exclude_fields`` — keys to always hide, takes precedence over
    ``include_fields``. Use for fields you never tune.

    ``pinned_fields`` — keys to surface in a top ``Pinned`` group
    regardless of their normal grouping. Order is preserved.
    """

    include_fields: list[str] = Field(default_factory=list)
    exclude_fields: list[str] = Field(default_factory=list)
    pinned_fields: list[str] = Field(default_factory=list)


class UniverseSettings(BaseModel):
    ui: UniverseUISettings = Field(default_factory=UniverseUISettings)


class ChartColors(BaseModel):
    """Operator-defined colors for trade levels drawn on every chart
    (/pending, /trades/{id}). Exposed to the frontend as ``window.CHART_COLORS``
    so the chart code reads these instead of hardcoding hex values.

    ``current_price`` defaults to a bright pink so it never gets confused with
    the green take-profit lines.
    """
    entry: str = "#4a9eff"          # blue
    stop: str = "#ef4444"           # red
    tp1: str = "#22c55e"            # green
    tp2: str = "#16a34a"            # darker green
    current_price: str = "#ff2e97"  # bright pink — distinct from TP green
    discovery: str = "#f59e0b"      # amber — "strategy found the trade here" marker


class Settings(BaseModel):
    app: AppSettings = Field(default_factory=AppSettings)
    ntfy: NtfySettings = Field(default_factory=NtfySettings)
    risk_defaults: RiskDefaults = Field(default_factory=RiskDefaults)
    compliance: ComplianceSettings = Field(default_factory=ComplianceSettings)
    data: DataPaths = Field(default_factory=DataPaths)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    universe: UniverseSettings = Field(default_factory=UniverseSettings)
    chart_colors: ChartColors = Field(default_factory=ChartColors)


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #


def _load_from_disk() -> Settings:
    if SETTINGS_FILE.exists():
        raw = yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8")) or {}
        s = Settings.model_validate(raw)
    else:
        s = Settings()
    # Env override for the public origin — it's deployment/secret config, so it
    # lives in .env (encrypted into config.enc), not settings.yaml.
    import os
    env_url = os.environ.get("PUBLIC_BASE_URL", "").strip()
    if env_url:
        s.app.public_base_url = env_url.rstrip("/")
    return s


@lru_cache(maxsize=1)
def _cached_settings() -> Settings:
    return _load_from_disk()


def get_settings() -> Settings:
    """FastAPI dependency entry point — `Depends(get_settings)`."""
    return _cached_settings()


def reload_settings() -> Settings:
    """Force a re-read of settings.yaml from disk."""
    _cached_settings.cache_clear()
    return _cached_settings()


def save_settings(s: Settings) -> None:
    """Persist settings to disk and invalidate the cache."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        yaml.safe_dump(s.model_dump(mode="python"), sort_keys=False),
        encoding="utf-8",
    )
    _cached_settings.cache_clear()


def ensure_directories() -> None:
    """Create all on-disk directories the app expects. Safe to call repeatedly.
    Run once at app startup (and any time we need to recover from a missing dir).
    """
    for d in (
        TRADE_LOG_DIR,
        FILTER_PRESET_DIR,
        STRATEGY_CONFIG_DIR,
        DATA_DIR,
        LOCAL_LOGS_DIR,
        STATIC_DIR,
        TEMPLATES_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
