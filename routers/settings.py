"""Settings router — read settings.yaml, render form, persist edits.

The form covers the most-edited fields (app/ntfy/risk_defaults/compliance);
fields not in the form (host, priority_map, execution windows, data paths)
are preserved as-is. Anything mission-critical can be edited in the YAML
directly and reloaded.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services.settings_service import (
    LOCAL_DB_PATH,
    SETTINGS_FILE,
    STRATEGY_CONFIG_DIR,
    TEMPLATES_DIR,
    TRADE_LOG_DIR,
    FILTER_PRESET_DIR,
    Settings,
    get_settings,
    reload_settings,
    save_settings,
)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _last_saved_ts() -> str | None:
    if not SETTINGS_FILE.exists():
        return None
    return datetime.fromtimestamp(SETTINGS_FILE.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, s: Settings = Depends(get_settings)):
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "settings",
            "paths": {
                "settings_file": str(SETTINGS_FILE),
                "trade_logs": str(TRADE_LOG_DIR),
                "universe_filters": str(FILTER_PRESET_DIR),
                "strategy_configs": str(STRATEGY_CONFIG_DIR),
                "local_db": str(LOCAL_DB_PATH),
            },
            "last_saved": _last_saved_ts(),
        },
    )


@router.post("/settings", response_class=HTMLResponse)
async def settings_save(
    request: Request,
    # App
    mode: str = Form(...),
    port: int = Form(...),
    tailscale_hostname: str = Form(...),
    # Risk defaults
    max_risk_pct_per_trade: float = Form(...),
    max_position_pct_of_equity: float = Form(...),
    max_daily_loss_pct: float = Form(...),
    max_open_positions: int = Form(...),
    max_daily_trades: int = Form(...),
    min_rr_ratio: float = Form(...),
    participation_cap_pct_adv: float = Form(...),
    max_spread_bps_to_cross: float = Form(...),
    max_sector_concentration_pct: float = Form(...),
    # Compliance
    earnings_blackout_hours: float = Form(...),
    earnings_blackout_enabled: bool = Form(False),
    wash_sale_tracking_enabled: bool = Form(False),
    restricted_symbols: str = Form(""),
    # Notifications
    ntfy_server: str = Form(...),
    ntfy_topic: str = Form(...),
):
    current = get_settings().model_copy(deep=True)

    current.app.mode = mode  # type: ignore[assignment]
    current.app.port = port
    current.app.tailscale_hostname = tailscale_hostname

    current.risk_defaults.max_risk_pct_per_trade = max_risk_pct_per_trade
    current.risk_defaults.max_position_pct_of_equity = max_position_pct_of_equity
    current.risk_defaults.max_daily_loss_pct = max_daily_loss_pct
    current.risk_defaults.max_open_positions = max_open_positions
    current.risk_defaults.max_daily_trades = max_daily_trades
    current.risk_defaults.min_rr_ratio = min_rr_ratio
    current.risk_defaults.participation_cap_pct_adv = participation_cap_pct_adv
    current.risk_defaults.max_spread_bps_to_cross = max_spread_bps_to_cross
    current.risk_defaults.max_sector_concentration_pct = max_sector_concentration_pct

    current.compliance.earnings_blackout_hours = earnings_blackout_hours
    current.compliance.earnings_blackout_enabled = earnings_blackout_enabled
    current.compliance.wash_sale_tracking_enabled = wash_sale_tracking_enabled
    current.compliance.restricted_symbols = [
        line.strip().upper()
        for line in restricted_symbols.splitlines()
        if line.strip()
    ]

    current.ntfy.server = ntfy_server
    current.ntfy.topic = ntfy_topic

    save_settings(current)
    reload_settings()

    return templates.TemplateResponse(
        request=request,
        name="settings/_save_status.html",
        context={"ok": True, "msg": "Settings saved.", "last_saved": _last_saved_ts()},
    )


@router.post("/api/ntfy/test", response_class=HTMLResponse)
async def ntfy_test():
    """Stub — real ntfy dispatch arrives in Phase 5."""
    return HTMLResponse(
        '<span class="toast toast-ok">Notification sent (stub — ntfy_service in Phase 5).</span>'
    )
