# pLI-xOg-5bQ — "New Momentum Indicator: Klinger Volume Oscillator + RSI" (PineTrades)

Source: <https://www.youtube.com/watch?v=pLI-xOg-5bQ>

## Rules (as described)
- **Instrument/timeframe:** CAD/CHF (forex), 15-minute.
- **Trend:** RSI length 35 above 50 = bullish (below = bearish).
- **Trigger (Klinger Volume Oscillator):** confirm bullish volume + a pullback — the KVO histogram briefly flips green→red→green, the white signal line re-enters the histogram (a dark-green dot prints), and the signal line is above 0.
- **Stop:** recent swing low. **Target:** 1.5R. Mirror for shorts.
- Alt variant gates entries on a proprietary paid "PineTrades Market Beacon" indicator (affiliate link + forex-broker deposit-bonus promo).

## Verdict: REJECT — forex/intraday + fuzzy trigger + paid indicator; needs a custom detector.
Demoed on forex (CAD/CHF) 15-minute intraday, not daily US stocks. The core trigger — a brief KVO histogram color transition (green→red→green "for a few candles") plus signal-line re-entry — is fuzzy and would require a faithfully-implemented Klinger Volume Oscillator detector with its dot/color-state logic (not in the codebase; not built now). The Klinger oscillator is an obscure volume indicator with no established daily-stock edge, and the second variant depends on a paywalled proprietary indicator. Promising-to-nobody / needs custom detector — not worth building given the forex-intraday framing.
Status: rejected
