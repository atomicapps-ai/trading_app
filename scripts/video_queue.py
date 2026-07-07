"""video_queue — the worklist for the autonomous video-mining loop.

Scans research/video_library/ and reports which ingested videos still need
assessment (have transcript+frames but no pass/reject status in _history.json).
Gives the co-work loop a deterministic "what's next" + progress toward a target.

    python scripts/video_queue.py                 # summary + next pending id
    python scripts/video_queue.py --next          # just the next pending video id
    python scripts/video_queue.py --list          # all pending ids
    python scripts/video_queue.py --stats         # counts as JSON
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "research" / "video_library"
HIST = LIB / "_history.json"


def _history() -> dict:
    try:
        return json.loads(HIST.read_text(encoding="utf-8")) if HIST.exists() else {}
    except Exception:
        return {}


def _has_material(d: Path) -> bool:
    tr = (d / "transcript.md").exists() or (d / "transcript.json").exists()
    frames = (d / "frames").is_dir() and any((d / "frames").glob("*.jpg"))
    return tr and frames


def scan() -> dict:
    hist = _history()
    passed, rejected, pending, no_material = [], [], [], []
    for d in sorted(p for p in LIB.iterdir() if p.is_dir() and not p.name.startswith("_")):
        vid = d.name
        status = (hist.get(vid) or {}).get("status")
        if status == "passed":
            passed.append(vid)
        elif status == "rejected":
            rejected.append(vid)
        elif _has_material(d):
            pending.append(vid)
        else:
            no_material.append(vid)
    return {"passed": passed, "rejected": rejected, "pending": pending,
            "no_material": no_material}


def main() -> None:
    ap = argparse.ArgumentParser(description="Video-mining worklist.")
    ap.add_argument("--next", action="store_true", help="print only the next pending id")
    ap.add_argument("--list", action="store_true", help="print all pending ids")
    ap.add_argument("--stats", action="store_true", help="print counts as JSON")
    args = ap.parse_args()

    s = scan()
    if args.next:
        print(s["pending"][0] if s["pending"] else "")
        return
    if args.list:
        print("\n".join(s["pending"]))
        return
    if args.stats:
        print(json.dumps({k: len(v) for k, v in s.items()}))
        return

    done = len(s["passed"]) + len(s["rejected"])
    print(f"assessed: {done}  (passed {len(s['passed'])} · rejected {len(s['rejected'])})")
    print(f"pending assessment: {len(s['pending'])}")
    print(f"ingested but incomplete (no transcript/frames): {len(s['no_material'])}")
    if s["pending"]:
        nxt = s["pending"][0]
        print(f"\nNEXT: {nxt}")
        print(f"  transcript: research/video_library/{nxt}/transcript.md")
        print(f"  frames:     research/video_library/{nxt}/frames/")


if __name__ == "__main__":
    main()
