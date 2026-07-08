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


# ---- VALIDATION classifier (operator req): a comment counts ONLY if it attests, with
# confidence, that the commenter TESTED the strategy and it ACTUALLY WORKS / made results.
# Generic positivity ("great video, thanks!", "love this", "so clear") does NOT count.
_EXPERIENCE_RE = re.compile(
    r"\b(back ?tested|backtest|i tested|tested (it|this)|tried (it|this)|used (it|this)|"
    r"been using|using this|i (trade|traded|use) this|paper ?trade[d]?|forward ?test|"
    r"on demo|took (this|the) trade|for (the )?(past )?(a )?(week|month|year|day)s?|"
    r"past (week|month|year)|every ?day|so far|last (week|month|year))\b", re.I)
_RESULT_RE = re.compile(
    r"\b(works|worked|working|profitable|profit|made (me )?(money|profit|pips|\$|\d)|"
    r"win ?rate|winrate|\d{1,3}\s?%|accura(te|cy)|consistent(ly)?|paid off|"
    r"hit (my |the )?target|green|up \d|passed (my|the) (funded|challenge|eval)|"
    r"changed my (trading|life)|best strateg)\b", re.I)
# Unambiguous standalone validation phrases (imply tested-and-works on their own).
_STRONG_VALID_RE = re.compile(
    r"\b(can confirm|actually works|really works|it works|this works|does work|"
    r"back ?tested.*(profit|win|work)|\d{1,3}\s?% win|been using this for|"
    r"tried this.*(work|profit|win)|tested this.*(work|profit|win)|100% works|"
    r"this is legit|it'?s legit)\b", re.I)


def is_validation(text: str) -> bool:
    """True only for a confident, evidence-based 'I tested it and it works' comment."""
    t = (text or "").lower()
    if not t.strip():
        return False
    if NEG_RE.search(t) or "doesn't work" in t or "does not work" in t or "not profitable" in t:
        return False
    if _STRONG_VALID_RE.search(t):
        return True
    return bool(_RESULT_RE.search(t) and _EXPERIENCE_RE.search(t))


def validation_stats(comments: list[dict], window_months: int = 12) -> dict:
    """Count validation comments (total + within window)."""
    import time as _t
    now = _t.time(); window = window_months * 2_629_800
    valid = recent = 0
    for c in comments[:80]:
        if is_validation(c.get("text") or ""):
            valid += 1
            ts = c.get("timestamp") or 0
            if ts and now - ts <= window:
                recent += 1
    return {"valid": valid, "valid_recent": recent}

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


def recency_score(comments: list[dict], upload_date: str, window_months: int = 12) -> float:
    """RANKING preference (not a gate): how fresh is the positive reception?
    = fraction of POSITIVE comments posted within `window_months`, blended with upload recency.
    Range [0,1]; comments with no timestamp are ignored in the numerator."""
    import time as _t
    now = _t.time()
    window = window_months * 2_629_800          # ~seconds/month
    pos_recent = pos_dated = 0
    for c in comments[:80]:
        if not is_validation(c.get("text") or ""):     # recency of VALIDATION, not generic praise
            continue
        ts = c.get("timestamp") or 0
        if ts <= 0:
            continue
        pos_dated += 1
        if now - ts <= window:
            pos_recent += 1
    comment_recency = (pos_recent / pos_dated) if pos_dated else 0.0
    # upload recency: 1.0 if uploaded within the window, decaying after
    up = 0.0
    if upload_date and len(upload_date) == 8:
        try:
            import datetime as _d
            dt = _d.datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=_d.timezone.utc)
            months = (now - dt.timestamp()) / 2_629_800
            up = 1.0 if months <= window_months else max(0.0, 1.0 - (months - window_months) / 36.0)
        except Exception:  # noqa: BLE001
            up = 0.0
    return round(0.7 * comment_recency + 0.3 * up, 3)


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
        "comments": [{"text": c.get("text") or "", "like_count": c.get("like_count") or 0,
                      "timestamp": c.get("timestamp") or 0}       # unix secs (yt-dlp), 0 if unknown
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
             "--extractor-args", "youtube:comment_sort=new;max_comments=80,80,0,0", url],
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
                    help="(soft) minimum opinionated comments to judge the sentiment ratio")
    ap.add_argument("--min-validation", type=int, default=3,
                    help="HARD gate: min # of VALIDATION comments (people who tested it and confirm it works)")
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
        vs = validation_stats(cmts)
        r["valid"] = vs["valid"]; r["valid_recent"] = vs["valid_recent"]   # tested-and-works comments
        r["recent"] = recency_score(cmts, r["upload"])   # 12-mo VALIDATION/upload recency (ranking pref)

    pv, pl, ps, pr, pvd = (pct([r[k] for r in s2]) for k in
                           ("views", "lv", "subs", "recent", "valid"))
    for r in s2:
        r["score"] = round(
            0.30 * pvd(r["valid"]) + 0.15 * pr(r["recent"]) + 0.15 * pl(r["lv"])
            + 0.12 * pv(r["views"]) + 0.10 * ps(r["subs"])
            + 0.08 * length_fit(r["min"]) + 0.10 * title_quality(r["title"]), 3)
    s2.sort(key=lambda r: r["score"], reverse=True)

    # HARD gates (operator criteria): >=100k subs AND comments overwhelmingly
    # positive (>= pos-ratio of opinionated comments, with a minimum sample).
    def _passes(r: dict) -> bool:
        # HARD gate (operator req): enough subscribers AND enough VALIDATION comments
        # (people who state, with confidence, that they tested it and it works).
        return (r.get("subs", 0) >= args.min_subs
                and r.get("valid", 0) >= args.min_validation)

    survivors = [r for r in s2 if _passes(r)]
    picks = survivors[:args.pick]
    pick_ids = {r["id"] for r in picks}

    lines = ["# Ranked candidates", "",
             f"Top {len(s2)} of {len(rows)} scored on praise / likes / views / subs / "
             "length / title quality.",
             f"HARD gates: subs >= {args.min_subs:,} AND >= {args.min_validation} VALIDATION comments "
             "(people stating with confidence they tested it and it works). "
             f"{len(survivors)} passed; PICK = top {len(picks)} to ingest.",
             "Reminder: engagement is a weak proxy — the backtest is the real test.", "",
             "| # | pick | score | valid | val_recent | recent12mo | pos/neg | subs | views | min | channel | title | url |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(s2, 1):
        gate = "PASS" if _passes(r) else "-"
        mark = ("PICK " if r["id"] in pick_ids else "") + gate
        lines.append(f"| {i} | {mark} | {r['score']} | {r.get('valid',0)} | {r.get('valid_recent',0)} | "
                     f"{r.get('recent',0.0):.2f} | {r.get('pos',0)}/{r.get('neg',0)} | {r['subs']:,} | {r['views']:,} | "
                     f"{r['min']} | {r['channel'][:20]} | {r['title'][:60]} | {r['url']} |")
    out = LIB / "_candidates_ranked.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    pick_urls = " ".join(f'"{r["url"]}"' for r in picks)
    (LIB / "_picks.txt").write_text("\n".join(r["url"] for r in picks), encoding="utf-8")
    print(f"\nRanked -> {out.relative_to(ROOT)}")
    print(f"{len(survivors)} passed hard gates (subs>={args.min_subs:,}, "
          f">={args.min_validation} validation comments = tested-and-confirmed-works); "
          f"picking {len(picks)}.")
    print(f"Ingest the picks:\n  python scripts/video_ingest.py --ingest {pick_urls}")


if __name__ == "__main__":
    main()
