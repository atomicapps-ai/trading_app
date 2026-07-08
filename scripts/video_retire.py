"""video_retire — close out a processed video and reclaim disk.

After a video is assessed, retire it:
  * status=passed   -> keep everything (it's in use).
  * status=rejected -> delete the heavy artifacts (_video.mp4, frames/, transcript.json,
    meta.json) and keep a lightweight record: notes.md (the verdict/spec) + status.json.
    The folder + history entry remain so the video is NEVER re-ingested, and you always
    have a "we tried this, here's why it failed" note.

(transcript.md is kept ONLY if there's no notes.md yet, so the folder never goes empty.)

    python scripts/video_retire.py <id> --status rejected --reason "coin-flip on daily; PF 1.0"
    python scripts/video_retire.py <id> --status passed
    python scripts/video_retire.py --all-rejected            # prune every history-rejected video
"""
from __future__ import annotations
import argparse, json, os, shutil, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "research" / "video_library"
LIB = BASE / os.environ.get("VIDEO_STYLE", "day_intra")   # per-style lane (swing|day_intra|scalp)
HIST = BASE / "_history.json"                             # global across lanes


def load_hist() -> dict:
    try:
        return json.loads(HIST.read_text()) if HIST.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def save_hist(h: dict) -> None:
    HIST.write_text(json.dumps(h, indent=2))


def _dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def retire(vid: str, status: str, reason: str) -> int:
    folder = LIB / vid
    if not folder.is_dir():
        print(f"  (missing) {vid}")
        return 0
    now = datetime.now(timezone.utc).isoformat()
    hist = load_hist()
    h = hist.get(vid, {})
    h.update({"status": status, "reason": reason, "retired_at": now})
    hist[vid] = h
    save_hist(hist)
    (folder / "status.json").write_text(json.dumps(
        {"video_id": vid, "status": status, "reason": reason, "retired_at": now}, indent=2))

    if status != "rejected":
        print(f"  {vid}: marked {status} — keeping all artifacts.")
        return 0

    freed = 0
    # heavy dirs
    frames = folder / "frames"
    if frames.exists():
        freed += _dir_size(frames)
        shutil.rmtree(frames, ignore_errors=True)
    # heavy / metadata files (keep notes.md; keep transcript.md only if no notes.md)
    delete = ["_video.mp4", "transcript.json", "meta.json"]
    if not (folder / "notes.md").exists():
        pass  # keep transcript.md as the record
    else:
        delete.append("transcript.md")
    for name in delete:
        f = folder / name
        if f.exists():
            freed += f.stat().st_size
            f.unlink()
    print(f"  {vid}: REJECTED — freed {freed/1e6:.1f} MB, kept "
          f"{'notes.md' if (folder/'notes.md').exists() else 'transcript.md'} + status.json")
    return freed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("vid", nargs="?", help="video id")
    ap.add_argument("--status", default="rejected", choices=["rejected", "passed"])
    ap.add_argument("--reason", default="")
    ap.add_argument("--all-rejected", action="store_true",
                    help="prune every video already marked rejected in history")
    args = ap.parse_args()

    total = 0
    if args.all_rejected:
        hist = load_hist()
        targets = [v for v, h in hist.items() if h.get("status") == "rejected"]
        if not targets:
            print("no history-rejected videos to prune.")
            return
        for v in targets:
            total += retire(v, "rejected", load_hist().get(v, {}).get("reason", ""))
    elif args.vid:
        total = retire(args.vid, args.status, args.reason)
    else:
        sys.exit("provide a video id, or --all-rejected")
    print(f"\nReclaimed {total/1e6:.1f} MB total.")


if __name__ == "__main__":
    main()
