"""Tests for the TraceCaliper comparison engine.

Covers VAL-CMP-001 through VAL-CMP-012 from the validation contract.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tracecaliper.models import (
    DEFAULT_WEIGHTS,
    DIMENSION_NAMES,
    Comparison,
    DimensionScore,
    FailureMode,
    Trace,
    TraceScore,
    TraceStep,
)
from tracecaliper.comparison import compare


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_trace_score(
    *,
    trace_id: str = "test-trace",
    scores: dict[str, float] | None = None,
    weights: dict[str, float] | None = None,
) -> TraceScore:
    """Build a TraceScore with given per-dimension scores and weights."""
    if scores is None:
        scores = {name: 0.5 for name in DIMENSION_NAMES}
    if weights is None:
        weights = dict(DEFAULT_WEIGHTS)
    dimensions = sorted(
        [
            DimensionScore(name=name, score=scores.get(name, 0.5), rationale="test")
            for name in DIMENSION_NAMES
        ],
        key=lambda d: d.name,
    )
    weighted_total = sum(weights.get(d.name, 0.0) * d.score for d in dimensions)
    return TraceScore(
        trace_id=trace_id,
        dimensions=dimensions,
        weights=dict(weights),
        weighted_total=weighted_total,
    )


def _make_failure_mode(code: str, severity: str = "medium") -> FailureMode:
    return FailureMode(code=code, severity=severity, evidence=f"Evidence for {code}.")


# ---------------------------------------------------------------------------
# VAL-CMP-001: Per-dimension delta equals candidate minus baseline
# ---------------------------------------------------------------------------


def test_per_dimension_delta_candidate_minus_baseline():
    """VAL-CMP-001: dimension_deltas[d] == candidate.dimensions[d].score - baseline.dimensions[d].score."""
    baseline_scores = {name: 0.3 for name in DIMENSION_NAMES}
    candidate_scores = {name: 0.7 for name in DIMENSION_NAMES}
    baseline = _make_trace_score(trace_id="baseline", scores=baseline_scores)
    candidate = _make_trace_score(trace_id="candidate", scores=candidate_scores)
    cmp = compare(baseline, candidate, [], [])
    for name in DIMENSION_NAMES:
        expected = candidate_scores[name] - baseline_scores[name]
        assert abs(cmp.dimension_deltas[name] - expected) < 1e-9, (
            f"dimension_deltas[{name!r}] expected {expected:.6f}, got {cmp.dimension_deltas[name]:.6f}"
        )


def test_per_dimension_delta_heterogeneous():
    """VAL-CMP-001: check with heterogeneous per-dimension scores."""
    baseline_scores = {
        "instruction_following": 0.2,
        "over_editing": 0.4,
        "repo_conventions": 0.6,
        "reviewability": 0.8,
        "security": 1.0,
        "task_completion": 0.1,
        "tests_passed": 0.5,
    }
    candidate_scores = {
        "instruction_following": 0.9,
        "over_editing": 0.1,
        "repo_conventions": 0.7,
        "reviewability": 0.3,
        "security": 0.5,
        "task_completion": 0.8,
        "tests_passed": 0.6,
    }
    baseline = _make_trace_score(trace_id="b", scores=baseline_scores)
    candidate = _make_trace_score(trace_id="c", scores=candidate_scores)
    cmp = compare(baseline, candidate, [], [])
    for name in DIMENSION_NAMES:
        expected = candidate_scores[name] - baseline_scores[name]
        assert abs(cmp.dimension_deltas[name] - expected) < 1e-9


# ---------------------------------------------------------------------------
# VAL-CMP-002: Aggregate delta equals candidate.weighted_total - baseline.weighted_total
# ---------------------------------------------------------------------------


def test_aggregate_delta_equals_weighted_total_difference():
    """VAL-CMP-002: aggregate_delta == candidate.weighted_total - baseline.weighted_total."""
    baseline = _make_trace_score(trace_id="b", scores={n: 0.3 for n in DIMENSION_NAMES})
    candidate = _make_trace_score(trace_id="c", scores={n: 0.8 for n in DIMENSION_NAMES})
    cmp = compare(baseline, candidate, [], [])
    expected = candidate.weighted_total - baseline.weighted_total
    assert abs(cmp.aggregate_delta - expected) < 1e-9


def test_aggregate_delta_with_partial_scores():
    """VAL-CMP-002: aggregate_delta with heterogeneous scores."""
    baseline_scores = {name: float(i) / 10 for i, name in enumerate(sorted(DIMENSION_NAMES))}
    candidate_scores = {name: float(i) / 7 for i, name in enumerate(sorted(DIMENSION_NAMES))}
    # Clamp candidate scores to [0, 1]
    candidate_scores = {k: min(v, 1.0) for k, v in candidate_scores.items()}
    baseline = _make_trace_score(trace_id="b", scores=baseline_scores)
    candidate = _make_trace_score(trace_id="c", scores=candidate_scores)
    cmp = compare(baseline, candidate, [], [])
    expected = candidate.weighted_total - baseline.weighted_total
    assert abs(cmp.aggregate_delta - expected) < 1e-9


# ---------------------------------------------------------------------------
# VAL-CMP-003: Aggregate delta consistent with per-dimension deltas under same weights
# ---------------------------------------------------------------------------


def test_aggregate_delta_consistent_with_per_dimension_deltas():
    """VAL-CMP-003: aggregate_delta == dot product of dimension_deltas and shared weights."""
    weights = dict(DEFAULT_WEIGHTS)
    baseline = _make_trace_score(
        trace_id="b",
        scores={n: 0.4 for n in DIMENSION_NAMES},
        weights=weights,
    )
    candidate = _make_trace_score(
        trace_id="c",
        scores={n: 0.7 for n in DIMENSION_NAMES},
        weights=weights,
    )
    cmp = compare(baseline, candidate, [], [])
    dot_product = sum(
        cmp.dimension_deltas[name] * weights[name] for name in DIMENSION_NAMES
    )
    assert abs(cmp.aggregate_delta - dot_product) < 1e-9


def test_aggregate_delta_consistent_custom_weights():
    """VAL-CMP-003: verify consistency with non-default weights."""
    custom_weights = {
        "tests_passed": 0.5,
        "task_completion": 0.5,
        "security": 0.0,
        "over_editing": 0.0,
        "repo_conventions": 0.0,
        "instruction_following": 0.0,
        "reviewability": 0.0,
    }
    baseline = _make_trace_score(
        trace_id="b",
        scores={"tests_passed": 0.2, "task_completion": 0.4, **{n: 0.5 for n in DIMENSION_NAMES if n not in ("tests_passed", "task_completion")}},
        weights=custom_weights,
    )
    candidate = _make_trace_score(
        trace_id="c",
        scores={"tests_passed": 0.8, "task_completion": 0.6, **{n: 0.5 for n in DIMENSION_NAMES if n not in ("tests_passed", "task_completion")}},
        weights=custom_weights,
    )
    cmp = compare(baseline, candidate, [], [])
    dot_product = sum(
        cmp.dimension_deltas[name] * custom_weights[name] for name in DIMENSION_NAMES
    )
    assert abs(cmp.aggregate_delta - dot_product) < 1e-9


# ---------------------------------------------------------------------------
# VAL-CMP-004: Identical traces produce a no-op comparison
# ---------------------------------------------------------------------------


def test_identical_traces_no_op():
    """VAL-CMP-004: Identical inputs yield zero deltas and empty failure-mode diffs."""
    ts = _make_trace_score(trace_id="same", scores={n: 0.6 for n in DIMENSION_NAMES})
    cmp = compare(ts, ts, [], [])
    for name in DIMENSION_NAMES:
        assert cmp.dimension_deltas[name] == 0.0
    assert cmp.aggregate_delta == 0.0
    assert cmp.introduced == []
    assert cmp.resolved == []
    assert cmp.persistent == []


def test_identical_traces_with_failure_modes_no_op():
    """VAL-CMP-004: Identical inputs with same failure modes yield empty introduced/resolved."""
    ts = _make_trace_score(trace_id="same")
    fm = _make_failure_mode("OVER_EDITING")
    cmp = compare(ts, ts, [fm], [fm])
    for name in DIMENSION_NAMES:
        assert cmp.dimension_deltas[name] == 0.0
    assert cmp.aggregate_delta == 0.0
    assert cmp.introduced == []
    assert cmp.resolved == []
    assert cmp.persistent == ["OVER_EDITING"]


# ---------------------------------------------------------------------------
# VAL-CMP-005: Introduced = candidate codes - baseline codes
# ---------------------------------------------------------------------------


def test_introduced_is_candidate_minus_baseline():
    """VAL-CMP-005: introduced == candidate failure-mode codes - baseline codes."""
    ts_b = _make_trace_score(trace_id="b")
    ts_c = _make_trace_score(trace_id="c")
    baseline_modes = [_make_failure_mode("OVER_EDITING"), _make_failure_mode("TEST_REGRESSION")]
    candidate_modes = [_make_failure_mode("SECURITY_FLAG"), _make_failure_mode("OVER_EDITING")]
    cmp = compare(ts_b, ts_c, baseline_modes, candidate_modes)
    assert cmp.introduced == ["SECURITY_FLAG"]


def test_introduced_empty_when_no_new_codes():
    """VAL-CMP-005: introduced is empty when candidate adds no new codes."""
    ts = _make_trace_score(trace_id="t")
    modes = [_make_failure_mode("CONVENTION_VIOLATION")]
    cmp = compare(ts, ts, modes, modes)
    assert cmp.introduced == []


# ---------------------------------------------------------------------------
# VAL-CMP-006: Resolved = baseline codes - candidate codes
# ---------------------------------------------------------------------------


def test_resolved_is_baseline_minus_candidate():
    """VAL-CMP-006: resolved == baseline failure-mode codes - candidate codes."""
    ts_b = _make_trace_score(trace_id="b")
    ts_c = _make_trace_score(trace_id="c")
    baseline_modes = [_make_failure_mode("OVER_EDITING"), _make_failure_mode("TEST_REGRESSION")]
    candidate_modes = [_make_failure_mode("OVER_EDITING"), _make_failure_mode("SECURITY_FLAG")]
    cmp = compare(ts_b, ts_c, baseline_modes, candidate_modes)
    assert cmp.resolved == ["TEST_REGRESSION"]


def test_resolved_empty_when_no_codes_removed():
    """VAL-CMP-006: resolved is empty when candidate retains all baseline codes."""
    ts_b = _make_trace_score(trace_id="b")
    ts_c = _make_trace_score(trace_id="c")
    baseline_modes = [_make_failure_mode("OVER_EDITING")]
    candidate_modes = [_make_failure_mode("OVER_EDITING"), _make_failure_mode("SECURITY_FLAG")]
    cmp = compare(ts_b, ts_c, baseline_modes, candidate_modes)
    assert cmp.resolved == []


# ---------------------------------------------------------------------------
# VAL-CMP-007: Persistent = intersection of baseline and candidate codes
# ---------------------------------------------------------------------------


def test_persistent_is_intersection():
    """VAL-CMP-007: persistent == intersection of baseline and candidate codes."""
    ts_b = _make_trace_score(trace_id="b")
    ts_c = _make_trace_score(trace_id="c")
    baseline_modes = [
        _make_failure_mode("OVER_EDITING"),
        _make_failure_mode("TEST_REGRESSION"),
        _make_failure_mode("CONVENTION_VIOLATION"),
    ]
    candidate_modes = [
        _make_failure_mode("OVER_EDITING"),
        _make_failure_mode("SECURITY_FLAG"),
        _make_failure_mode("CONVENTION_VIOLATION"),
    ]
    cmp = compare(ts_b, ts_c, baseline_modes, candidate_modes)
    assert cmp.persistent == ["CONVENTION_VIOLATION", "OVER_EDITING"]


def test_persistent_empty_when_no_overlap():
    """VAL-CMP-007: persistent is empty when no overlap between code sets."""
    ts_b = _make_trace_score(trace_id="b")
    ts_c = _make_trace_score(trace_id="c")
    baseline_modes = [_make_failure_mode("TEST_REGRESSION")]
    candidate_modes = [_make_failure_mode("SECURITY_FLAG")]
    cmp = compare(ts_b, ts_c, baseline_modes, candidate_modes)
    assert cmp.persistent == []


# ---------------------------------------------------------------------------
# VAL-CMP-008: Introduced / resolved / persistent are mutually disjoint
# ---------------------------------------------------------------------------


def test_diff_sets_mutually_disjoint():
    """VAL-CMP-008: No code appears in more than one of introduced/resolved/persistent."""
    ts_b = _make_trace_score(trace_id="b")
    ts_c = _make_trace_score(trace_id="c")
    baseline_modes = [
        _make_failure_mode("OVER_EDITING"),
        _make_failure_mode("TEST_REGRESSION"),
        _make_failure_mode("CONVENTION_VIOLATION"),
    ]
    candidate_modes = [
        _make_failure_mode("SECURITY_FLAG"),
        _make_failure_mode("TEST_REGRESSION"),
        _make_failure_mode("INCOMPLETE_TASK"),
    ]
    cmp = compare(ts_b, ts_c, baseline_modes, candidate_modes)
    intro = set(cmp.introduced)
    res = set(cmp.resolved)
    pers = set(cmp.persistent)
    assert intro & res == set()
    assert intro & pers == set()
    assert res & pers == set()


def test_diff_sets_cover_all_codes():
    """VAL-CMP-008: Every code from baseline or candidate appears in exactly one set."""
    ts_b = _make_trace_score(trace_id="b")
    ts_c = _make_trace_score(trace_id="c")
    baseline_codes = {"OVER_EDITING", "TEST_REGRESSION"}
    candidate_codes = {"TEST_REGRESSION", "SECURITY_FLAG"}
    baseline_modes = [_make_failure_mode(c) for c in baseline_codes]
    candidate_modes = [_make_failure_mode(c) for c in candidate_codes]
    cmp = compare(ts_b, ts_c, baseline_modes, candidate_modes)
    all_codes = baseline_codes | candidate_codes
    covered = set(cmp.introduced) | set(cmp.resolved) | set(cmp.persistent)
    assert covered == all_codes


# ---------------------------------------------------------------------------
# VAL-CMP-009: Brand-new failure modes → all in introduced, resolved is empty
# ---------------------------------------------------------------------------


def test_brand_new_failure_modes_in_introduced():
    """VAL-CMP-009: Candidate-only codes land in introduced; resolved is empty."""
    ts_b = _make_trace_score(trace_id="b")
    ts_c = _make_trace_score(trace_id="c")
    cmp = compare(
        ts_b, ts_c,
        [],  # baseline has no failure modes
        [_make_failure_mode("SECURITY_FLAG"), _make_failure_mode("OVER_EDITING")],
    )
    assert set(cmp.introduced) == {"SECURITY_FLAG", "OVER_EDITING"}
    assert cmp.resolved == []
    assert cmp.persistent == []


# ---------------------------------------------------------------------------
# VAL-CMP-010: Only resolved failure modes
# ---------------------------------------------------------------------------


def test_all_baseline_failure_modes_resolved():
    """VAL-CMP-010: Candidate fixes all failures → introduced=∅, persistent=∅, resolved=all."""
    ts_b = _make_trace_score(trace_id="b")
    ts_c = _make_trace_score(trace_id="c")
    baseline_modes = [
        _make_failure_mode("OVER_EDITING"),
        _make_failure_mode("TEST_REGRESSION"),
    ]
    cmp = compare(ts_b, ts_c, baseline_modes, [])
    assert cmp.introduced == []
    assert cmp.persistent == []
    assert set(cmp.resolved) == {"OVER_EDITING", "TEST_REGRESSION"}


# ---------------------------------------------------------------------------
# VAL-CMP-011: Per-dimension deltas may be negative
# ---------------------------------------------------------------------------


def test_negative_dimension_delta_preserved():
    """VAL-CMP-011: Regression on a dimension produces a negative delta (no clamping)."""
    baseline_scores = {name: 0.9 for name in DIMENSION_NAMES}
    candidate_scores = {name: 0.2 for name in DIMENSION_NAMES}
    baseline = _make_trace_score(trace_id="b", scores=baseline_scores)
    candidate = _make_trace_score(trace_id="c", scores=candidate_scores)
    cmp = compare(baseline, candidate, [], [])
    for name in DIMENSION_NAMES:
        assert cmp.dimension_deltas[name] < 0, (
            f"Expected negative delta for {name}, got {cmp.dimension_deltas[name]}"
        )


def test_mixed_positive_negative_deltas():
    """VAL-CMP-011: Some dimensions improve, some regress - negatives not clamped."""
    ts_b = _make_trace_score(
        trace_id="b",
        scores={"tests_passed": 0.8, **{n: 0.5 for n in DIMENSION_NAMES if n != "tests_passed"}},
    )
    ts_c = _make_trace_score(
        trace_id="c",
        scores={"tests_passed": 0.3, **{n: 0.7 for n in DIMENSION_NAMES if n != "tests_passed"}},
    )
    cmp = compare(ts_b, ts_c, [], [])
    assert cmp.dimension_deltas["tests_passed"] < 0
    for name in DIMENSION_NAMES:
        if name != "tests_passed":
            assert cmp.dimension_deltas[name] > 0


# ---------------------------------------------------------------------------
# VAL-CMP-012: Comparison output is deterministic
# ---------------------------------------------------------------------------


def test_comparison_deterministic():
    """VAL-CMP-012: Two invocations on the same inputs produce byte-identical Comparisons."""
    ts_b = _make_trace_score(
        trace_id="b",
        scores={n: 0.4 for n in DIMENSION_NAMES},
    )
    ts_c = _make_trace_score(
        trace_id="c",
        scores={n: 0.7 for n in DIMENSION_NAMES},
    )
    modes_b = [_make_failure_mode("OVER_EDITING"), _make_failure_mode("TEST_REGRESSION")]
    modes_c = [_make_failure_mode("SECURITY_FLAG"), _make_failure_mode("OVER_EDITING")]
    cmp1 = compare(ts_b, ts_c, modes_b, modes_c)
    cmp2 = compare(ts_b, ts_c, modes_b, modes_c)
    assert cmp1.model_dump_json(indent=2) == cmp2.model_dump_json(indent=2)


def test_comparison_collections_sorted():
    """VAL-CMP-012: introduced/resolved/persistent are sorted (deterministic ordering)."""
    ts_b = _make_trace_score(trace_id="b")
    ts_c = _make_trace_score(trace_id="c")
    baseline_modes = [
        _make_failure_mode("TEST_REGRESSION"),
        _make_failure_mode("OVER_EDITING"),
        _make_failure_mode("CONVENTION_VIOLATION"),
    ]
    candidate_modes = [
        _make_failure_mode("SECURITY_FLAG"),
        _make_failure_mode("INCOMPLETE_TASK"),
    ]
    cmp = compare(ts_b, ts_c, baseline_modes, candidate_modes)
    assert cmp.introduced == sorted(cmp.introduced)
    assert cmp.resolved == sorted(cmp.resolved)
    assert cmp.persistent == sorted(cmp.persistent)


def test_comparison_dimension_deltas_all_seven():
    """VAL-CMP-001 / VAL-CMP-012: dimension_deltas contains exactly the 7 rubric dimensions."""
    ts_b = _make_trace_score(trace_id="b")
    ts_c = _make_trace_score(trace_id="c")
    cmp = compare(ts_b, ts_c, [], [])
    assert set(cmp.dimension_deltas.keys()) == set(DIMENSION_NAMES)
