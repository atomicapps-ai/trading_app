"""kronos_service — wraps the Kronos foundation model into a ForecastDistribution.

POC stage (see strategies/KRONOS_UPGRADE_PROPOSAL.md, build order step 1). This is
deliberately decoupled from data_service: pass in a bars DataFrame and get back a
ForecastDistribution. Wiring to data_service / the detector contract comes later.

SETUP (one time):
    1. Vendor the MIT-licensed model code:
         git clone https://github.com/shiyu-coder/Kronos vendor/kronos
       (only the `model/` package and its deps are needed; weights pull from HF.)
    2. Install inference deps into your env:
         pip install torch safetensors huggingface_hub einops
    3. Run the POC:
         python -m scripts.kronos_poc

Weights download automatically from Hugging Face on first use:
    tokenizer  NeoQuasar/Kronos-Tokenizer-base
    model      NeoQuasar/Kronos-small   (24.7M params, max context 512)

Probability note: Kronos.predict() with sample_count>1 *averages* paths internally
and returns a single trajectory. To get a genuine distribution (for p_up, the cone,
and hit probabilities) we call predict() n_paths times with sample_count=1 and a
sampling temperature T>0, collecting one stochastic path per call. Correct but not
fast; batching is a later optimization.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

from models.forecast import ForecastDistribution, ForecastPath
from services.settings_service import PROJECT_ROOT

logger = logging.getLogger(__name__)

DEFAULT_TOKENIZER = "NeoQuasar/Kronos-Tokenizer-base"
DEFAULT_MODEL = "NeoQuasar/Kronos-small"
MAX_CONTEXT = 512

_PREDICTOR = None  # module singleton (model load is expensive)


def _vendor_on_path() -> None:
    vendor = PROJECT_ROOT / "vendor" / "kronos"
    if vendor.exists() and str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))


def _pick_device() -> str:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "torch is required for Kronos inference. "
            "Install with: pip install torch safetensors huggingface_hub einops"
        ) from exc
    if torch.cuda.is_available():
        return "cuda:0"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def get_predictor(
    model_name: str = DEFAULT_MODEL,
    tokenizer_name: str = DEFAULT_TOKENIZER,
    device: str | None = None,
):
    """Load (once) and return a KronosPredictor. Raises a clear error if unset up."""
    global _PREDICTOR
    if _PREDICTOR is not None:
        return _PREDICTOR

    _vendor_on_path()
    vendor_model = PROJECT_ROOT / "vendor" / "kronos" / "model"
    try:
        from model import Kronos, KronosPredictor, KronosTokenizer
    except ImportError as exc:
        if not vendor_model.exists():
            raise ImportError(
                f"Kronos model code not found at {vendor_model}. Vendor it first:\n"
                "    git clone https://github.com/shiyu-coder/Kronos vendor/kronos"
            ) from exc
        raise ImportError(
            f"Found Kronos code at {vendor_model}, but importing it failed: {exc}\n"
            "This almost always means a missing dependency (commonly torch). "
            "Install into THIS venv with:\n"
            "    python -m pip install torch safetensors huggingface_hub einops"
        ) from exc

    dev = device or _pick_device()
    logger.info("Loading Kronos %s (tokenizer %s) on %s", model_name, tokenizer_name, dev)
    tokenizer = KronosTokenizer.from_pretrained(tokenizer_name)
    model = Kronos.from_pretrained(model_name)
    # Be tolerant of KronosPredictor signature differences across repo versions.
    try:
        _PREDICTOR = KronosPredictor(model, tokenizer, max_context=MAX_CONTEXT, device=dev)
    except TypeError:
        _PREDICTOR = KronosPredictor(model, tokenizer, max_context=MAX_CONTEXT)
    return _PREDICTOR


def _future_timestamps(last_ts: pd.Timestamp, interval: str, pred_len: int) -> pd.Series:
    """Generate plausible future timestamps for the forecast horizon."""
    if interval in ("1d", "1day", "day"):
        idx = pd.bdate_range(start=last_ts + pd.Timedelta(days=1), periods=pred_len)
    else:
        # crude intraday spacing; refine when we move past daily
        freq = {"1h": "1h", "30m": "30min", "15m": "15min", "5m": "5min"}.get(interval, "1h")
        idx = pd.date_range(start=last_ts, periods=pred_len + 1, freq=freq)[1:]
    return pd.Series(idx)


def forecast(
    *,
    symbol: str,
    interval: str,
    bars: pd.DataFrame,
    pred_len: int = 10,
    n_paths: int = 30,
    lookback: int = 400,
    temperature: float = 1.0,
    top_p: float = 0.9,
    batch_size: int = 16,
    model_name: str = DEFAULT_MODEL,
    device: str | None = None,
) -> ForecastDistribution:
    """Forecast `pred_len` bars ahead, returning a ForecastDistribution of `n_paths`.

    `bars` must have columns ['open','high','low','close'] (volume optional) and a
    DatetimeIndex or a 'timestamps' column, oldest-first.

    Paths are produced by replicating the context `n_paths` times and running them
    through predict_batch in one (chunked) batched pass — far faster than calling
    predict() per path. Each replicated series differs only by stochastic sampling
    (T>0, top_p), which is exactly the Monte-Carlo distribution we want.
    """
    df = bars.copy()
    if "timestamps" in df.columns:
        df["timestamps"] = pd.to_datetime(df["timestamps"])
        ts = df["timestamps"]
    else:
        ts = pd.Series(pd.to_datetime(df.index))
        df = df.reset_index(drop=True)

    required = ["open", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"bars missing required columns: {missing}")

    lookback = min(lookback, MAX_CONTEXT, len(df))
    x_df = df.iloc[-lookback:][[c for c in ["open", "high", "low", "close", "volume", "amount"] if c in df.columns]].reset_index(drop=True)
    x_ts = ts.iloc[-lookback:].reset_index(drop=True)
    last_ts = pd.Timestamp(x_ts.iloc[-1])
    y_ts = _future_timestamps(last_ts, interval, pred_len)
    last_close = float(x_df["close"].iloc[-1])

    predictor = get_predictor(model_name=model_name, device=device)

    def _to_path(pred) -> ForecastPath:
        return ForecastPath(
            close=[float(v) for v in pred["close"].tolist()],
            high=[float(v) for v in pred["high"].tolist()],
            low=[float(v) for v in pred["low"].tolist()],
        )

    paths: list[ForecastPath] = []
    remaining = n_paths
    use_batch = hasattr(predictor, "predict_batch")
    while remaining > 0:
        chunk = min(batch_size, remaining)
        if use_batch:
            try:
                preds = predictor.predict_batch(
                    df_list=[x_df] * chunk,
                    x_timestamp_list=[x_ts] * chunk,
                    y_timestamp_list=[y_ts] * chunk,
                    pred_len=pred_len,
                    T=temperature,
                    top_p=top_p,
                    sample_count=1,
                    verbose=False,
                )
                paths.extend(_to_path(p) for p in preds)
            except Exception as exc:  # noqa: BLE001 — fall back to per-path predict
                logger.warning("predict_batch failed (%s); falling back to per-path predict", exc)
                use_batch = False
                continue
        else:
            for _ in range(chunk):
                pred = predictor.predict(
                    df=x_df, x_timestamp=x_ts, y_timestamp=y_ts,
                    pred_len=pred_len, T=temperature, top_p=top_p,
                    sample_count=1, verbose=False,
                )
                paths.append(_to_path(pred))
        remaining -= chunk
        logger.debug("%s: %d/%d paths", symbol, len(paths), n_paths)

    return ForecastDistribution.build(
        source=model_name.split("/")[-1].lower(),
        symbol=symbol,
        interval=interval,
        as_of=last_ts.isoformat(),
        last_close=last_close,
        paths=paths,
    )
