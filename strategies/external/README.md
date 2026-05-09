# strategies/external/

Drop one folder per strategy here. Format:

```
external/
├── luxalgo_smc_breakout/
│   ├── source.pine          ← Pine Script copied from TradingView
│   ├── source_url.txt       ← TradingView URL the script was copied from
│   └── notes.md             ← (optional) anything you want to remember
├── chrismood_squeeze_pro/
│   └── source.pine
└── ...
```

When you're ready, ask Claude:
> analyze all strategies in strategies/external/

Claude will:
1. Read each `source.pine` / `notes.md`
2. Append a section to `strategies/STRATEGY_KNOWLEDGE.md` with what it does + critique
3. Flag duplicates (same primitive being reused under different names)
4. Identify any primitive worth extracting / reusing
5. Propose new combinations in `strategies/proposed/`
