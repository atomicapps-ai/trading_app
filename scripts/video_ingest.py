"""video_ingest — two-phase YouTube ingest for the strategy research library.

The research firewall can't reach YouTube, so YOU run this (it has internet); it saves
everything into the repo where the analysis side can read the transcript and view the
frames.

WORKFLOW
  Phase 1 — transcript:
      python scripts/video_ingest.py "https://youtu.be/VIDEOID"
    → saves research/video_library/<id>/transcript.md (+ .json, meta.json)
    → I read the transcript and reply with the timestamps worth snapshotting.

  Phase 2 — frames at the timestamps I give you:
      python scripts/video_ingest.py "https://youtu.be/VIDEOID" --frames 120,355,610
    → saves research/video_library/<id>/frames/frame_00120s.jpg ...
    → I view the frames and write up the testable hypotheses in notes.md.

DEPENDENCIES (install once, on your machine):
    pip install youtube-transcript-api yt-dlp
    + ffmpeg on PATH (winget install Gyan.FFmpeg  /  choco install ffmpeg)

Notes: transcript-only is light and fast (no video download). Frames stream-seek the
video at low res, so they're cheap too. For personal research/education use.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import os
BASE = PROJECT_ROOT / "research" / "video_library"          # global _history.json lives here
LIB = BASE / os.environ.get("VIDEO_STYLE", "day_intra")     # per-style lane (swing|day_intra|scalp)
LIB.mkdir(parents=True, exist_ok=True)

# Optional Netscape cookies.txt (exported from a signed-in browser) to bypass
# YouTube's "confirm you're not a bot" gate + caption IP-blocks. Set via --cookies.
_COOKIES: str | None = None


def _cookie_args() -> list[str]:
    return ["--cookies", _COOKIES] if _COOKIES else []


def video_id(url: str) -> str:
    url = url.strip()
    for pat in (r"v=([A-Za-z0-9_-]{11})", r"youtu\.be/([A-Za-z0-9_-]{11})",
                r"shorts/([A-Za-z0-9_-]{11})", r"embed/([A-Za-z0-9_-]{11})"):
        m = re.search(pat, url)
        if m:
            return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    raise SystemExit(f"Could not parse a video id from: {url}")


def fetch_transcript(vid: str):
    """Return list of {text,start,duration}; works across youtube-transcript-api versions.
    Tries manual+generated English, then any available/translatable transcript, and raises a
    clear reason instead of masking it behind a removed-method AttributeError."""
    from youtube_transcript_api import YouTubeTranscriptApi
    langs = ["en", "en-US", "en-GB"]
    last = None

    # --- new API (>=1.0): instance methods fetch()/list(); FetchedTranscript.to_raw_data()
    try:
        api = YouTubeTranscriptApi()
    except TypeError:
        api = None
    if api is not None and hasattr(api, "fetch"):
        try:
            return api.fetch(vid, languages=langs).to_raw_data()
        except Exception as e:
            last = e
        try:
            tl = api.list(vid)
            try:
                return tl.find_transcript(langs).fetch().to_raw_data()
            except Exception as e:
                last = e
            for t in tl:                       # any language, manual or generated
                try:
                    return t.fetch().to_raw_data()
                except Exception as e:
                    last = e
        except Exception as e:
            last = e

    # --- old API (<=0.6): classmethods
    if hasattr(YouTubeTranscriptApi, "get_transcript"):
        try:
            return YouTubeTranscriptApi.get_transcript(vid, languages=langs)
        except Exception as e:
            last = e
        try:
            for t in YouTubeTranscriptApi.list_transcripts(vid):
                try:
                    return t.fetch()
                except Exception as e:
                    last = e
        except Exception as e:
            last = e

    raise RuntimeError(f"no fetchable transcript (captions likely disabled): {type(last).__name__ if last else 'unknown'}")


def hhmmss(sec: float) -> str:
    s = int(sec); return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


def _vtt_seconds(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts; return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts; return int(m) * 60 + float(s)
    except ValueError:
        return 0.0
    return 0.0


def ytdlp_subs(url: str, folder: Path) -> list[dict]:
    """Fallback when the transcript API is IP-blocked: pull captions via yt-dlp
    (a different endpoint YouTube blocks far less), parse the .vtt into rows."""
    folder.mkdir(parents=True, exist_ok=True)
    tmpl = str(folder / "_sub.%(ext)s")
    cmd = ["yt-dlp", "--remote-components", "ejs:github", *_cookie_args(),
           "--skip-download",
           "--write-auto-subs", "--write-subs", "--sub-langs", "en,en-US,en-orig",
           "--sub-format", "vtt", "--no-playlist", "-o", tmpl, url]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    except subprocess.TimeoutExpired:
        return []
    vtts = sorted(folder.glob("_sub*.vtt"), key=lambda p: p.stat().st_size, reverse=True)
    if not vtts:
        return []
    # largest file = the fullest English track (translations come back smaller)
    rows: list[dict] = []
    seen_last = None
    import re as _re
    for raw in vtts[0].read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if "-->" in line:
            cur_start = _vtt_seconds(line.split("-->")[0])
            continue
        if not line or line in ("WEBVTT",) or line.startswith(("Kind:", "Language:", "NOTE")):
            continue
        text = _re.sub(r"<[^>]+>", "", line).strip()        # strip inline timing tags
        if not text or text == seen_last:
            continue
        if rows and rows[-1]["start"] == locals().get("cur_start", 0.0):
            rows[-1]["text"] += " " + text
        else:
            rows.append({"text": text, "start": locals().get("cur_start", 0.0), "duration": 0})
        seen_last = text
    for k in range(len(rows) - 1):
        rows[k]["duration"] = max(0.0, rows[k + 1]["start"] - rows[k]["start"])
    for _v in folder.glob("_sub*.vtt"):
        try:
            _v.unlink()
        except OSError:
            pass
    return rows


def do_transcript(url: str, vid: str, folder: Path) -> None:
    # With cookies, the yt-dlp caption path is authenticated (bypasses the
    # timedtext IP-block), so prefer it over the cookieless transcript API.
    if _COOKIES:
        rows = ytdlp_subs(url, folder)
        if not rows:
            try:
                rows = fetch_transcript(vid)
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"cookie caption + API both failed: {e}")
    else:
      try:
        rows = fetch_transcript(vid)
      except Exception as e:  # noqa: BLE001 — API blocked/unavailable -> try yt-dlp captions
        print(f"  transcript API failed ({e}); trying yt-dlp captions ...")
        rows = ytdlp_subs(url, folder)
        if not rows:
            raise
        print(f"  recovered {len(rows)} caption lines via yt-dlp")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "transcript.json").write_text(json.dumps(rows, indent=2))
    md = [f"# Transcript — {vid}", f"<{url}>", ""]
    for r in rows:
        md.append(f"[{hhmmss(r['start'])} | {int(r['start'])}s] {r['text']}")
    (folder / "transcript.md").write_text("\n".join(md))
    (folder / "meta.json").write_text(json.dumps(
        {"url": url, "video_id": vid, "fetched_at": datetime.now(timezone.utc).isoformat(),
         "duration_s": int(rows[-1]["start"] + rows[-1].get("duration", 0)) if rows else 0,
         "lines": len(rows)}, indent=2))
    print(f"Transcript saved: {folder/'transcript.md'}  ({len(rows)} lines, "
          f"~{int(rows[-1]['start'])//60} min)")
    print("Next: share the transcript; I'll reply with frame timestamps, then run "
          f"--frames <list>.")


def stream_url(url: str) -> str:
    out = subprocess.check_output(
        ["yt-dlp", "--remote-components", "ejs:github", *_cookie_args(),
         "-f", "bestvideo[height<=720][ext=mp4]/best[height<=720]/best",
         "-g", url], text=True, timeout=120)
    return out.strip().splitlines()[0]


def do_frames(url: str, vid: str, folder: Path, seconds: list[int],
              keep_video: bool = False) -> None:
    import shutil
    if shutil.which("ffmpeg") is None:
        raise SystemExit(
            "ffmpeg not found on PATH. Install it and reopen the terminal:\n"
            "    winget install Gyan.FFmpeg\n"
            "then verify with:  ffmpeg -version")
    frames = folder / "frames"; frames.mkdir(parents=True, exist_ok=True)
    # idempotent: skip frames already captured (so re-runs only fill gaps)
    todo = [t for t in seconds if not (frames / f"frame_{t:05d}s.jpg").exists()]
    if not todo:
        print(f"  all {len(seconds)} frames already present in {frames}")
        return
    # Download the video ONCE to a local mp4, then seek it locally. Remote
    # stream-seeking times out under YouTube throttling; local seeking is instant.
    mp4 = folder / "_video.mp4"
    if not mp4.exists():
        print("Downloading video (one-time) for local frame extraction ...")
        dl = ["yt-dlp", "--remote-components", "ejs:github", *_cookie_args(),
              "-f", "best[height<=720][ext=mp4]/best[height<=720]/best",
              "--no-playlist", "-o", str(mp4), url]
        try:
            r = subprocess.run(dl, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=900)
        except subprocess.TimeoutExpired:
            print("  download timed out (>15min) — skipping frames (transcript saved)")
            return
        if r.returncode != 0 or not mp4.exists():
            print("  download failed — skipping frames (transcript saved). "
                  "Check yt-dlp / a JS runtime (winget install DenoLand.Deno).")
            return

    print(f"Extracting {len(todo)} frames from local video ...")
    for t in todo:
        out = frames / f"frame_{t:05d}s.jpg"
        cmd = ["ffmpeg", "-y", "-ss", str(t), "-i", str(mp4),
               "-frames:v", "1", "-q:v", "2", str(out)]
        try:
            r = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30)
            ok = out.exists() and r.returncode == 0
        except subprocess.TimeoutExpired:
            ok = False
        print(f"  {hhmmss(t)} -> {out.name}  {'ok' if ok else 'FAILED'}")

    if not keep_video:
        try:
            mp4.unlink()
        except Exception:  # noqa: BLE001
            pass
    print(f"Frames saved in {frames}")


def expand_urls(items: list[str]) -> list[str]:
    """Flatten a list that may contain comma/space/newline-delimited URLs."""
    out = []
    for it in items:
        for part in re.split(r"[,\s]+", it.strip()):
            if part:
                out.append(part)
    return out


def do_manifest(path: str) -> None:
    """Batch-grab frames for many videos from a JSON map {id-or-url: [seconds, ...]}."""
    data = json.loads(Path(path).read_text())
    for key, secs in data.items():
        vid = video_id(key)
        url = key if "http" in key else f"https://www.youtube.com/watch?v={vid}"
        folder = LIB / vid
        if not (folder / "transcript.md").exists():
            do_transcript(url, vid, folder)
        do_frames(url, vid, folder, [int(float(s)) for s in secs])


# --------------------------------------------------------------------------- #
# One-command ingest: transcript + auto-frames, with duplicate detection
# --------------------------------------------------------------------------- #

HISTORY_FILE = BASE / "_history.json"   # global across all style lanes


def load_history() -> dict:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_history(h: dict) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(h, indent=2))


def _duration_for(folder: Path) -> int:
    m = folder / "meta.json"
    if m.exists():
        try:
            return int(json.loads(m.read_text()).get("duration_s", 0))
        except Exception:  # noqa: BLE001
            return 0
    return 0


def do_ingest(urls: list[str], interval: int = 90, force: bool = False,
              keep_video: bool = False, sleep_s: float = 0.0,
              no_frames: bool = False) -> None:
    """End-to-end: for each NEW url, save transcript + (optionally) auto-extract frames
    at even intervals. Skips any video already in the history (or with a transcript
    on disk) unless --force. The history file is the record of what's been run.

    Anti-block: sleep_s is the BASE pause between videos; actual pause is randomized
    jitter in [0.6, 1.6]x to look less bot-like. --no-frames keeps footprint light
    (transcript-only = one lightweight caption request; frames stream the video via
    yt-dlp and are the heavier, more block-prone call)."""
    import time, random
    hist = load_history()
    done = skipped = 0
    for url in urls:
        try:
            vid = video_id(url)
        except SystemExit as e:
            print(f"  bad url {url!r}: {e}")
            continue
        folder = LIB / vid
        # "done" only if a prior run actually produced a transcript — a failed
        # attempt (transcript:false, no transcript.md) must NOT block a retry.
        prior_ok = bool(hist.get(vid, {}).get("transcript")) or (folder / "transcript.md").exists()
        already = prior_ok
        if already and not force:
            print(f"SKIP (already ingested): {vid}")
            skipped += 1
            continue

        print(f"\n=== ingesting {vid} ===")
        if not (folder / "transcript.md").exists():
            try:
                do_transcript(url, vid, folder)
            except Exception as e:  # noqa: BLE001
                print(f"  transcript failed: {e}")

        dur = _duration_for(folder)
        if no_frames:
            secs = []
        elif dur > 45:
            secs = list(range(30, dur - 15, max(15, interval)))
        elif dur:
            secs = [max(1, dur // 2)]
        else:
            secs = []
        if secs:
            do_frames(url, vid, folder, secs, keep_video=keep_video)

        frames_dir = folder / "frames"
        nframes = len(list(frames_dir.glob("*.jpg"))) if frames_dir.exists() else 0
        hist[vid] = {
            "url": url,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "duration_s": dur,
            "frames": nframes,
            "transcript": (folder / "transcript.md").exists(),
        }
        save_history(hist)
        done += 1
        if sleep_s > 0:
            time.sleep(random.uniform(0.6 * sleep_s, 1.6 * sleep_s))   # jittered pacing

    print(f"\nIngested {done}, skipped {skipped} duplicate(s). "
          f"Library: research/video_library/  ·  history: {HISTORY_FILE.name}")


def do_backfill(interval: int = 90, force: bool = False, keep_video: bool = False) -> None:
    """Re-extract frames for every library video that has a transcript but NO
    frames (e.g. ingested before the local-download fix). With --force, re-do
    even videos that already have frames. URL comes from each folder's meta.json."""
    hist = load_history()
    checked = fixed = 0
    for folder in sorted(LIB.iterdir()):
        if not folder.is_dir() or not (folder / "transcript.md").exists():
            continue
        vid = folder.name
        frames_dir = folder / "frames"
        nframes = len(list(frames_dir.glob("*.jpg"))) if frames_dir.exists() else 0
        if nframes > 0 and not force:
            continue
        checked += 1
        url = f"https://www.youtube.com/watch?v={vid}"
        meta = folder / "meta.json"
        if meta.exists():
            try:
                url = json.loads(meta.read_text()).get("url") or url
            except Exception:  # noqa: BLE001
                pass
        dur = _duration_for(folder)
        if dur > 45:
            secs = list(range(30, dur - 15, max(15, interval)))
        elif dur:
            secs = [max(1, dur // 2)]
        else:
            print(f"SKIP {vid}: unknown duration (no meta.json)")
            continue
        print(f"\n=== backfilling {vid} (has {nframes} frames -> extracting {len(secs)}) ===")
        do_frames(url, vid, folder, secs, keep_video=keep_video)
        nframes2 = len(list(frames_dir.glob("*.jpg"))) if frames_dir.exists() else 0
        hist[vid] = {"url": url, "processed_at": datetime.now(timezone.utc).isoformat(),
                     "duration_s": dur, "frames": nframes2, "transcript": True}
        save_history(hist)
        if nframes2 > 0:
            fixed += 1
    print(f"\nBackfill: {checked} video(s) needed frames, {fixed} now have them.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest YouTube videos into the research library")
    ap.add_argument("urls", nargs="*", help="one or more YouTube URLs (space/comma/newline delimited)")
    ap.add_argument("--ingest", action="store_true",
                    help="ONE COMMAND: transcript + auto-frames for each url, skipping duplicates")
    ap.add_argument("--interval", type=int, default=90,
                    help="seconds between auto-extracted frames in --ingest mode (default 90)")
    ap.add_argument("--force", action="store_true",
                    help="re-ingest even if the video is already in the history")
    ap.add_argument("--keep-video", action="store_true",
                    help="keep the downloaded _video.mp4 instead of deleting it after frames")
    ap.add_argument("--sleep", type=float, default=0.0,
                    help="seconds to pause between processed videos (rate-limit safety)")
    ap.add_argument("--cookies", default=None,
                    help="path to a Netscape cookies.txt (bypasses bot-check + caption IP-block)")
    ap.add_argument("--backfill", action="store_true",
                    help="re-extract frames for every library video that has a transcript but no frames")
    ap.add_argument("--frames", help="single video: comma-separated seconds, e.g. 120,355,610")
    ap.add_argument("--frames-file", help="single video: text file, one timestamp (seconds) per line")
    ap.add_argument("--frames-manifest", help="JSON {video: [seconds,...]} — batch frames for many videos")
    ap.add_argument("--no-frames", action="store_true",
                    help="transcript-only ingest (light footprint; skip frame extraction to avoid IP-blocks)")
    ap.add_argument("--style", choices=["swing", "day_intra", "scalp"],
                    help="library lane (overrides VIDEO_STYLE env; video dirs saved here, history global)")
    args = ap.parse_args()

    if getattr(args, "style", None):
        global LIB
        LIB = BASE / args.style
        LIB.mkdir(parents=True, exist_ok=True)

    global _COOKIES
    if getattr(args, "cookies", None):
        _COOKIES = args.cookies
        print(f"Using cookies file: {_COOKIES}")

    # Phase 2 (batch): grab frames for many videos from a manifest I write for you.
    if args.frames_manifest:
        do_manifest(args.frames_manifest)
        return

    # Backfill: re-extract frames for any video missing them (no URLs needed).
    if args.backfill:
        do_backfill(interval=args.interval, force=args.force, keep_video=args.keep_video)
        return

    # One-command ingest (transcript + auto-frames + dedupe).
    if args.ingest:
        urls = expand_urls(args.urls)
        if not urls:
            raise SystemExit("Provide one or more YouTube URLs with --ingest.")
        do_ingest(urls, interval=args.interval, force=args.force,
                  keep_video=args.keep_video, sleep_s=args.sleep, no_frames=args.no_frames)
        return

    urls = expand_urls(args.urls)
    if not urls:
        raise SystemExit("Provide one or more YouTube URLs, or --frames-manifest <file>.")

    # Phase 2 (single video): explicit frames for one url.
    if args.frames or args.frames_file:
        url = urls[0]; vid = video_id(url); folder = LIB / vid
        raw = args.frames.split(",") if args.frames else Path(args.frames_file).read_text().split()
        secs = [int(float(x)) for x in raw if x.strip()]
        if not (folder / "transcript.md").exists():
            do_transcript(url, vid, folder)
        do_frames(url, vid, folder, secs)
        return

    # Phase 1 (batch): transcripts for every url in the list.
    ok = 0
    for url in urls:
        try:
            vid = video_id(url)
            do_transcript(url, vid, LIB / vid)
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAILED {url}: {e}")
    print(f"\n{ok}/{len(urls)} transcripts saved under research/video_library/")
    print("Tell me the video IDs (or just say 'done') — I'll read the transcripts and write a "
          "frames_manifest.json; then run:  python scripts/video_ingest.py --frames-manifest "
          "research/video_library/frames_manifest.json")


if __name__ == "__main__":
    main()
