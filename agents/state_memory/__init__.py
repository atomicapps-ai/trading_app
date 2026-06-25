"""state_memory — vector-similarity matrix over historical bar states.

Answers: "find me past times the market state on a given symbol/timeframe
looked like *this* and tell me what happened next."

Pure-function design: encoder + labeler are deterministic functions of
(bars, as_of_idx). The FAISS index is built offline from cached OHLCV
CSVs in data/historical/, persisted under data/state_memory/.

Public surface:
- encoder.encode_bars(df) -> (features: np.ndarray[N, 8], valid_mask: np.ndarray[N])
- encoder.FEATURE_NAMES: ordered list of feature names
- labeler.label_bars(df, interval) -> dict[horizon -> np.ndarray[N]]
- labeler.HORIZONS: ordered list of horizon names
"""

from agents.state_memory import encoder, labeler

__all__ = ["encoder", "labeler"]
