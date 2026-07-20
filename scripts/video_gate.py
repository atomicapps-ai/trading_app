"""video_gate.py — social-proof gate for candidate day-trade videos.

Titles are misleading, so before we spend assessment effort we gate candidates on
who's behind them and how recent viewers actually reacted:

  * channel must have >= --min-subs subscribers (default 100k),
  * the most-recent --max-comments comments must be positive on average (VADER),
  * and we surface **"this made me money"** testimonials — the gold signal — and
    rank by how many of those show up in the recent comments.

Needs YouTube access (yt-dlp), so RUN THIS ON THE OPERATOR MACHINE, not the
sandbox (cloud IPs are blocked). It enriches, gates, ranks, and writes a shortlist
to research/video_library/day_intra/_candidates_gated.md for assessment.

    python scripts/video_gate.py                       # gate the existing _candidates.md
    python scripts/video_gate.py --top 25 --min-subs 100000
    python scripts/video_gate.py --ids id1,id2,...     # gate a specific set
    python scripts/video_gate.py --cookies cookies.txt # if YouTube bot-checks
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "research" / "video_library"
LANE = BASE / "day_intra"
HIST = BASE / "_history.json"

# "This made me money" — the gold signal. Recent comments matching these are
# the strongest social proof that the strategy did something real for a viewer.
MONEY = re.compile(
    r"\$\s?\d|\d+\s?%|\bprofit|\bmade (me |money|bank)|making money|"
    r"paid (for|off|my)|\bbanked|withdrew|withdrawal|took \$?\d|turned \$?\d.*into|"
    r"funded (account|me)|passed (my|the|prop)|been profitable|consistent(ly)? profit|"
    r"changed my (life|trading)|this works|works (great|well|like)|"
    r"up \d|green (day|week|month)|first profitable", re.I)
# Obvious spam/scam comment noise to ignore when scoring (promo bots, tg handles).
SPAM = re.compile(r"t\.me/|telegram|whats ?app|dm me|contact (me|mr|mrs)|"
                  r"@\w+ on (ig|insta|telegram)|expert|account manager", re.I)


def _known() -> set[str]:
    try:
        return set(json.loads(HIST.read_text()).keys()) if HIST.exists() else set()
    except Exception:
        return set()


def _ids_from_candidates() -> list[tuple[str, str, str]]:
    """(id, title, url) rows from the existing _candidates.md."""
    f = LANE / "_candidates.md"
    if not f.exists():
        sys.exit(f"no {f} — run scripts/video_discover.py first, or pass --ids")
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        m = re.search(r"\|\s*(.+?)\s*\|\s*(https\S*watch\?v=([A-Za-z0-9_-]{11}))", line)
        if m:
            out.append((m.group(3), m.group(1), m.group(2)))
    return out


def _analyzer():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    return SentimentIntensityAnalyzer()


def fetch(vid: str, max_comments: int, cookies: str | None) -> dict | None:
    """yt-dlp metadata + recent comments for one video (no download)."""
    cmd = [sys.executable, "-m", "yt_dlp", "--skip-download", "--dump-single-json",
           "--write-comments", "--no-warnings",
           "--extractor-args", f"youtube:comment_sort=new;max_comments={max_comments},all,0,0",
           f"https://www.youtube.com/watch?v={vid}"]
    if cookies:
        cmd += ["--cookies", cookies]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return json.loads(out.stdout)
    except Exception as e:  # noqa: BLE001
        print(f"  (fetch failed) {vid}: {e}", file=sys.stderr)
        return None


def score(info: dict, sia) -> dict:
    subs = info.get("channel_follower_count") or 0
    comments = [c.get("text", "") for c in (info.get("comments") or [])
                if c.get("text") and not SPAM.search(c.get("text", ""))]
    comments = comments[:info.get("_max", 50)]
    comps = [sia.polarity_scores(t)["compound"] for t in comments]
    avg = round(statistics.mean(comps), 3) if comps else 0.0
    pos_frac = round(sum(c > 0.2 for c in comps) / len(comps), 2) if comps else 0.0
    money = [t for t in comments if MONEY.search(t)]
    return {
        "id": info.get("id"), "title": (info.get("title") or "")[:70],
        "channel": (info.get("channel") or info.get("uploader") or "")[:24],
        "subs": subs, "n_comments": len(comments),
        "avg_sentiment": avg, "pos_frac": pos_frac,
        "money_hits": len(money),
        "money_samples": [re.sub(r"\s+", " ", t)[:100] for t in money[:3]],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", default="")
    ap.add_argument("--ids", default="")
    ap.add_argument("--min-subs", type=int, default=100_000)
    ap.add_argument("--min-sentiment", type=float, default=0.15)
    ap.add_argument("--min-pos-frac", type=float, default=0.40)
    ap.add_argument("--max-comments", type=int, default=50)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--cookies", default="")
    args = ap.parse_args()

    if args.ids:
        rows = [(v.strip(), "", f"https://youtube.com/watch?v={v.strip()}")
                for v in args.ids.split(",") if v.strip()]
    else:
        rows = _ids_from_candidates()
    known = _known()
    rows = [r for r in rows if r[0] not in known]           # skip processed/tombstoned
    print(f"gating {len(rows)} candidates "
          f"(subs>={args.min_subs:,}, avg-sentiment>={args.min_sentiment}, "
          f"pos-frac>={args.min_pos_frac}) ...", file=sys.stderr)

    sia = _analyzer()
    scored = []
    for i, (vid, _t, _u) in enumerate(rows, 1):
        info = fetch(vid, args.max_comments, args.cookies or None)
        if not info:
            continue
        info["_max"] = args.max_comments
        s = score(info, sia)
        passed = (s["subs"] >= args.min_subs
                  and s["avg_sentiment"] >= args.min_sentiment
                  and s["pos_frac"] >= args.min_pos_frac
                  and s["n_comments"] >= 5)
        s["pass"] = passed
        scored.append(s)
        flag = "PASS" if passed else "skip"
        print(f"  [{i}/{len(rows)}] {flag} {vid} subs={s['subs']:>9,} "
              f"sent={s['avg_sentiment']:+.2f} money={s['money_hits']}", file=sys.stderr)

    winners = [s for s in scored if s["pass"]]
    # rank: money testimonials first (the gold signal), then sentiment, then subs
    winners.sort(key=lambda s: (s["money_hits"], s["avg_sentiment"], s["subs"]), reverse=True)
    winners = winners[:args.top]

    lines = ["# Gated day-trade candidates (subscriber + recent-comment gate)", "",
             f"{len(winners)} passed of {len(scored)} fetched — "
             f"subs>={args.min_subs:,}, avg VADER sentiment>={args.min_sentiment}, "
             f"pos-frac>={args.min_pos_frac}. Ranked by money-testimonials, then sentiment.", "",
             "| subs | sent | pos% | 💰money | channel | title | url |",
             "|---|---|---|---|---|---|---|"]
    for s in winners:
        lines.append(f"| {s['subs']:,} | {s['avg_sentiment']:+.2f} | {int(s['pos_frac']*100)}% | "
                     f"{s['money_hits']} | {s['channel']} | {s['title']} | "
                     f"https://youtube.com/watch?v={s['id']} |")
    lines += ["", "## Sample \"made me money\" comments (top winners)"]
    for s in winners[:12]:
        if s["money_samples"]:
            lines.append(f"- **{s['id']}** ({s['money_hits']}): " +
                         " · ".join(f'"{q}"' for q in s["money_samples"]))
    out = LANE / "_candidates_gated.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{len(winners)} winners -> {out.relative_to(ROOT)}", file=sys.stderr)
    print("Next: review it, then ingest the picks with scripts/video_ingest.py --ingest",
          file=sys.stderr)


if __name__ == "__main__":
    main()
