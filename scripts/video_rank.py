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
import argparse, json, math, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "research" / "video_library"
LIB = BASE / os.environ.get("VIDEO_STYLE", "day_intra")   # per-style lane (swing|day_intra|scalp)
CAND = LIB / "_candidates.md"
CACHE = LIB / "_rankcache"   # trimmed per-video metadata+comments, so gate tweaks never re-fetch

TITLE_KW = ["backtest", "tested", "rules", "results", "win rate", "win-rate",
            "entry", "exit", "system", "mechanical", "%", "profit factor"]
PRAISE_POS = ["works", "profitable", "made money", "thank you", "best", "clear",
              "helped", "legit", "accurate", "backtested", "finally", "gem", "underrated"]
PRAISE_NEG = ["scam", "doesn't work", "does not work", "lost money", "useless",
              "misleading", "garbage", "hype", "selling", "waste", "fake"]

# Stronger, efficacy-specific phrases: a comment matching one of these is treated
# as confluence that the strategy ACTUALLY WORKS (not just a generic "nice video").
WORKS_RE = re.compile(
    r"\b(it works|this works|really works|actually works|works (great|well|for me)|"
    r"profitable|made (me )?(money|profit|pips|\$|\d)|paid off|"
    r"back ?tested|win ?rate|winrate|consistent(ly)? profit|"
    r"changed my trading|best strateg|this is (the )?(gold|goat)|"
    r"passed (my|the) (funded|challenge)|took this trade.*(profit|win)|"
    r"been using this.*(work|profit|win))\b", re.I)
NEG_RE = re.compile(
    r"\b(scam|does ?n'?t work|doesn't work|lost money|blew my account|"
    r"repaint|misleading|waste of time|fake|selling a course)\b", re.I)


def works_mentions(comments: list[dict]) -> int:
    """Count comments that explicitly affirm the strategy works (net of clear negatives)."""
    if not comments:
        return 0
    pos = neg = 0
    for c in comments[:60]:
        txt = c.get("text") or ""
        if not txt:
            continue
        if WORKS_RE.search(txt):
            pos += 1
        if NEG_RE.search(txt):
            neg += 1
    return pos - neg

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


def _vid_of(url: str) -> str:
    m = re.search(r"v=([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else url


def _trim(d: dict) -> dict:
    """Keep only what the ranker + gates need, so the cache stays small."""
    return {
        "like_count": d.get("like_count") or 0,
        "comment_count": d.get("comment_count") or 0,
        "channel_follower_count": d.get("channel_follower_count") or 0,
        "upload_date": d.get("upload_date") or "",
        "comments": [{"text": c.get("text") or "", "like_count": c.get("like_count") or 0}
                     for c in (d.get("comments") or [])],
    }


def fetch(url: str) -> dict | None:
    """Fetch trimmed metadata+comments, cached per video so re-runs (e.g. after a
    gate change) never hit YouTube again."""
    vid = _vid_of(url)
    cf = CACHE / f"{vid}.json"
    if cf.exists():
        try:
            return json.loads(cf.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    try:
        _ck = ["--cookies", os.environ["VIDEO_COOKIES"]] if os.environ.get("VIDEO_COOKIES") else []
        out = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "-J", "--write-comments", "--no-warnings",
             "--remote-components", "ejs:github", *_ck,
             "--extractor-args", "youtube:max_comments=60,60,0,0", url],
            capture_output=True, text=True, timeout=150)
        d = json.loads(out.stdout) if out.stdout.strip() else None
    except Exception:  # noqa: BLE001
        d = None
    if d is None:
        return None
    trimmed = _trim(d)
    CACHE.mkdir(parents=True, exist_ok=True)
    try:
        cf.write_text(json.dumps(trimmed), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return trimmed


def _classify(text: str) -> int:
    """+1 positive, -1 negative, 0 neutral/off-topic for one comment."""
    t = (text or "").lower()
    if not t.strip():
        return 0
    if NEG_RE.search(t) or any(k in t for k in PRAISE_NEG):
        return -1
    score = 0.0
    if _VADER:
        score = _VADER.polarity_scores(t)["compound"]
    strong_pos = bool(WORKS_RE.search(t)) or any(k in t for k in PRAISE_POS)
    if strong_pos or score >= 0.35:
        return 1
    if score <= -0.35:
        return -1
    return 0


def comment_stats(comments: list[dict]) -> dict:
    """Positive/negative counts + positive ratio over OPINIONATED comments.
    ratio = pos / (pos+neg); 'overwhelmingly positive' means ratio >= ~0.8."""
    pos = neg = 0
    for c in comments[:60]:
        v = _classify(c.get("text") or "")
        if v > 0:
            pos += 1
        elif v < 0:
            neg += 1
    opinion = pos + neg
    ratio = (pos / opinion) if opinion else 0.0
    return {"pos": pos, "neg": neg, "opinion": opinion, "ratio": ratio}


def pct(vals):
    s = sorted(vals)
    n = len(s)
    return lambda x: (sum(1 for v in s if v <= x) / n) if n else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage2", type=int, default=30)
    ap.add_argument("--pick", type=int, default=8)
    ap.add_argument("--min-subs", type=int, default=10_000,
                    help="HARD gate: drop channels below this subscriber count (operator req: >10k)")
    ap.add_argument("--pos-ratio", type=float, default=0.8,
                    help="HARD gate: fraction of opinionated comments that must be positive (0.8 = 8 of 10)")
    ap.add_argument("--min-opinion", type=int, default=10,
                    help="HARD gate: minimum opinionated comments needed to judge the ratio")
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
        cmts = d.get("comments") or []
        r["praise"] = praise_score(cmts)
        r["works"] = works_mentions(cmts)
        st = comment_stats(cmts)
        r["pos"] = st["pos"]; r["neg"] = st["neg"]
        r["opinion"] = st["opinion"]; r["ratio"] = st["ratio"]

    pv, pl, ps, pc, pp = (pct([r[k] for r in s2]) for k in
                          ("views", "lv", "subs", "comments_n", "praise"))
    for r in s2:
        r["score"] = round(
            0.25 * pp(r["praise"]) + 0.20 * pl(r["lv"]) + 0.15 * pv(r["views"])
            + 0.10 * ps(r["subs"]) + 0.10 * pc(r["comments_n"])
            + 0.10 * length_fit(r["min"]) + 0.10 * title_quality(r["title"]), 3)
    s2.sort(key=lambda r: r["score"], reverse=True)

    # HARD gates (operator criteria): >=100k subs AND comments overwhelmingly
    # positive (>= pos-ratio of opinionated comments, with a minimum sample).
    def _passes(r: dict) -> bool:
        return (r.get("subs", 0) >= args.min_subs
                and r.get("opinion", 0) >= args.min_opinion
                and r.get("ratio", 0.0) >= args.pos_ratio)

    survivors = [r for r in s2 if _passes(r)]
    picks = survivors[:args.pick]
    pick_ids = {r["id"] for r in picks}

    lines = ["# Ranked candidates", "",
             f"Top {len(s2)} of {len(rows)} scored on praise / likes / views / subs / "
             "length / title quality.",
             f"HARD gates: subs >= {args.min_subs:,} AND >= {int(args.pos_ratio*100)}% of "
             f">= {args.min_opinion} opinionated comments positive. "
             f"{len(survivors)} passed; PICK = top {len(picks)} to ingest.",
             "Reminder: engagement is a weak proxy — the backtest is the real test.", "",
             "| # | pick | score | pos/neg | ratio | subs | views | praise | min | channel | title | url |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(s2, 1):
        gate = "PASS" if _passes(r) else "-"
        mark = ("PICK " if r["id"] in pick_ids else "") + gate
        lines.append(f"| {i} | {mark} | {r['score']} | {r.get('pos',0)}/{r.get('neg',0)} | "
                     f"{r.get('ratio',0.0):.0%} | {r['subs']:,} | {r['views']:,} | "
                     f"{r['praise']:+.2f} | {r['min']} | "
                     f"{r['channel'][:20]} | {r['title'][:60]} | {r['url']} |")
    out = LIB / "_candidates_ranked.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    pick_urls = " ".join(f'"{r["url"]}"' for r in picks)
    (LIB / "_picks.txt").write_text("\n".join(r["url"] for r in picks), encoding="utf-8")
    print(f"\nRanked -> {out.relative_to(ROOT)}")
    print(f"{len(survivors)} passed hard gates (subs>={args.min_subs:,}, "
          f">={int(args.pos_ratio*100)}% of >={args.min_opinion} comments positive); "
          f"picking {len(picks)}.")
    print(f"Ingest the picks:\n  python scripts/video_ingest.py --ingest {pick_urls}")


if __name__ == "__main__":
    main()
