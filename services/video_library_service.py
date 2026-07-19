"""video_library_service.py — data layer for the Video Mining UI.

Surfaces the YouTube research library (``research/video_library/``) so the
operator can see every video mined, which have been reviewed (passed/rejected),
which are pending, and add more.

Source of truth for review status is ``_history.json`` (keyed by video id):
    {id: {url, status, reason, processed_at, duration_s, frames, transcript}}
On-disk video dirs (nested under style lanes like ``day_intra/`` / ``swing/``)
add the lane + "is it ingested" state.

Adding a video runs ``scripts.video_ingest`` as a background subprocess (yt-dlp),
best-effort — the app is local, so this drives the real pipeline.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from pathlib import Path

from services.settings_service import PROJECT_ROOT

logger = logging.getLogger(__name__)

LIB = PROJECT_ROOT / "research" / "video_library"
HIST = LIB / "_history.json"
_VID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")

# In-memory state for the most recent add/ingest run (single-worker app).
_ADD: dict = {"run": None}


def parse_video_id(url: str) -> str | None:
    url = (url or "").strip()
    m = _URL_ID.search(url)
    if m:
        return m.group(1)
    if _VID_RE.match(url):
        return url
    return None


def _load_hist() -> dict:
    try:
        return json.loads(HIST.read_text()) if HIST.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def _disk_index() -> dict[str, dict]:
    """Map video_id -> {lane, ingested} by walking the library (2 levels)."""
    out: dict[str, dict] = {}
    if not LIB.exists():
        return out

    def _scan(base: Path, lane: str) -> None:
        for p in base.iterdir():
            if not p.is_dir() or p.name.startswith("_"):
                continue
            if _VID_RE.match(p.name):
                ingested = (p / "transcript.md").exists() or (
                    (p / "frames").is_dir() and any((p / "frames").glob("*.jpg")))
                out[p.name] = {"lane": lane, "ingested": ingested}
            else:
                _scan(p, p.name)   # a style-lane dir (day_intra, swing, …)

    _scan(LIB, "root")
    return out


def load_library() -> list[dict]:
    """Every known video — merged history + disk — newest activity first."""
    hist = _load_hist()
    disk = _disk_index()
    ids = set(hist) | set(disk)
    rows: list[dict] = []
    for vid in ids:
        h = hist.get(vid, {})
        d = disk.get(vid, {})
        status = h.get("status")
        if not status:
            status = "pending" if d.get("ingested") else "new"
        rows.append({
            "id": vid,
            "url": h.get("url") or f"https://www.youtube.com/watch?v={vid}",
            "status": status,                       # passed | rejected | pending | new
            "reason": h.get("reason") or "",
            "lane": d.get("lane") or h.get("style") or "—",
            "ingested": bool(d.get("ingested") or h.get("transcript")),
            "frames": h.get("frames") or 0,
            "duration_s": h.get("duration_s") or 0,
            "processed_at": h.get("processed_at") or "",
        })
    rows.sort(key=lambda r: r.get("processed_at") or "", reverse=True)
    return rows


def summary(rows: list[dict]) -> dict:
    by = {"passed": 0, "rejected": 0, "pending": 0, "new": 0}
    for r in rows:
        by[r["status"]] = by.get(r["status"], 0) + 1
    return {
        "total": len(rows),
        "reviewed": by["passed"] + by["rejected"],
        "passed": by["passed"],
        "rejected": by["rejected"],
        "pending": by["pending"],
        "new": by["new"],
        "ingested": sum(1 for r in rows if r["ingested"]),
    }


# ----------------------------------------------------------------------- #
# Add a video — run scripts.video_ingest as a background subprocess
# ----------------------------------------------------------------------- #


def add_status() -> dict | None:
    return _ADD["run"]


def is_adding() -> bool:
    run = _ADD["run"]
    return bool(run and run.get("status") == "running")


async def add_video(url: str, *, transcript_only: bool = True,
                    lane: str = "swing") -> dict:
    """Kick off ingestion of one YouTube URL. Returns the run record."""
    vid = parse_video_id(url)
    if not vid:
        return {"status": "error", "error": "could not parse a YouTube video id"}
    if is_adding():
        return _ADD["run"]

    _ADD["run"] = {"status": "running", "video_id": vid, "url": url.strip(),
                   "lane": lane, "line": "starting…", "returncode": None}
    asyncio.create_task(_run_ingest(vid, url.strip(), transcript_only, lane))
    return _ADD["run"]


async def _run_ingest(vid: str, url: str, transcript_only: bool, lane: str) -> None:
    run = _ADD["run"]
    cmd = [sys.executable, "-m", "scripts.video_ingest", url, "--ingest", "--style", lane]
    if transcript_only:
        cmd.append("--no-frames")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(PROJECT_ROOT),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        last = ""
        assert proc.stdout is not None
        async for raw in proc.stdout:
            last = raw.decode(errors="ignore").rstrip()
            if last:
                run["line"] = last[:300]
        await proc.wait()
        run["returncode"] = proc.returncode
        run["status"] = "done" if proc.returncode == 0 else "error"
        if proc.returncode != 0 and not run.get("error"):
            run["error"] = last[:300] or f"ingest exited {proc.returncode}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("video ingest failed for %s: %s", vid, exc)
        run["status"] = "error"
        run["error"] = f"{type(exc).__name__}: {exc}"
