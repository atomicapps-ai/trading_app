"""video_rank — rank discovered candidates to pick the best prospects to ingest.

Two-stage (so we don't hit YouTube 163 times):
  Stage 1 (free, from _candidates.md): pre-rank by views, length-fitness, and
          title quality (mentions of backtest/rules/results/win-rate).
  Stage 2 (yt-dlp, top N only): pull likes, comment_count, channel subscribers,
          upload date, AND top comments -> a "praise" score (does the audience say
          it actually works, vs. scam/hype). Composite -> ranked shortlist.

You run this (needs YouTube). Output: research/video_library/_candidates_ranked.md
with the top picks flagged. Then ingest the picks with video_ingest.py --ingest.

    python scripts/video_rank.py                 # stage-2 on top 30, pick 8
    python scripts/video_rank.py --stage2 40 --pick 10
"""
from __future__ import annotations
import argparse, json, math, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "research" / "video_library"
CAND = LIB / "_candidates.md"

TITLE_KW = ["backtest", "tested", "rules", "results", "win rate", "win-rate",
            "entry", "exit", "system", "mechanical", "%", "profit factor"]
PRAISE_POS = ["works", "profitable", "made money", "thank you", "best", "clear",
              "helped", "legit", "accurate", "backtested", "finally", "gem", "underrated"]
PRAISE_NEG = ["scam", "doesn't work", "does not work", "lost money", "useless",
              "misleading", "garbage", "hype", "selling", "waste", "fake"]

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _VADER = SentimentIntensityAnalyzer()
except Exception:  # noqa: BLE001
    _VADER = None


def parse_candidates() -> list[dict]:
    rows = []
    if not CAND.exists():
        sys.exit(f"no {CAND} — run scripts/video_discover.py first")
    for line in CAND.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[0] in ("views", "---"):
            continue
        m = re.search(r"v=([A-Za-z0-9_-]{11})", cells[4])
        if not m:
            continue
        try: views = int(cells[0].replace(",", ""))
        except ValueError: views = 0
        try: mins = int(cells[1])
        except ValueError: mins = 0
        rows.append({"id": m.group(1), "views": views, "min": mins,
                     "channel": cells[2], "title": cells[3], "url": cells[4]})
    return rows


def title_quality(t: str) -> float:
    t = t.lower()
    return min(sum(1 for k in TITLE_KW if k in t) / 4.0, 1.0)


def length_fit(m: int) -> float:
    if 6 <= m <= 25: return 1.0          # long enough for rules, not a Short/ramble
    if 3 <= m < 6 or 25 < m <= 40: return 0.5
    return 0.1


def praise_score(comments: list[dict]) -> float:
    if not comments:
        return 0.0
    tot = wsum = 0.0
    for c in comments[:40]:
        txt = (c.get("text") or "").lower()
        if not txt:
            continue
        s = 0.0
        if _VADER:
            s += _VADER.polarity_scores(txt)["compound"]
        s += 0.3 * (sum(k in txt for k in PRAISE_POS) - sum(k in txt for k in PRAISE_NEG))
        w = 1.0 + math.log1p(c.get("like_count") or 0)
        wsum += s * w; tot += w
    return wsum / tot if tot else 0.0


def fetch(url: str) -> dict | None:
    try:
        out = subprocess.run(
            ["yt-dlp", "-J", "--write-comments", "--no-warnings",
             "--remote-components", "ejs:github",
             "--extractor-args", "youtube:max_comments=40,40,0,0", url],
            capture_output=True, text=True, timeout=150)
        return json.loads(out.stdout) if out.stdout.strip() else None
    except Exception:  # noqa: BLE001
        return None


def pct(vals):
    s = sorted(vals)
    n = len(s)
    return lambda x: (sum(1 for v in s if v <= x) / n) if n else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage2", type=int, default=30)
    ap.add_argument("--pick", type=int, default=8)
    args = ap.parse_args()

    rows = parse_candidates()
    maxv = max((r["views"] for r in rows), default=1) or 1
    for r in rows:
        r["pre"] = (0.5 * math.log1p(r["views"]) / math.log1p(maxv)
                    + 0.3 * length_fit(r["min"]) + 0.2 * title_quality(r["title"]))
    rows.sort(key=lambda r: r["pre"], reverse=True)
    s2 = rows[:args.stage2]
    print(f"Stage 2: fetching metadata + comments for top {len(s2)} of {len(rows)} ...",
          file=sys.stderr)
    for i, r in enumerate(s2, 1):
        print(f"  [{i}/{len(s2)}] {r['title'][:50]}", file=sys.stderr)
        d = fetch(r["url"]) or {}
        r["likes"] = d.get("like_count") or 0
        r["comments_n"] = d.get("comment_count") or 0
        r["subs"] = d.get("channel_follower_count") or 0
        r["upload"] = d.get("upload_date") or ""
        r["lv"] = (r["likes"] / r["views"]) if r["views"] else 0.0
        r["praise"] = praise_score(d.get("comments") or [])

    pv, pl, ps, pc, pp = (pct([r[k] for r in s2]) for k in
                          ("views", "lv", "subs", "comments_n", "praise"))
    for r in s2:
        r["score"] = round(
            0.25 * pp(r["praise"]) + 0.20 * pl(r["lv"]) + 0.15 * pv(r["views"])
            + 0.10 * ps(r["subs"]) + 0.10 * pc(r["comments_n"])
            + 0.10 * length_fit(r["min"]) + 0.10 * title_quality(r["title"]), 3)
    s2.sort(key=lambda r: r["score"], reverse=True)

    lines = ["# Ranked candidates", "",
             f"Top {len(s2)} of {len(rows)} scored on praise / likes / views / subs / "
             "length / title quality. **PICK** = top " + str(args.pick) + " to ingest.",
             "Reminder: engagement is a weak proxy — the backtest is the real test.", "",
             "| # | score | views | likes | praise | subs | min | channel | title | url |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(s2, 1):
        pick = " ✅PICK" if i <= args.pick else ""
        lines.append(f"| {i}{pick} | {r['score']} | {r['views']:,} | {r['likes']:,} | "
                     f"{r['praise']:+.2f} | {r['subs']:,} | {r['min']} | "
                     f"{r['channel'][:20]} | {r['title'][:60]} | {r['url']} |")
    out = LIB / "_candidates_ranked.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    picks = " ".join(f'"{r["url"]}"' for r in s2[:args.pick])
    print(f"\nRanked -> {out.relative_to(ROOT)}")
    print(f"Ingest the picks:\n  python scripts/video_ingest.py --ingest {picks}")


if __name__ == "__main__":
    main()
