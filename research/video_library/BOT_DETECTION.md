# Bot / scam-comment detection — living playbook

**Purpose:** the social-proof gate (`scripts/video_gate.py`) ranks candidates by
"this made me money" testimonials in recent comments. That signal is only useful if
we strip the **bot/scam comment rings** that farm engagement on popular trading videos.
This doc catalogs the patterns we've seen so the gate keeps improving. When you spot a
new one, add it here AND to `video_gate.py`'s filters.

## Observed on the 2026-07 gate run (concrete)
- **Cross-video duplicate comments** — the *strongest* signal. Same text posted on
  multiple different videos = a bot, not a viewer:
  - *"I was recently laid off from my truck driver job with Pepsi…"* → on `TxFITsJBQbI` **and** `Z52d-_p5DXM`.
  - *"Am I the only one struggling 🤦 I've been losing so much lately…"* → on `l0UsErg8OLA` **and** `ZTMregh_428`.
- **Signal-seller / "copy professionals" promos** — *"surprised he skipped Anesaurus
  signals… where beginners copy professionals"* (Anesaurus is a known signals scam).
- **Crypto-pivot** — a stock/forex day-trade video whose comment pushes crypto or a
  "recovery expert": *"For the Newbie… in the crypto space… you need a sound mentor."*
- **Sob-story → mentor** testimonials — *"I owed the bank \$110,340… God is good"*,
  emoji-heavy, usually followed by a name-drop.

## Detection heuristics (what the gate implements)
| # | Heuristic | Rule |
|---|---|---|
| 1 | **Cross-video duplicate** | normalize text (lowercase, strip emoji/space); if it appears on ≥2 videos in the batch → bot, exclude everywhere |
| 2 | **Contact solicitation** | `t.me/`, telegram, whatsapp, "dm me", "@handle on IG", "reach out" |
| 3 | **Signal/mentor promo** | "signals", "copy professionals", "account manager", "expert", "mentor", "under the tutelage", named services |
| 4 | **Crypto-pivot / recovery** | crypto/bitcoin/forex-mentor/"recovery expert"/"recover funds" on a stock/day-trade video |
| 5 | **Sob-story bot** | "owed the bank", "laid off", "changed my life", "God is good" + money figure + emoji cluster |
| 6 | **Generic praise farm** | vague "this works, thank you" with zero strategy specifics — weak alone, discount not exclude |

## What a REAL testimonial looks like (KEEP — these are gold)
An authentic "made me money" comment references the video's **actual** strategy,
instrument, or rules, and a **concrete, checkable** result:
- *"I backtested the 5-minute FVG breakout for a month and got 75% win rate (n≈20)…"*
- *"I trade RTY 5-min with micros, this works — stick to the plan."*
- *"On the examples you hit the stop because the candle closed right at the level…"*

Rule of thumb: **specific + on-topic = real; generic + off-topic + repeated = bot.**
The gate's money-count now uses only comments that pass heuristics 1–5.

## Roadmap to improve
- Weight testimonials higher when they contain trading specifics (instrument, timeframe,
  win-rate, R-multiple) — a "specificity score".
- Flag channels whose comment section is >X% bot as low-trust regardless of subs.
- Track repeat-offender bot phrases across runs in this doc.
