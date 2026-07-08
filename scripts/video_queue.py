"""video_queue — derive the mining worklist from the library + _history.json.

The mining loop is checkpointed in research/video_library/_history.json: a video is
"assessed" once it has a status of passed|rejected. Everything ingested (has a
transcript) but not yet assessed is "pending". This helper makes that queue
explicit and deterministic so the loop is resumable on either computer.

  python -m scripts.video_queue --stats     # counts: assessed / pending / passed / rejected
  python -m scripts.video_queue --next      # print the next pending id (blank if none)
  python -m scripts.video_queue --list      # list all pending ids, one per line
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import os
ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "research" / "video_library"
LIB = BASE / os.environ.get("VIDEO_STYLE", "day_intra")   # per-style lane (swing|day_intra|scalp)
HIST = BASE / "_history.json"                             # global across lanes


def load_hist() -> dict:
    try:
        return json.loads(HIST.read_text()) if HIST.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def _ingested(folder: Path) -> bool:
    """A video is ingested if it has a transcript or extracted frames."""
    if (folder / "transcript.md").exists():
        return True
    frames = folder / "frames"
    return frames.is_dir() and any(frames.glob("*.jpg"))


def scan() -> dict:
    hist = load_hist()
    lib_dirs = sorted(
        p.name for p in LIB.iterdir() if p.is_dir() and not p.name.startswith("_")
    )
    passed, rejected, pending, not_ingested = [], [], [], []
    for vid in lib_dirs:
        status = hist.get(vid, {}).get("status")
        if status == "passed":
            passed.append(vid)
        elif status == "rejected":
            rejected.append(vid)
        elif _ingested(LIB / vid):
            pending.append(vid)
        else:
            not_ingested.append(vid)
    return {
        "lib": lib_dirs,
        "passed": passed,
        "rejected": rejected,
        "pending": pending,
        "not_ingested": not_ingested,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--next", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    s = scan()
    if args.next:
        print(s["pending"][0] if s["pending"] else "")
        return
    if args.list:
        print("\n".join(s["pending"]))
        return
    # default / --stats
    assessed = len(s["passed"]) + len(s["rejected"])
    print(f"library:      {len(s['lib'])}")
    print(f"assessed:     {assessed}  (passed {len(s['passed'])} / rejected {len(s['rejected'])})")
    print(f"pending:      {len(s['pending'])}")
    if s["not_ingested"]:
        print(f"not_ingested: {len(s['not_ingested'])}  {s['not_ingested']}")
    if s["pending"]:
        print(f"next:         {s['pending'][0]}")


if __name__ == "__main__":
    main()
