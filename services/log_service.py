"""Append-only JSONL log for TradeRecords — the ML data pool.

CLAUDE.md non-negotiable: every completed trade writes a TradeRecord here.
Open in append mode, write one JSON line, flush, close. Never hold a handle
between writes. Never rewrite a file.

Files are bucketed by month: `trade_logs/YYYY-MM.jsonl`. Bucketing uses
`lifecycle.ts_exited_last` (when the trade finalized) so a trade always
lands in the month it closed in.

API is async (uses `asyncio.to_thread` for the file ops) so it can be
awaited from FastAPI routes without blocking the event loop.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from models import TradeRecord
from services.settings_service import TRADE_LOG_DIR


# --------------------------------------------------------------------------- #
# Internal helpers (sync — wrapped via to_thread by the public API)
# --------------------------------------------------------------------------- #


def _month_key(record: TradeRecord) -> str:
    """YYYY-MM bucket. Prefers lifecycle.ts_exited_last; falls back to UTC now."""
    ts = record.lifecycle.get("ts_exited_last") if isinstance(record.lifecycle, dict) else None
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y-%m")
        except ValueError:
            pass
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _path_for_month(year_month: str) -> Path:
    return TRADE_LOG_DIR / f"{year_month}.jsonl"


def _append_sync(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        if not line.endswith("\n"):
            f.write("\n")
        f.flush()


def _iter_sync(path: Path) -> Iterator[TradeRecord]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield TradeRecord.model_validate_json(line)


def _list_months_sync() -> list[str]:
    if not TRADE_LOG_DIR.exists():
        return []
    return sorted(p.stem for p in TRADE_LOG_DIR.glob("*.jsonl"))


def _count_sync(year_month: str | None) -> int:
    months = [year_month] if year_month else _list_months_sync()
    total = 0
    for ym in months:
        p = _path_for_month(ym)
        if not p.exists():
            continue
        with p.open("r", encoding="utf-8") as f:
            total += sum(1 for line in f if line.strip())
    return total


def _read_sync(year_month: str | None) -> list[TradeRecord]:
    if year_month is not None:
        return list(_iter_sync(_path_for_month(year_month)))
    out: list[TradeRecord] = []
    for ym in _list_months_sync():
        out.extend(_iter_sync(_path_for_month(ym)))
    return out


# --------------------------------------------------------------------------- #
# Public async API
# --------------------------------------------------------------------------- #


async def append_trade_record(record: TradeRecord) -> Path:
    """Append one TradeRecord as a single JSON line. Returns the file written."""
    path = _path_for_month(_month_key(record))
    line = record.model_dump_json()
    await asyncio.to_thread(_append_sync, path, line)
    return path


async def list_months() -> list[str]:
    """Sorted YYYY-MM strings for which a log file exists."""
    return await asyncio.to_thread(_list_months_sync)


async def read_records(year_month: str | None = None) -> list[TradeRecord]:
    """Load all records from one month, or every month if None.
    Loads into memory — fine for v1 single-user scale; revisit if logs grow large."""
    return await asyncio.to_thread(_read_sync, year_month)


async def count_records(year_month: str | None = None) -> int:
    """Line count without parsing. Total across all months if `year_month` is None."""
    return await asyncio.to_thread(_count_sync, year_month)
