"""refresh_universe.py — periodic Finviz scrape → ticker list refresh.

Purpose
-------
The trading pipeline reads its universe from
``universe_filter_presets_tickers.yaml`` (committed to git). This script
is the only thing that writes that file. It:

  1. Loads the preset's filter criteria from ``universe_filter_presets.yaml``
  2. Maps the criteria to Finviz screener URL parameters
  3. Paginates through the Finviz results with a polite delay
  4. Parses the ticker column and backs off on 429/503
  5. Writes the tickers back to ``universe_filter_presets_tickers.yaml``
     while preserving the other presets and their metadata

Infrequent by design. Run it manually when you want to refresh (weekly
is a sensible cadence), then ``git add + git commit`` the result. The
live pipeline never touches Finviz.

Usage
-----
    python -m scripts.refresh_universe liquid_momentum_core
    python -m scripts.refresh_universe --all
    python -m scripts.refresh_universe liquid_momentum_core --max-pages 2 --dry-run

Environment
-----------
    FINVIZ_DELAY_SECONDS     (default 1.5)  delay between requests

Notes
-----
Finviz's free tier doesn't publish a stable API — if they change their
HTML, this script fixes in one place; the live pipeline keeps running
off the last-committed ticker list.

This script is NOT a pure function of its inputs (it talks to the
internet). That's deliberate — the agents are pure; the universe
refresh sits upstream of the pipeline, not inside it.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from bs4 import BeautifulSoup

from services.settings_service import PROJECT_ROOT

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

CRITERIA_FILE = PROJECT_ROOT / "universe_filter_presets.yaml"
TICKERS_FILE = PROJECT_ROOT / "universe_filter_presets_tickers.yaml"

# Presets that don't get refreshed (on-demand or hardcoded)
SKIP_PRESETS = {"sentiment_catalyst", "etf_sector_rotation"}

FINVIZ_BASE = "https://finviz.com/screener.ashx"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
PAGE_SIZE = 20  # Finviz returns 20 rows per page; r= increments by this


# --------------------------------------------------------------------------- #
# Criteria → Finviz filter string
# --------------------------------------------------------------------------- #


def _build_finviz_filters(criteria: dict[str, Any]) -> list[str]:
    """Translate the preset criteria dict into Finviz `f=` parameters.

    Skips criteria we can't map cleanly (fundamentals encoded differently
    across Finviz versions, performance thresholds, etc.). The pre-screener
    re-applies bar-based gates after we fetch the bars anyway, so a
    best-effort mapping is fine here — Finviz's job is to narrow 6000+
    names to ~200, not to be pixel-accurate.
    """
    filters: list[str] = []

    # --- Price band ---
    price_min = criteria.get("price_min")
    price_max = criteria.get("price_max")
    if price_min is not None and price_max is not None:
        filters.append(f"sh_price_{_fmt_range('price', price_min, price_max)}")
    elif price_min is not None:
        filters.append(f"sh_price_o{int(price_min)}")
    elif price_max is not None:
        filters.append(f"sh_price_u{int(price_max)}")

    # --- Avg volume ---
    avg_volume_min = criteria.get("avg_volume_min")
    if avg_volume_min is not None:
        thousands = int(avg_volume_min) // 1000
        filters.append(f"sh_avgvol_o{thousands}")

    # --- Market cap list ---
    caps = criteria.get("market_cap")
    if isinstance(caps, list) and caps:
        # Finviz supports multi: cap_midover, cap_largeover etc. don't quite
        # line up — simplest approach is the OR-prefixed token via `|`
        # which Finviz encodes as URL-safe. We fall back to joining
        # individual `cap_<size>` filters if only one size given.
        if len(caps) == 1:
            filters.append(f"cap_{caps[0]}")
        else:
            filters.append("cap_" + "|".join(caps))

    # --- SMA relations ---
    if criteria.get("sma20_relation") == "above":
        filters.append("ta_sma20_pa")
    elif criteria.get("sma20_relation") == "below":
        filters.append("ta_sma20_pb")
    if criteria.get("sma50_relation") == "above":
        filters.append("ta_sma50_pa")
    elif criteria.get("sma50_relation") == "below":
        filters.append("ta_sma50_pb")
    if criteria.get("sma200_relation") == "above":
        filters.append("ta_sma200_pa")
    elif criteria.get("sma200_relation") == "below":
        filters.append("ta_sma200_pb")

    # --- RSI window ---
    rsi_min = criteria.get("rsi_min")
    rsi_max = criteria.get("rsi_max")
    if rsi_min is not None and rsi_max is not None:
        filters.append(f"ta_rsi_b{int(rsi_min)}o{int(rsi_max)}")

    # --- Exchange whitelist ---
    exchanges = criteria.get("exchange")
    if isinstance(exchanges, list) and exchanges:
        mapping = {"nasdaq": "exch_nasd", "nyse": "exch_nyse", "arcx": "exch_amex"}
        codes = [mapping[e] for e in exchanges if e in mapping]
        if codes:
            filters.append("|".join(codes))

    # --- Profitability flags (best-effort) ---
    if criteria.get("eps_ttm_positive") is True:
        filters.append("fa_eps_pos")
    if criteria.get("roe_positive") is True:
        filters.append("fa_roe_pos")

    return filters


def _fmt_range(kind: str, lo: float, hi: float) -> str:
    """Finviz uses `o{low}to{high}` for some numeric ranges."""
    return f"o{int(lo)}to{int(hi)}"


# --------------------------------------------------------------------------- #
# Scraper
# --------------------------------------------------------------------------- #


def _scrape_preset(
    preset_name: str,
    filters: list[str],
    *,
    max_pages: int = 50,
    delay_seconds: float = 1.5,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[str]:
    """Paginate through Finviz, return deduped ticker list."""
    tickers: list[str] = []
    seen: set[str] = set()
    filter_str = ",".join(filters)
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})

    for page in range(max_pages):
        row_offset = page * PAGE_SIZE + 1  # Finviz is 1-indexed
        params = {"v": "111", "r": str(row_offset)}
        if filter_str:
            params["f"] = filter_str

        html = _get_with_retry(session, FINVIZ_BASE, params)
        page_tickers = _parse_ticker_column(html)
        if not page_tickers:
            logger.info("  page %d: no tickers — stopping pagination", page + 1)
            break
        new = [t for t in page_tickers if t not in seen]
        for t in new:
            seen.add(t)
            tickers.append(t)
        logger.info(
            "  page %d (r=%d): +%d tickers (total %d)",
            page + 1, row_offset, len(new), len(tickers),
        )
        if len(page_tickers) < PAGE_SIZE:
            # Short page → end of result set
            break
        time.sleep(delay_seconds)

    return tickers


def _get_with_retry(
    session: requests.Session, url: str, params: dict,
    max_retries: int = 3,
) -> str:
    """GET with exponential backoff on 429 / 503."""
    for attempt in range(max_retries + 1):
        resp = session.get(url, params=params, timeout=20)
        if resp.status_code == 200:
            return resp.text
        if resp.status_code in (429, 503):
            backoff = 2 ** attempt
            logger.warning(
                "  HTTP %d — backing off %ds (attempt %d/%d)",
                resp.status_code, backoff, attempt + 1, max_retries + 1,
            )
            time.sleep(backoff)
            continue
        resp.raise_for_status()
    raise RuntimeError(f"Finviz GET failed after {max_retries + 1} attempts")


_TICKER_HREF_RE = re.compile(r"quote\.ashx\?t=([A-Z][A-Z0-9\.\-]{0,9})")


def _parse_ticker_column(html: str) -> list[str]:
    """Extract deduped ticker list from the screener results table.

    Finviz (as of 2026-04) drops the `screener-link-primary` class name
    and places tickers inside anchors of the form
    ``<a href="quote.ashx?t=TICKER&...">TICKER</a>`` within the table
    ``class="styled-table-new ... screener_table"``. We scope to that
    table to skip navigation links and dedupe preserving page order.
    """
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
        if sym in seen:
            continue
        seen.add(sym)
        tickers.append(sym)
    return tickers


# --------------------------------------------------------------------------- #
# YAML persistence
# --------------------------------------------------------------------------- #


def _load_criteria_file() -> dict[str, dict]:
    """Return {preset_name: full_doc_dict} across every doc in the YAML."""
    text = CRITERIA_FILE.read_text(encoding="utf-8")
    out: dict[str, dict] = {}
    for doc in yaml.safe_load_all(text):
        if isinstance(doc, dict) and doc.get("preset_name"):
            out[doc["preset_name"]] = doc
    return out


def _load_tickers_file() -> dict[str, Any]:
    if not TICKERS_FILE.exists():
        return {"presets": {}}
    text = TICKERS_FILE.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if "presets" not in data:
        data["presets"] = {}
    return data


def _save_tickers_file(data: dict[str, Any]) -> None:
    TICKERS_FILE.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def refresh_one(
    preset_name: str,
    criteria_docs: dict[str, dict],
    tickers_data: dict[str, Any],
    *,
    delay_seconds: float,
    max_pages: int,
    dry_run: bool,
) -> list[str]:
    if preset_name in SKIP_PRESETS:
        logger.info("Skipping %s (on-demand / hardcoded preset)", preset_name)
        return []
    if preset_name not in criteria_docs:
        logger.error("No criteria for preset %r in %s", preset_name, CRITERIA_FILE)
        return []
    doc = criteria_docs[preset_name]
    criteria = doc.get("criteria", {}) or {}
    filters = _build_finviz_filters(criteria)
    logger.info(
        "Refreshing %s — %d Finviz filter tokens: %s",
        preset_name, len(filters), ",".join(filters),
    )
    tickers = _scrape_preset(
        preset_name, filters,
        max_pages=max_pages,
        delay_seconds=delay_seconds,
    )
    logger.info("  -> %d unique tickers", len(tickers))

    if dry_run:
        logger.info("  dry-run: not writing to disk")
        return tickers

    tickers_data["presets"][preset_name] = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "source": f"finviz:{','.join(filters)}" if filters else "finviz:no_filters",
        "tickers": tickers,
    }
    return tickers


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh preset ticker lists from Finviz.")
    parser.add_argument(
        "preset", nargs="?",
        help="Preset name to refresh. Omit + pass --all to refresh all eligible.",
    )
    parser.add_argument("--all", action="store_true", help="Refresh every eligible preset.")
    parser.add_argument("--dry-run", action="store_true", help="Scrape but don't write the YAML.")
    parser.add_argument("--max-pages", type=int, default=50, help="Max Finviz pages to fetch per preset.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.preset and not args.all:
        parser.error("must specify a preset name or --all")

    delay = float(os.getenv("FINVIZ_DELAY_SECONDS", "1.5"))
    criteria_docs = _load_criteria_file()
    tickers_data = _load_tickers_file()

    targets: list[str]
    if args.all:
        targets = [
            name for name in criteria_docs
            if name not in SKIP_PRESETS
        ]
    else:
        targets = [args.preset]

    for preset_name in targets:
        try:
            refresh_one(
                preset_name, criteria_docs, tickers_data,
                delay_seconds=delay,
                max_pages=args.max_pages,
                dry_run=args.dry_run,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to refresh %s: %s", preset_name, e)

    if not args.dry_run:
        _save_tickers_file(tickers_data)
        logger.info("Wrote %s", TICKERS_FILE)

    return 0


if __name__ == "__main__":
    sys.exit(main())
