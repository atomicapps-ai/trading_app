# Autonomous Video-Mining Co-Work Plan

Goal: run the existing video toolchain as a **hands-off loop** — ingest trading
videos, extract their strategies, validate by backtest, keep the good, discard
the rest — over ~100 videos without stopping. Resumable; never re-processes a
video (checkpointed in `_history.json`).

## Two lanes

**A. Acquisition (needs YouTube — runs where there's internet).**
Builds the raw material into `research/video_library/<id>/`.
```
python scripts/video_discover.py --per-query 30 --top 120      # candidates
python scripts/video_rank.py --stage2 60 --pick 100            # ranked shortlist
python scripts/video_ingest.py --ingest <urls...> --interval 90  # transcript + frames
```
Run this ahead of (or alongside) the loop to keep the queue full. The research
sandbox can't reach YouTube, so this lane runs on your machine (or a local
co-work session). Assessment does NOT need YouTube — it reads the saved files.

**B. Assessment (local files — the co-work loop).**
Per pending video: read transcript → view frames → extract a mechanical spec →
validate by backtest → pass/reject → retire → next.

## The loop (one video per iteration)

```
1. NEXT = `python scripts/video_queue.py --next`   (empty = done)
2. Read research/video_library/NEXT/transcript.md
3. View  research/video_library/NEXT/frames/*.jpg
4. Extract a MECHANICAL spec: instrument · timeframe · entry trigger ·
   regime/filters · stop · targets/exit. If it is NOT mechanical (motivational,
   vague, discretionary) or is out of scope (forex/crypto/options/ICT/scalping,
   non-daily-US-stock) → REJECT.
5. VALIDATE the mechanical ones:
     • Map to an existing detector, the parameterized meta-strategy, or write a
       minimal detector.
     • Backtest on the core universe (scripts.score_universe / backtest_runner).
     • PASS bar: OOS profit factor ≥ 1.2 AND avg-R > 0 AND ≥ ~100 trades across
       the universe AND it beats a naive control. Otherwise REJECT.
     • Promising but needs a custom detector we won't write now → REJECT with
       reason "promising — needs custom detector" so the idea is recorded.
6. Write research/video_library/NEXT/notes.md — the spec + the backtest verdict
   and numbers (or why it was rejected).
7. Retire:
     python scripts/video_retire.py NEXT --status passed
     python scripts/video_retire.py NEXT --status rejected --reason "<one line>"
8. Go to 1. Stop only when the queue is empty or the target count is reached.
```

## Guardrails / philosophy
- **Be strict.** Most videos are noise; the value is in rejecting fast and
  keeping only what survives a real backtest. A high reject rate is success.
- **No trade goes live from this loop.** It produces *validated candidates* +
  notes; adopting one into the live suite is a separate, deliberate step.
- **Checkpoint every video** via `video_retire` (writes `_history.json`), so the
  loop is fully resumable — if it stops, restart and it continues from the next
  pending id, never re-doing finished ones.
- **Progress:** `python scripts/video_queue.py --stats` → {passed, rejected,
  pending, no_material}. Target = 100 assessed.

## Status today
`python scripts/video_queue.py` — 48 ingested, 7 assessed, **40 pending**. The
loop can start on the 40 now; top up the queue toward 100 with lane A.
