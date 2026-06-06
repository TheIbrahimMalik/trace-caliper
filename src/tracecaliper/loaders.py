"""Trace and Suite loaders for TraceCaliper.

Provides a clean interface for loading artifacts from the filesystem so
that future trace-source adapters (Factory, GitHub PR, NDJSON) can be
added without modifying the scoring or comparison engine.

Public API:

- :func:`load_trace`: Load and validate a :class:`~tracecaliper.models.Trace`
  from a JSON file.
- :func:`load_suite`: Load and validate a :class:`~tracecaliper.models.Suite`
  from a YAML file.

Both functions raise descriptive errors on missing files, parse failures, and
schema violations.  They never make network calls or read files outside the
provided path.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from tracecaliper.models import Suite, Trace


def load_trace(path: str | Path) -> Trace:
    """Load and validate a :class:`~tracecaliper.models.Trace` from a JSON file.

    Args:
        path: Path to the trace JSON file.

    Returns:
        Validated :class:`~tracecaliper.models.Trace` instance.

    Raises:
        FileNotFoundError: If the file does not exist, with the path embedded
            in the message.
        json.JSONDecodeError: If the file contains invalid JSON syntax.
        pydantic.ValidationError: If the JSON parses but fails model validation.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Trace file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FileNotFoundError(f"Cannot read trace file {path}: {exc}") from exc
    raw = json.loads(text)
    return Trace.model_validate(raw)


def load_suite(path: str | Path) -> Suite:
    """Load and validate a :class:`~tracecaliper.models.Suite` from a YAML file.

    Args:
        path: Path to the suite YAML file.

    Returns:
        Validated :class:`~tracecaliper.models.Suite` instance.

    Raises:
        FileNotFoundError: If the file does not exist, with the path embedded
            in the message.
        yaml.YAMLError: If the file contains invalid YAML syntax.
        pydantic.ValidationError: If the YAML parses but fails model validation.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Suite file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FileNotFoundError(f"Cannot read suite file {path}: {exc}") from exc
    raw = yaml.safe_load(text)
    return Suite.model_validate(raw)


__all__ = ["load_trace", "load_suite"]
