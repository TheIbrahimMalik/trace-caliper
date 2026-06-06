"""Comparison engine for TraceCaliper.

:func:`compare` produces a :class:`~tracecaliper.models.Comparison` from a
pair of :class:`~tracecaliper.models.TraceScore` objects and their associated
:class:`~tracecaliper.models.FailureMode` lists.

Per-dimension deltas are candidate minus baseline.  Aggregate delta is
``candidate.weighted_total - baseline.weighted_total``.  Failure-mode sets
(introduced / resolved / persistent) are derived from the set-difference and
intersection of the two failure-mode code sets, then sorted for determinism.

All computations are pure and deterministic.  The function never mutates its
inputs.
"""

from __future__ import annotations

from tracecaliper.models import (
    DIMENSION_NAMES,
    Comparison,
    FailureMode,
    TraceScore,
)


def compare(
    baseline: TraceScore,
    candidate: TraceScore,
    baseline_modes: list[FailureMode],
    candidate_modes: list[FailureMode],
) -> Comparison:
    """Compare a candidate :class:`TraceScore` against a baseline.

    Args:
        baseline: The baseline trace score.
        candidate: The candidate trace score.
        baseline_modes: Failure modes detected for the baseline trace.
        candidate_modes: Failure modes detected for the candidate trace.

    Returns:
        :class:`~tracecaliper.models.Comparison` with:

        - ``dimension_deltas``: candidate score minus baseline score for each
          of the seven rubric dimensions (sorted by dimension name).
        - ``aggregate_delta``: ``candidate.weighted_total - baseline.weighted_total``.
        - ``introduced``: failure-mode codes present in the candidate only
          (set-difference candidate − baseline), sorted.
        - ``resolved``: failure-mode codes present in the baseline only
          (set-difference baseline − candidate), sorted.
        - ``persistent``: failure-mode codes present in both
          (set-intersection), sorted.
    """
    baseline_dim = {d.name: d.score for d in baseline.dimensions}
    candidate_dim = {d.name: d.score for d in candidate.dimensions}

    dimension_deltas = {
        name: candidate_dim[name] - baseline_dim[name]
        for name in DIMENSION_NAMES
    }

    aggregate_delta = candidate.weighted_total - baseline.weighted_total

    baseline_codes: set[str] = {m.code for m in baseline_modes}
    candidate_codes: set[str] = {m.code for m in candidate_modes}

    introduced = sorted(candidate_codes - baseline_codes)
    resolved = sorted(baseline_codes - candidate_codes)
    persistent = sorted(baseline_codes & candidate_codes)

    return Comparison(
        baseline=baseline,
        candidate=candidate,
        dimension_deltas=dimension_deltas,
        aggregate_delta=aggregate_delta,
        introduced=introduced,
        resolved=resolved,
        persistent=persistent,
    )


__all__ = ["compare"]
