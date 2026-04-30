"""job_log_buffer.py — in-memory ring buffer of log lines per scheduled job.

The /jobs detail page needs a "Logs" tab. We don't ship a full logging
infrastructure for v1 — instead a tiny per-process buffer captures the
log lines emitted *during* each scheduled job run.

Wiring
------
``services.scheduler`` calls ``capture(job_id)`` as a context manager
around every job invocation. Inside the context, a logging handler
appends formatted records to ``_buffers[job_id]``. The buffer is a
``deque`` capped at ``MAX_LINES`` per job, so memory is bounded.

Limitations (acceptable for v1):
  * Lost on process restart.
  * Captures only the root logger by default — child loggers must
    propagate (they do by default).
  * Per-job, not per-run — two runs of the same job interleave.

Replace with a structured run ledger + on-disk log files when
``/jobs`` graduates from v1.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from contextlib import contextmanager
from typing import Iterator

MAX_LINES = 500


_buffers: dict[str, deque[str]] = {}
_lock = threading.Lock()


class _BufferHandler(logging.Handler):
    """Routes every record to the buffer of the currently-running job_id."""

    def __init__(self, job_id: str):
        super().__init__()
        self.job_id = job_id
        self.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:                                      # noqa: BLE001
            return
        with _lock:
            buf = _buffers.setdefault(self.job_id, deque(maxlen=MAX_LINES))
            buf.append(line)


@contextmanager
def capture(job_id: str) -> Iterator[None]:
    """Context manager: route logs emitted inside the block to ``job_id``."""
    handler = _BufferHandler(job_id)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield
    finally:
        root.removeHandler(handler)


def get_log_lines(job_id: str, limit: int = 200) -> list[str]:
    """Return the most recent ``limit`` lines captured for ``job_id``."""
    with _lock:
        buf = _buffers.get(job_id)
        if not buf:
            return []
        return list(buf)[-limit:]


def clear(job_id: str) -> None:
    """Drop all captured lines for ``job_id``. Used by the UI's "Clear" button."""
    with _lock:
        _buffers.pop(job_id, None)
