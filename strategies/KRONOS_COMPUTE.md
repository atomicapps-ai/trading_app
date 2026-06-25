# Kronos Compute — local vs cloud, and what it costs

You can run Kronos forecasts **local (CPU, free, slow)** or **cloud (GPU, paid, fast)**, and
switch per run depending on how much you need your CPU / how much you want to spend. Prices
below are current as of 2026-06 (sources at the bottom) — they drift, so treat as ballpark.

## The switch

Every Kronos script takes `--device`:

```
python scripts\kronos_scan.py --device cpu              # local, free, slow
python scripts\kronos_scan.py --device cuda --gpu-rate 0.34   # on a GPU box, prints $ cost
python scripts\kronos_scan.py --device auto             # cuda if present, else cpu
```

`--gpu-rate <$/hr>` makes the run print its own estimated cost at the end, e.g.
`Est. cloud cost this run @ $0.34/hr: $0.02`. Local CPU always costs $0.

## What it costs (Kronos-small, ~30 paths, 10-day horizon)

The model is small, so even a budget GPU is ~20-40× faster than your CPU, and the bill is
tiny because the job finishes fast.

| Task | Local CPU (your machine) | Budget cloud GPU (e.g. RTX 4090 @ $0.34/hr) |
|---|---|---|
| Per symbol | ~130 s | ~3-5 s |
| Full `core_universe_100` scan (44 names) | ~94 min · $0 | ~3 min · **~$0.02** |
| Daily scans for a month (~22 days) | ~34 hrs of CPU · $0 | ~$0.50 |
| Stage-0 backtest (~5,000 forecasts) | days · $0 | ~5 hrs · **~$2** |

The dominant cloud cost risk is **leaving a box running idle** — you pay for every hour it's
on, not just compute. Spin up → run → spin down. For a tiny model like this, don't rent
anything bigger than a 3090/4090/T4; an A100/H100 is wasted money here.

## Cloud options, cheapest first

| Provider | GPU | ~$/hr | Notes |
|---|---|---|---|
| **Kaggle** | T4 ×2 | **free** | 30 GPU-hrs/week. Best for iteration; notebook only. |
| **Google Colab** | T4 | free / ~$10/mo Pro | Easiest browser GPU; free tier has session limits. |
| **Vast.ai** | RTX 3090 | ~$0.13-0.19 | Cheapest paid; marketplace, variable availability. |
| **Vast.ai** | RTX 4090 | ~$0.31 | Fast, cheap, still marketplace-variable. |
| **RunPod** | RTX 4090 | ~$0.34 (community) / $0.69 (secure) | Easy UX, reliable; from ~$0.24/hr entry. |
| **Lambda** | A100 40GB | ~$1.99 | Fixed pricing, predictable — but overkill for 24.7M params. |

## Recommended setup for the way you want to work

- **Iterating / tuning (free):** the `notebooks/kronos_cloud.ipynb` notebook on **Kaggle or
  Colab** — free GPU, runs the scan in minutes, paste results back here. No card, no idle risk.
- **Unattended backtests or daily pre-market scans (cheap):** rent a **Vast.ai RTX 3090/4090
  (~$0.13-0.34/hr)** or **RunPod 4090 ($0.34/hr)**, `git clone` this repo on the box, then
  `python scripts/kronos_scan.py --device cuda --gpu-rate 0.34`. A daily scan is ~$0.02; a
  month is well under a dollar. Shut the box down when done.
- **When you'd rather not spend and don't need the CPU:** run local with `--device cpu`
  overnight. Free, just slow.

Rule of thumb: this model is cheap to run on GPU — the decision is really "do I want my CPU
free and the answer in minutes (spend pennies)" vs "don't care, run it local overnight (free)."

## Sources (prices, 2026-06)
- Vast.ai pricing — https://vast.ai/pricing (RTX 3090 ~$0.13-0.19/hr, RTX 4090 ~$0.31/hr)
- RunPod pricing — https://www.runpod.io/pricing (RTX 4090 from $0.34/hr community)
- Lambda pricing — https://altstreet.investments/tools/gpu/gpu-price-comparison (A100 $1.99/hr)
- Kaggle/Colab free GPU tiers — provider docs
