# Video Library — trading-strategy idea mining

Each top video gets a folder `<video_id>/` containing:

```
<video_id>/
  meta.json        url, id, fetched-at, duration
  transcript.md    timestamped transcript (human + analysis readable)
  transcript.json  raw transcript data
  frames/          frame_00120s.jpg ... snapshots at specific timestamps
  notes.md         ← the payoff: source, summary, and TESTABLE HYPOTHESES
```

## Pipeline (per video)
1. **You:** `python scripts/video_ingest.py "<url>"` → transcript saved.
2. **Me:** read the transcript, reply with the frame timestamps worth capturing.
3. **You:** `python scripts/video_ingest.py "<url>" --frames 120,355,610` → frames saved.
4. **Me:** view frames + transcript, write `notes.md`:
   - source (channel, link, date), 1-paragraph summary,
   - the explicit **rules** the video proposes (entry / filter / stop / target),
   - each rule converted into a **testable hypothesis** with an ID, cross-linked into
     `strategies/THEORY_MATRIX.md`.
5. **Both:** the hypotheses get **backtested for validity** through `scripts/strategy_lab.py`
   on local data — adopted only if they beat the controls out-of-sample.

## Principle
A video is a *source of hypotheses, not facts*. Confident YouTube "strategies" are
usually untested or survivorship-biased. Mining them is valuable; believing them is not.
Everything here earns its place by surviving the backtest, same as the pivot work.
