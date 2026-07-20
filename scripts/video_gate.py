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
# Bot/scam comment noise to exclude when scoring — see BOT_DETECTION.md.
# Contact-solicitation, signal-seller/mentor promos, crypto-pivot, recovery scams,
# and sob-story-bot markers. Add new patterns here + to BOT_DETECTION.md.
SPAM = re.compile(
    r"t\.me/|telegram|whats ?app|dm me|contact (me|mr|mrs|him|her)|reach out|"
    r"@\w+ on (ig|insta|telegram|x)|account manager|"
    r"signals?\b|copy (the )?pro|copy professionals|mentor|coach|tutelage|"
    r"expert trader|recover(y| funds| my)|owed the bank|laid off|god is good|"
    r"anesaurus|under the guidance|guru|his strategy changed my life|"
    r"bitcoin|crypto|forex expert|financial (advisor|freedom coach)", re.I)


def _norm(t: str) -> str:
    """Normalize a comment for cross-video duplicate detection."""
    return re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()[:120]


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


class _LiteAnalyzer:
    """Fallback if vaderSentiment isn't installed — a tiny lexicon good enough
    to gate comment praise. Same interface as VADER (polarity_scores→compound)."""
    POS = {"great", "amazing", "love", "best", "profit", "profitable", "works",
           "worked", "clear", "helpful", "thank", "thanks", "gold", "excellent",
           "awesome", "perfect", "easy", "consistent", "winning", "won", "green",
           "made", "gain", "gains", "up", "passed", "banked", "goat", "legend"}
    NEG = {"scam", "bad", "worst", "lost", "loss", "losing", "waste", "trash",
           "useless", "fake", "doesnt", "didnt", "hate", "confusing", "wrong",
           "blew", "red", "down", "terrible", "garbage", "misleading"}

    def polarity_scores(self, text: str) -> dict:
        words = re.findall(r"[a-z']+", text.lower())
        if not words:
            return {"compound": 0.0}
        p = sum(w in self.POS for w in words)
        n = sum(w in self.NEG for w in words)
        return {"compound": max(-1.0, min(1.0, (p - n) / max(3, len(words) ** 0.5)))}


def _analyzer():
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        return SentimentIntensityAnalyzer()
    except ModuleNotFoundError:
        print("  (vaderSentiment not installed — using lite lexicon fallback; "
              "`pip install vaderSentiment` for better scoring)", file=sys.stderr)
        return _LiteAnalyzer()


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


def score(info: dict, sia, dupes: set[str]) -> dict:
    """dupes = normalized comment texts seen on >=2 videos (cross-video bots)."""
    raw = [c.get("text", "") for c in (info.get("comments") or []) if c.get("text")]
    raw = raw[:info.get("_max", 50)]
    n_raw = len(raw)
    # authentic = not spam AND not a cross-video duplicate bot
    clean = [t for t in raw if not SPAM.search(t) and _norm(t) not in dupes]
    comps = [sia.polarity_scores(t)["compound"] for t in clean]
    avg = round(statistics.mean(comps), 3) if comps else 0.0
    pos_frac = round(sum(c > 0.2 for c in comps) / len(comps), 2) if comps else 0.0
    money = [t for t in clean if MONEY.search(t)]
    return {
        "id": info.get("id"), "title": (info.get("title") or "")[:70],
        "channel": (info.get("channel") or info.get("uploader") or "")[:24],
        "subs": info.get("channel_follower_count") or 0,
        "n_comments": len(clean), "n_raw": n_raw,
        "bot_frac": round((n_raw - len(clean)) / n_raw, 2) if n_raw else 0.0,
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
    ap.add_argument("--min-money", type=int, default=0,
                    help="min CLEAN money-testimonials to pass (0 = no floor)")
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
    # ---- pass 1: fetch all, so we can detect cross-video duplicate bots ----
    infos = []
    from collections import Counter
    norm_counts: Counter = Counter()
    for i, (vid, _t, _u) in enumerate(rows, 1):
        info = fetch(vid, args.max_comments, args.cookies or None)
        if not info:
            print(f"  [{i}/{len(rows)}] (no data) {vid}", file=sys.stderr)
            continue
        info["_max"] = args.max_comments
        infos.append(info)
        for c in (info.get("comments") or [])[:args.max_comments]:
            t = c.get("text", "")
            if t:
                norm_counts[_norm(t)] += 1
    # a normalized comment seen on/across >=2 places is a bot ring
    dupes = {k for k, n in norm_counts.items() if n >= 2 and len(k) >= 15}
    print(f"cross-video duplicate bot phrases: {len(dupes)}", file=sys.stderr)

    # ---- pass 2: score with bots removed ----
    scored = []
    for info in infos:
        s = score(info, sia, dupes)
        passed = (s["subs"] >= args.min_subs
                  and s["avg_sentiment"] >= args.min_sentiment
                  and s["pos_frac"] >= args.min_pos_frac
                  and s["money_hits"] >= args.min_money
                  and s["n_comments"] >= 5)
        s["pass"] = passed
        scored.append(s)
        flag = "PASS" if passed else "skip"
        print(f"  {flag} {s['id']} subs={s['subs']:>9,} sent={s['avg_sentiment']:+.2f} "
              f"bot={int(s['bot_frac']*100)}% money={s['money_hits']}", file=sys.stderr)

    winners = [s for s in scored if s["pass"]]
    # rank: money testimonials first (the gold signal), then sentiment, then subs
    winners.sort(key=lambda s: (s["money_hits"], s["avg_sentiment"], s["subs"]), reverse=True)
    winners = winners[:args.top]

    lines = ["# Gated day-trade candidates (subscriber + recent-comment gate)", "",
             f"{len(winners)} passed of {len(scored)} fetched — "
             f"subs>={args.min_subs:,}, avg VADER sentiment>={args.min_sentiment}, "
             f"pos-frac>={args.min_pos_frac}. Ranked by money-testimonials, then sentiment.", "",
             "| subs | sent | pos% | bot% | 💰money | channel | title | url |",
             "|---|---|---|---|---|---|---|---|"]
    for s in winners:
        lines.append(f"| {s['subs']:,} | {s['avg_sentiment']:+.2f} | {int(s['pos_frac']*100)}% | "
                     f"{int(s['bot_frac']*100)}% | {s['money_hits']} | {s['channel']} | {s['title']} | "
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
