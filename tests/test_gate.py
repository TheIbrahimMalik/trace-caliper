"""Tests for the TraceCaliper release gate logic.

Covers VAL-GATE-001 through VAL-GATE-012 from the validation contract.
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
    GateDecision,
    Trace,
    TraceScore,
    TraceStep,
)
from tracecaliper.comparison import compare
from tracecaliper.gate import decide
from tracecaliper.loaders import load_trace, load_suite
from tracecaliper.scoring import resolve_weights, score_trace


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_trace_score(
    *,
    trace_id: str = "test-trace",
    scores: dict[str, float] | None = None,
    weights: dict[str, float] | None = None,
) -> TraceScore:
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


def _make_comparison(
    *,
    baseline_scores: dict[str, float] | None = None,
    candidate_scores: dict[str, float] | None = None,
    baseline_modes: list[FailureMode] | None = None,
    candidate_modes: list[FailureMode] | None = None,
    weights: dict[str, float] | None = None,
) -> Comparison:
    if baseline_modes is None:
        baseline_modes = []
    if candidate_modes is None:
        candidate_modes = []
    ts_b = _make_trace_score(trace_id="b", scores=baseline_scores, weights=weights)
    ts_c = _make_trace_score(trace_id="c", scores=candidate_scores, weights=weights)
    return compare(ts_b, ts_c, baseline_modes, candidate_modes)


# ---------------------------------------------------------------------------
# VAL-GATE-001: GateDecision values restricted to PASS/HOLD/INVESTIGATE
# ---------------------------------------------------------------------------


def test_gate_decision_outcome_restricted_to_valid_values():
    """VAL-GATE-001: All gate outcomes are PASS, HOLD, or INVESTIGATE."""
    valid_outcomes = {"PASS", "HOLD", "INVESTIGATE"}
    scenarios = [
        # Identical (PASS)
        _make_comparison(),
        # Pure improvement (PASS)
        _make_comparison(
            candidate_scores={n: 1.0 for n in DIMENSION_NAMES},
            baseline_modes=[_make_failure_mode("OVER_EDITING")],
        ),
        # Security introduced (HOLD)
        _make_comparison(candidate_modes=[_make_failure_mode("SECURITY_FLAG", "critical")]),
        # Pure regression (HOLD)
        _make_comparison(candidate_modes=[_make_failure_mode("OVER_EDITING")]),
        # Mixed signals (INVESTIGATE)
        _make_comparison(
            baseline_modes=[_make_failure_mode("OVER_EDITING")],
            candidate_modes=[_make_failure_mode("TEST_REGRESSION")],
        ),
    ]
    for cmp in scenarios:
        decision = decide(cmp)
        assert decision.decision in valid_outcomes, (
            f"Unexpected decision value: {decision.decision!r}"
        )


# ---------------------------------------------------------------------------
# VAL-GATE-002: Introduced SECURITY_FLAG → HOLD or INVESTIGATE, never PASS
# ---------------------------------------------------------------------------


def test_introduced_security_flag_never_pass():
    """VAL-GATE-002: SECURITY_FLAG in introduced must not yield PASS."""
    cmp = _make_comparison(
        candidate_modes=[_make_failure_mode("SECURITY_FLAG", "critical")],
    )
    assert "SECURITY_FLAG" in cmp.introduced
    decision = decide(cmp)
    assert decision.decision in {"HOLD", "INVESTIGATE"}
    assert decision.decision != "PASS"


def test_introduced_security_flag_with_improvement_never_pass():
    """VAL-GATE-002: SECURITY_FLAG in introduced even with resolved modes must not yield PASS."""
    cmp = _make_comparison(
        baseline_modes=[_make_failure_mode("OVER_EDITING")],
        candidate_modes=[_make_failure_mode("SECURITY_FLAG", "critical")],
    )
    assert "SECURITY_FLAG" in cmp.introduced
    decision = decide(cmp)
    assert decision.decision != "PASS"


def test_introduced_security_flag_with_positive_delta_never_pass():
    """VAL-GATE-002: positive aggregate_delta does not override SECURITY_FLAG block."""
    cmp = _make_comparison(
        candidate_scores={n: 0.9 for n in DIMENSION_NAMES},
        candidate_modes=[_make_failure_mode("SECURITY_FLAG", "critical")],
    )
    assert "SECURITY_FLAG" in cmp.introduced
    assert cmp.aggregate_delta > 0
    decision = decide(cmp)
    assert decision.decision != "PASS"


# ---------------------------------------------------------------------------
# VAL-GATE-003: Persistent SECURITY_FLAG → HOLD or INVESTIGATE, never PASS
# ---------------------------------------------------------------------------


def test_persistent_security_flag_never_pass():
    """VAL-GATE-003: SECURITY_FLAG in persistent must not yield PASS."""
    sf = _make_failure_mode("SECURITY_FLAG", "critical")
    cmp = _make_comparison(
        baseline_modes=[sf],
        candidate_modes=[sf],
    )
    assert "SECURITY_FLAG" in cmp.persistent
    decision = decide(cmp)
    assert decision.decision != "PASS"
    assert decision.decision in {"HOLD", "INVESTIGATE"}


def test_persistent_security_flag_with_other_resolved():
    """VAL-GATE-003: Persistent SECURITY_FLAG blocks PASS even when other modes resolved."""
    sf = _make_failure_mode("SECURITY_FLAG", "critical")
    oe = _make_failure_mode("OVER_EDITING")
    cmp = _make_comparison(
        baseline_modes=[sf, oe],
        candidate_modes=[sf],  # resolved OVER_EDITING but persistent SECURITY_FLAG
    )
    assert "SECURITY_FLAG" in cmp.persistent
    assert "OVER_EDITING" in cmp.resolved
    decision = decide(cmp)
    assert decision.decision != "PASS"


# ---------------------------------------------------------------------------
# VAL-GATE-004: Pure improvement yields PASS
# ---------------------------------------------------------------------------


def test_pure_improvement_yields_pass():
    """VAL-GATE-004: resolved non-empty, introduced empty, no security flag, delta>=0 → PASS."""
    cmp = _make_comparison(
        candidate_scores={n: 0.8 for n in DIMENSION_NAMES},
        baseline_modes=[_make_failure_mode("OVER_EDITING")],
        candidate_modes=[],
    )
    assert cmp.resolved != []
    assert cmp.introduced == []
    assert cmp.aggregate_delta >= 0
    decision = decide(cmp)
    assert decision.decision == "PASS"


def test_pure_improvement_zero_delta_yields_pass():
    """VAL-GATE-004: pure improvement with delta==0 also yields PASS."""
    cmp = _make_comparison(
        # Same scores (delta=0) but resolved failure modes
        baseline_modes=[_make_failure_mode("INCOMPLETE_TASK", "high")],
        candidate_modes=[],
    )
    assert cmp.resolved != []
    assert cmp.introduced == []
    assert cmp.aggregate_delta == 0.0
    decision = decide(cmp)
    assert decision.decision == "PASS"


# ---------------------------------------------------------------------------
# VAL-GATE-005: Identical traces yield PASS
# ---------------------------------------------------------------------------


def test_identical_traces_yield_pass():
    """VAL-GATE-005: Identical comparison (zero deltas, empty diffs, no failures) → PASS."""
    ts = _make_trace_score(trace_id="same", scores={n: 0.6 for n in DIMENSION_NAMES})
    cmp = compare(ts, ts, [], [])
    assert cmp.aggregate_delta == 0.0
    assert cmp.introduced == []
    assert cmp.resolved == []
    assert cmp.persistent == []
    decision = decide(cmp)
    assert decision.decision == "PASS"
    assert len(decision.rationale) >= 1


def test_identical_traces_rationale_non_empty():
    """VAL-GATE-005: Rationale explains the no-op outcome."""
    ts = _make_trace_score(trace_id="same")
    cmp = compare(ts, ts, [], [])
    decision = decide(cmp)
    assert decision.decision == "PASS"
    assert len(decision.rationale) >= 1
    for entry in decision.rationale:
        assert entry.strip() != ""


# ---------------------------------------------------------------------------
# VAL-GATE-006: Mixed signals yield INVESTIGATE
# ---------------------------------------------------------------------------


def test_mixed_signals_yield_investigate():
    """VAL-GATE-006: introduced non-empty and resolved non-empty (no security) → INVESTIGATE."""
    cmp = _make_comparison(
        baseline_modes=[_make_failure_mode("OVER_EDITING")],
        candidate_modes=[_make_failure_mode("TEST_REGRESSION")],
    )
    assert cmp.introduced != []
    assert cmp.resolved != []
    assert "SECURITY_FLAG" not in cmp.introduced
    assert "SECURITY_FLAG" not in cmp.persistent
    decision = decide(cmp)
    assert decision.decision == "INVESTIGATE"


def test_mixed_signals_with_negative_delta_still_investigate():
    """VAL-GATE-006: Mixed signals with negative delta → INVESTIGATE (not HOLD)."""
    cmp = _make_comparison(
        baseline_scores={n: 0.8 for n in DIMENSION_NAMES},
        candidate_scores={n: 0.3 for n in DIMENSION_NAMES},
        baseline_modes=[_make_failure_mode("OVER_EDITING")],
        candidate_modes=[_make_failure_mode("TEST_REGRESSION")],
    )
    assert cmp.introduced != []
    assert cmp.resolved != []
    assert cmp.aggregate_delta < 0
    decision = decide(cmp)
    assert decision.decision == "INVESTIGATE"


# ---------------------------------------------------------------------------
# VAL-GATE-007: Negative aggregate delta blocks PASS
# ---------------------------------------------------------------------------


def test_negative_delta_blocks_pass():
    """VAL-GATE-007: Negative aggregate_delta must not yield PASS."""
    cmp = _make_comparison(
        baseline_scores={n: 0.9 for n in DIMENSION_NAMES},
        candidate_scores={n: 0.1 for n in DIMENSION_NAMES},
    )
    assert cmp.aggregate_delta < 0
    decision = decide(cmp)
    assert decision.decision in {"HOLD", "INVESTIGATE"}
    assert decision.decision != "PASS"


def test_negative_delta_no_failure_modes_blocks_pass():
    """VAL-GATE-007: Negative delta with no failure mode changes → HOLD or INVESTIGATE."""
    cmp = _make_comparison(
        baseline_scores={n: 0.8 for n in DIMENSION_NAMES},
        candidate_scores={n: 0.2 for n in DIMENSION_NAMES},
        baseline_modes=[],
        candidate_modes=[],
    )
    assert cmp.aggregate_delta < 0
    assert cmp.introduced == []
    assert cmp.resolved == []
    decision = decide(cmp)
    assert decision.decision != "PASS"


# ---------------------------------------------------------------------------
# VAL-GATE-008: Rationale list is always non-empty
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario_name,cmp", [
    (
        "PASS identical",
        _make_comparison(),
    ),
])
def test_rationale_always_non_empty_parameterized(scenario_name, cmp):
    """VAL-GATE-008: rationale always has at least one non-empty string."""
    decision = decide(cmp)
    assert len(decision.rationale) >= 1
    for entry in decision.rationale:
        assert isinstance(entry, str) and entry.strip() != ""


def test_rationale_non_empty_for_pass():
    """VAL-GATE-008: PASS decision has non-empty rationale."""
    cmp = _make_comparison()
    decision = decide(cmp)
    assert decision.decision == "PASS"
    assert len(decision.rationale) >= 1


def test_rationale_non_empty_for_hold():
    """VAL-GATE-008: HOLD decision has non-empty rationale."""
    cmp = _make_comparison(
        candidate_modes=[_make_failure_mode("SECURITY_FLAG", "critical")],
    )
    decision = decide(cmp)
    assert decision.decision in {"HOLD", "INVESTIGATE"}
    assert len(decision.rationale) >= 1


def test_rationale_non_empty_for_investigate():
    """VAL-GATE-008: INVESTIGATE decision has non-empty rationale."""
    cmp = _make_comparison(
        baseline_modes=[_make_failure_mode("OVER_EDITING")],
        candidate_modes=[_make_failure_mode("TEST_REGRESSION")],
    )
    decision = decide(cmp)
    assert decision.decision == "INVESTIGATE"
    assert len(decision.rationale) >= 1


# ---------------------------------------------------------------------------
# VAL-GATE-009: Rationale entries cite concrete signals
# ---------------------------------------------------------------------------


def test_rationale_cites_security_flag_when_introduced():
    """VAL-GATE-009: SECURITY_FLAG introduction is mentioned in rationale."""
    cmp = _make_comparison(
        candidate_modes=[_make_failure_mode("SECURITY_FLAG", "critical")],
    )
    decision = decide(cmp)
    full_rationale = " ".join(decision.rationale)
    assert "SECURITY_FLAG" in full_rationale


def test_rationale_cites_security_flag_when_persistent():
    """VAL-GATE-009: Persistent SECURITY_FLAG is mentioned in rationale."""
    sf = _make_failure_mode("SECURITY_FLAG", "critical")
    cmp = _make_comparison(baseline_modes=[sf], candidate_modes=[sf])
    decision = decide(cmp)
    full_rationale = " ".join(decision.rationale)
    assert "SECURITY_FLAG" in full_rationale


def test_rationale_cites_delta_sign():
    """VAL-GATE-009: Rationale references aggregate delta sign for HOLD from negative delta."""
    cmp = _make_comparison(
        baseline_scores={n: 0.9 for n in DIMENSION_NAMES},
        candidate_scores={n: 0.1 for n in DIMENSION_NAMES},
    )
    decision = decide(cmp)
    assert decision.decision in {"HOLD", "INVESTIGATE"}
    full_rationale = " ".join(decision.rationale)
    # Should mention delta (negative/regression) or a concrete signal
    has_concrete_signal = any(
        token in full_rationale
        for token in ["delta", "aggregate", "negative", "regression", "HOLD", "INVESTIGATE"]
    )
    assert has_concrete_signal


def test_rationale_cites_failure_mode_codes_for_mixed():
    """VAL-GATE-009: Mixed signals rationale mentions failure mode codes."""
    cmp = _make_comparison(
        baseline_modes=[_make_failure_mode("OVER_EDITING")],
        candidate_modes=[_make_failure_mode("TEST_REGRESSION")],
    )
    decision = decide(cmp)
    full_rationale = " ".join(decision.rationale)
    assert "OVER_EDITING" in full_rationale or "TEST_REGRESSION" in full_rationale


# ---------------------------------------------------------------------------
# VAL-GATE-010: Gate decision is reproducible across runs
# ---------------------------------------------------------------------------


def test_gate_decision_reproducible():
    """VAL-GATE-010: Two invocations on the same Comparison yield byte-identical GateDecision."""
    cmp = _make_comparison(
        baseline_modes=[_make_failure_mode("OVER_EDITING")],
        candidate_modes=[_make_failure_mode("SECURITY_FLAG", "critical")],
    )
    d1 = decide(cmp)
    d2 = decide(cmp)
    assert d1.model_dump_json(indent=2) == d2.model_dump_json(indent=2)


def test_gate_decision_reproducible_various_scenarios():
    """VAL-GATE-010: Reproducibility across PASS, HOLD, INVESTIGATE outcomes."""
    scenarios = [
        # PASS
        _make_comparison(),
        # HOLD via security introduced
        _make_comparison(candidate_modes=[_make_failure_mode("SECURITY_FLAG", "critical")]),
        # INVESTIGATE via mixed signals
        _make_comparison(
            baseline_modes=[_make_failure_mode("OVER_EDITING")],
            candidate_modes=[_make_failure_mode("TEST_REGRESSION")],
        ),
    ]
    for cmp in scenarios:
        d1 = decide(cmp)
        d2 = decide(cmp)
        assert d1.model_dump_json(indent=2) == d2.model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# VAL-GATE-011: Scoring is byte-identical across repeated invocations
# ---------------------------------------------------------------------------


def test_scoring_byte_identical():
    """VAL-GATE-011: score_trace produces byte-identical JSON across two invocations."""
    from tracecaliper.scoring import score_trace
    trace = load_trace("examples/traces/skill-v1.json")
    weights = resolve_weights(None)
    s1 = score_trace(trace, weights)
    s2 = score_trace(trace, weights)
    assert s1.model_dump_json(indent=2) == s2.model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# VAL-GATE-012: Full compare pipeline is byte-identical across repeated invocations
# ---------------------------------------------------------------------------


def test_full_pipeline_byte_identical():
    """VAL-GATE-012: Full pipeline (score + detect + compare + decide) is byte-deterministic."""
    from tracecaliper.failure_modes import detect_failure_modes
    from tracecaliper.scoring import score_trace
    suite = load_suite("examples/suites/python-api.yml")
    weights = resolve_weights(suite.weights)
    baseline = load_trace("examples/traces/skill-v1.json")
    candidate = load_trace("examples/traces/skill-v2.json")

    def run_pipeline():
        b_score = score_trace(baseline, weights)
        c_score = score_trace(candidate, weights)
        b_modes = detect_failure_modes(baseline)
        c_modes = detect_failure_modes(candidate)
        cmp = compare(b_score, c_score, b_modes, c_modes)
        decision = decide(cmp)
        return cmp, decision

    cmp1, d1 = run_pipeline()
    cmp2, d2 = run_pipeline()
    assert cmp1.model_dump_json(indent=2) == cmp2.model_dump_json(indent=2)
    assert d1.model_dump_json(indent=2) == d2.model_dump_json(indent=2)


def test_full_pipeline_produces_valid_decision():
    """VAL-GATE-012: Full pipeline produces a valid GateDecision with non-empty rationale."""
    from tracecaliper.failure_modes import detect_failure_modes
    from tracecaliper.scoring import score_trace
    suite = load_suite("examples/suites/python-api.yml")
    weights = resolve_weights(suite.weights)
    baseline = load_trace("examples/traces/skill-v1.json")
    candidate = load_trace("examples/traces/skill-v2.json")
    b_score = score_trace(baseline, weights)
    c_score = score_trace(candidate, weights)
    b_modes = detect_failure_modes(baseline)
    c_modes = detect_failure_modes(candidate)
    cmp = compare(b_score, c_score, b_modes, c_modes)
    decision = decide(cmp)
    assert decision.decision in {"PASS", "HOLD", "INVESTIGATE"}
    assert len(decision.rationale) >= 1
    for entry in decision.rationale:
        assert entry.strip() != ""


# ---------------------------------------------------------------------------
# Fix: negative-aggregate-delta with resolved modes — rationale must cite codes
# ---------------------------------------------------------------------------


def test_negative_delta_with_resolved_modes_rationale_cites_codes():
    """BLOCKING fix: Rule 7 (negative delta) with resolved modes must cite them in rationale.

    When aggregate_delta < 0 and some failure modes were resolved, the rationale
    must mention the resolved codes — never emit 'no failure-mode changes'.
    """
    cmp = _make_comparison(
        baseline_scores={n: 0.8 for n in DIMENSION_NAMES},
        candidate_scores={n: 0.2 for n in DIMENSION_NAMES},
        baseline_modes=[_make_failure_mode("OVER_EDITING")],
        candidate_modes=[],
    )
    # Preconditions
    assert cmp.aggregate_delta < 0, "aggregate_delta must be negative for this test"
    assert cmp.resolved == ["OVER_EDITING"], "OVER_EDITING must be resolved"
    assert cmp.introduced == [], "nothing must be introduced"

    decision = decide(cmp)
    assert decision.decision == "HOLD", f"expected HOLD but got {decision.decision}"

    full_rationale = " ".join(decision.rationale)
    # Resolved code must appear in rationale
    assert "OVER_EDITING" in full_rationale, (
        f"rationale must cite resolved code 'OVER_EDITING'; got: {full_rationale!r}"
    )
    # Must NOT claim there were no failure-mode changes
    assert "no failure-mode changes" not in full_rationale.lower(), (
        f"rationale must not say 'no failure-mode changes' when resolved is non-empty; "
        f"got: {full_rationale!r}"
    )


def test_negative_delta_with_resolved_modes_rationale_never_says_no_changes():
    """BLOCKING fix: negative-delta + resolved modes → rationale must NOT say 'no failure-mode changes'."""
    cmp = _make_comparison(
        baseline_scores={n: 0.9 for n in DIMENSION_NAMES},
        candidate_scores={n: 0.1 for n in DIMENSION_NAMES},
        baseline_modes=[
            _make_failure_mode("TEST_REGRESSION", "high"),
            _make_failure_mode("INCOMPLETE_TASK"),
        ],
        candidate_modes=[],
    )
    assert cmp.aggregate_delta < 0
    assert set(cmp.resolved) == {"TEST_REGRESSION", "INCOMPLETE_TASK"}
    assert cmp.introduced == []

    decision = decide(cmp)
    full_rationale = " ".join(decision.rationale)
    assert "TEST_REGRESSION" in full_rationale or "INCOMPLETE_TASK" in full_rationale, (
        "rationale must mention at least one resolved code"
    )
    assert "no failure-mode changes" not in full_rationale.lower(), (
        "rationale must not say 'no failure-mode changes' when resolved modes exist"
    )


# ---------------------------------------------------------------------------
# Fix: offsetting per-dimension deltas — must NOT be labeled identical/no-op
# ---------------------------------------------------------------------------


def test_offsetting_deltas_not_labeled_no_op():
    """NON-BLOCKING fix: offsetting per-dimension deltas (aggregate==0) must not be labeled identical.

    When tests_passed improves and task_completion regresses by the same amount
    (same weight) so that aggregate_delta==0, but per-dimension deltas are not
    all zero, the no-op/identical rationale must NOT be emitted.
    """
    # tests_passed and task_completion have weight 0.25 each.
    # +0.2 on tests_passed and -0.2 on task_completion → aggregate delta = 0.
    baseline_scores = {n: 0.5 for n in DIMENSION_NAMES}
    candidate_scores = dict(baseline_scores)
    candidate_scores["tests_passed"] = 0.7   # +0.2
    candidate_scores["task_completion"] = 0.3  # -0.2

    cmp = _make_comparison(
        baseline_scores=baseline_scores,
        candidate_scores=candidate_scores,
        baseline_modes=[],
        candidate_modes=[],
    )

    # Verify preconditions
    assert cmp.aggregate_delta == pytest.approx(0.0), (
        f"aggregate_delta must be 0.0, got {cmp.aggregate_delta}"
    )
    assert cmp.introduced == []
    assert cmp.resolved == []
    assert cmp.dimension_deltas["tests_passed"] == pytest.approx(0.2)
    assert cmp.dimension_deltas["task_completion"] == pytest.approx(-0.2)

    decision = decide(cmp)

    full_rationale = " ".join(decision.rationale)
    # The no-op/identical rationale phrase must NOT appear
    assert "identical comparison" not in full_rationale.lower(), (
        f"offsetting deltas must not produce 'identical comparison' rationale; "
        f"got: {full_rationale!r}"
    )
    assert "identical" not in full_rationale.lower() or "not identical" in full_rationale.lower(), (
        f"rationale must not label offsetting-delta comparison as identical; "
        f"got: {full_rationale!r}"
    )


# ---------------------------------------------------------------------------
# VAL-EX-007: v1 and v2 traces produce distinct failure-mode sets
# VAL-EX-008: End-to-end pipeline produces non-trivial delta
# ---------------------------------------------------------------------------


def test_example_traces_distinct_failure_modes():
    """VAL-EX-007: v1 and v2 traces yield a non-trivial introduced+resolved set."""
    from tracecaliper.failure_modes import detect_failure_modes
    from tracecaliper.scoring import score_trace
    suite = load_suite("examples/suites/python-api.yml")
    weights = resolve_weights(suite.weights)
    baseline = load_trace("examples/traces/skill-v1.json")
    candidate = load_trace("examples/traces/skill-v2.json")
    b_score = score_trace(baseline, weights)
    c_score = score_trace(candidate, weights)
    b_modes = detect_failure_modes(baseline)
    c_modes = detect_failure_modes(candidate)
    cmp = compare(b_score, c_score, b_modes, c_modes)
    # introduced and resolved together must have >= 2 codes
    assert len(cmp.introduced) + len(cmp.resolved) >= 2
    # They must not be equal (pure overlap fails this assertion)
    assert set(cmp.introduced) != set(cmp.resolved)


def test_example_traces_non_trivial_delta():
    """VAL-EX-008: Full pipeline over bundled examples produces |delta| >= 1e-6."""
    from tracecaliper.failure_modes import detect_failure_modes
    from tracecaliper.scoring import score_trace
    suite = load_suite("examples/suites/python-api.yml")
    weights = resolve_weights(suite.weights)
    baseline = load_trace("examples/traces/skill-v1.json")
    candidate = load_trace("examples/traces/skill-v2.json")
    b_score = score_trace(baseline, weights)
    c_score = score_trace(candidate, weights)
    b_modes = detect_failure_modes(baseline)
    c_modes = detect_failure_modes(candidate)
    cmp = compare(b_score, c_score, b_modes, c_modes)
    assert abs(cmp.aggregate_delta) >= 1e-6


# ---------------------------------------------------------------------------
# Round-2 scrutiny regression tests — gate rationale completeness
# ---------------------------------------------------------------------------


class TestRound2RegressionGate:
    """Regression tests added in fix-engine-round2 for gate rationale completeness."""

    def test_security_flag_introduced_with_resolved_rationale_mentions_both(self) -> None:
        """NON-BLOCKING fix: SECURITY_FLAG-introduced case with resolved modes must
        mention BOTH the security flag AND the resolved codes in rationale.

        This is the specific test required by the fix-engine-round2 feature.
        """
        cmp = _make_comparison(
            baseline_modes=[_make_failure_mode("OVER_EDITING")],
            candidate_modes=[_make_failure_mode("SECURITY_FLAG", "critical")],
        )
        assert "SECURITY_FLAG" in cmp.introduced
        assert "OVER_EDITING" in cmp.resolved

        decision = decide(cmp)
        full_rationale = " ".join(decision.rationale)
        assert "SECURITY_FLAG" in full_rationale, (
            f"rationale must mention SECURITY_FLAG; got: {full_rationale!r}"
        )
        assert "OVER_EDITING" in full_rationale, (
            f"rationale must mention resolved code OVER_EDITING; got: {full_rationale!r}"
        )

    def test_security_flag_introduced_with_persistent_non_security_codes_mentions_them(
        self,
    ) -> None:
        """NON-BLOCKING fix: SECURITY_FLAG introduced + persistent non-security code
        → rationale must cite the persistent code too.

        Without fix: Rule 1 does not mention 'persistent' codes at all.
        """
        cmp = _make_comparison(
            baseline_modes=[_make_failure_mode("OVER_EDITING")],
            candidate_modes=[
                _make_failure_mode("SECURITY_FLAG", "critical"),
                _make_failure_mode("OVER_EDITING"),
            ],
        )
        assert "SECURITY_FLAG" in cmp.introduced
        assert "OVER_EDITING" in cmp.persistent

        decision = decide(cmp)
        full_rationale = " ".join(decision.rationale)
        assert "SECURITY_FLAG" in full_rationale, (
            f"rationale must mention SECURITY_FLAG; got: {full_rationale!r}"
        )
        assert "OVER_EDITING" in full_rationale, (
            f"rationale must mention persistent code OVER_EDITING; got: {full_rationale!r}"
        )

    def test_persistent_security_flag_with_other_persistent_codes_mentions_all(
        self,
    ) -> None:
        """NON-BLOCKING fix: persistent SECURITY_FLAG + other persistent non-security code
        → rationale must cite both.

        Without fix: Rule 2 does not mention non-SECURITY_FLAG persistent codes.
        """
        cmp = _make_comparison(
            baseline_modes=[
                _make_failure_mode("SECURITY_FLAG", "critical"),
                _make_failure_mode("OVER_EDITING"),
            ],
            candidate_modes=[
                _make_failure_mode("SECURITY_FLAG", "critical"),
                _make_failure_mode("OVER_EDITING"),
            ],
        )
        assert "SECURITY_FLAG" in cmp.persistent
        assert "OVER_EDITING" in cmp.persistent

        decision = decide(cmp)
        full_rationale = " ".join(decision.rationale)
        assert "SECURITY_FLAG" in full_rationale, (
            f"rationale must mention SECURITY_FLAG; got: {full_rationale!r}"
        )
        assert "OVER_EDITING" in full_rationale, (
            f"rationale must mention other persistent code OVER_EDITING; got: {full_rationale!r}"
        )
