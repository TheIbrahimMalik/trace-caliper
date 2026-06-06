"""TraceCaliper: trace-first release gate for coding-agent skills."""

from __future__ import annotations

from tracecaliper.scoring import (
    DEFAULT_WEIGHTS,
    resolve_weights,
    score_trace,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "DEFAULT_WEIGHTS",
    "resolve_weights",
    "score_trace",
]
