# sZFdrxdVTMk — 15m FVG + liquidity inflection → 1m CHoCH (NY open)

Source: <https://www.youtube.com/watch?v=sZFdrxdVTMk> · day trading (forex/futures, 1-min @ NY open), ~25 min.
Same engine as `-4IPHZwse0M` (see that note for the shared backtest) — this one adds a **fib + FVG
confluence stack** on the entry.

## The strategy (as stated)
1. **15m**: mark still-valid FVGs (draw-to targets/confirmations) + liquidity-inflection levels
   (trend-line breaks where price struggled then broke).
2. **1m at NY open**: wait for **CHoCH** (close beyond pivot). Draw a **Fib** from the move's start
   to its low; require the entry zone to sit in the **0.5–0.786 band, ideally 0.618 (golden ratio)**.
3. Require a **1m FVG** inside that 0.5–0.786 band + a 1m liquidity-inflection break = confluence.
4. Enter at FVG midpoint; stop outside the FVG-producing candle; **1:4** to start; move to
   break-even on the next BOS; trail to next 15m FVG midpoint. Explicitly: low win rate, winners run.

## Testable hypotheses
- **H-ICT5** Confluence stack (CHoCH + 0.618 fib + FVG + inflection) beats CHoCH alone. ⏳ untested
- **H-ICT6** Targeting 15m FVG midpoints captures the bulk of the move. ⏳ untested
- (Base CHoCH/FVG direction + payoff → see H-ICT1/H-ICT2 in `-4IPHZwse0M/notes.md`.)

## Backtest
The base layer (CHoCH direction = coin-flip; CHoCH + structural stop + 1:4 = +0.066R OOS) is in
`-4IPHZwse0M/notes.md`. **The fib-0.618 + multi-FVG confluence is the distinguishing claim and is
NOT yet tested** — it needs a 1-minute entry engine we don't have data for (our cache is 15m stocks;
this is 1m forex/futures). On 15m we can only approximate.

The honest read: the presenter's own framing is anti-edge-claim ("the market moves randomly... we're
just playing probabilistic outcomes... slight edge over time"), and shows $15K screenshots that are
survivorship-flavored. The confluence stack is *plausible as a filter that trades fewer, better setups*
but is unproven; the only validated part so far is the asymmetric payoff, which is generic.

## Verdict
Queued, not adopted. The new, worth-testing idea is **H-ICT5 (does confluence filtering lift the
+0.066R base?)** — that's the question that would justify the extra machinery. Until tested on
appropriate (1m) data, treat the screenshots as motivation, not evidence.
