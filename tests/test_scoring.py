"""Tests for the TraceCaliper scoring engine.

Covers VAL-SCORE-001 through VAL-SCORE-014 from the validation contract.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from tracecaliper.models import (
    DEFAULT_WEIGHTS,
    DIMENSION_NAMES,
    DimensionScore,
    Trace,
    TraceScore,
    TraceStep,
)
from tracecaliper.scoring import (
    DEFAULT_WEIGHTS as SCORING_DEFAULT_WEIGHTS,
    resolve_weights,
    score_trace,
)


# ---------------------------------------------------------------------------
# Trace construction helpers
# ---------------------------------------------------------------------------


def _make_trace(
    *,
    skill_id: str = "test-skill",
    label: str = "SIMULATED — test trace",
    steps: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Trace:
    """Build a minimal valid Trace for testing."""
    if steps is None:
        steps = [
            {
                "index": 1,
                "action": "implement",
                "files_touched": ["main.py"],
                "evidence": "Implemented the feature.",
            }
        ]
    return Trace(
        skill_id=skill_id,
        simulated=True,
        label=label,
        steps=[TraceStep(**s) for s in steps],
        metadata=metadata,
    )


def _perfect_trace() -> Trace:
    """Trace designed to score 1.0 on every dimension."""
    return _make_trace(
        label="SIMULATED — perfect test trace",
        steps=[
            {
                "index": 1,
                "action": "implement",
                "files_touched": ["feat.py", "router.py"],
                "evidence": "Implemented the required feature within scope.",
            },
            {
                "index": 2,
                "action": "run_tests",
                "files_touched": [],
                "evidence": "All tests pass.",
            },
        ],
        metadata={
            "task": "Add feature",
            "files_in_scope": ["feat.py", "router.py"],
            "task_completed": True,
            "tests": {"after": {"passing": 15, "failing": 0}},
            "review_size_loc": 50,
        },
    )


def _zero_trace() -> Trace:
    """Trace designed to score 0.0 on every dimension."""
    return _make_trace(
        label="SIMULATED — zero-score test trace",
        steps=[
            {
                "index": 1,
                "action": "bad_action",
                "files_touched": [
                    "bad1.py", "bad2.py", "bad3.py", "bad4.py", "bad5.py",
                    "bad6.py", "bad7.py", "bad8.py", "bad9.py", "bad10.py",
                ],
                "evidence": (
                    "Hardcoded credential into source: "
                    "api_key = 'SECRET_TOKEN_PLACEHOLDER_12345'"
                ),
            },
            {
                "index": 2,
                "action": "more_bad",
                "files_touched": [
                    "bad11.py", "bad12.py", "bad13.py", "bad14.py", "bad15.py",
                ],
                "evidence": "Touched more unrelated files.",
            },
        ],
        metadata={
            "task": "Do something specific",
            "files_in_scope": ["expected.py"],
            "task_completed": False,
            "tests": {"after": {"passing": 0, "failing": 5}},
            "review_size_loc": 9999,
        },
    )


def _neutral_trace() -> Trace:
    """A trace with minimal metadata (produces neutral 0.5 scores where applicable)."""
    return _make_trace(
        label="SIMULATED — neutral test trace (no metadata)",
        steps=[
            {
                "index": 1,
                "action": "edit",
                "files_touched": ["a.py"],
                "evidence": "Made a change.",
            }
        ],
        metadata=None,
    )


# ---------------------------------------------------------------------------
# VAL-SCORE-001: resolve_weights(None) returns DEFAULT_WEIGHTS
# ---------------------------------------------------------------------------


def test_resolve_weights_none_returns_defaults() -> None:
    """VAL-SCORE-001: resolve_weights(None) returns the documented defaults."""
    resolved = resolve_weights(None)
    assert resolved == DEFAULT_WEIGHTS


def test_default_weights_values_match_documentation() -> None:
    """VAL-SCORE-001: DEFAULT_WEIGHTS matches the seven documented defaults exactly."""
    expected = {
        "tests_passed": 0.25,
        "task_completion": 0.25,
        "security": 0.20,
        "over_editing": 0.10,
        "repo_conventions": 0.08,
        "instruction_following": 0.07,
        "reviewability": 0.05,
    }
    assert SCORING_DEFAULT_WEIGHTS == expected
    assert sum(SCORING_DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)


def test_score_trace_with_no_overrides_uses_defaults() -> None:
    """VAL-SCORE-001: scoring a trace with default weights gives TraceScore
    whose weights equal the documented defaults."""
    trace = _perfect_trace()
    weights = resolve_weights(None)
    result = score_trace(trace, weights)
    assert result.weights == dict(DEFAULT_WEIGHTS)


# ---------------------------------------------------------------------------
# VAL-SCORE-002: weighted_total = dot product under defaults
# ---------------------------------------------------------------------------


def test_weighted_total_is_dot_product_under_defaults() -> None:
    """VAL-SCORE-002: weighted_total equals hand-computed dot product."""
    trace = _perfect_trace()
    weights = resolve_weights(None)
    result = score_trace(trace, weights)
    expected = sum(
        weights[d.name] * d.score for d in result.dimensions
    )
    assert result.weighted_total == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# VAL-SCORE-003: suite-level overrides take precedence
# ---------------------------------------------------------------------------


def test_suite_weight_override_replaces_default() -> None:
    """VAL-SCORE-003: suite overrides replace individual defaults."""
    overrides = {"tests_passed": 0.5, "security": 0.5}
    # All other dims get 0 in this override (partial — tested separately)
    full_override = {name: 0.0 for name in DIMENSION_NAMES}
    full_override["tests_passed"] = 0.5
    full_override["security"] = 0.5

    weights = resolve_weights(full_override)
    trace = _perfect_trace()
    result = score_trace(trace, weights)

    # weighted_total = dot product with our custom weights
    expected = sum(weights[d.name] * d.score for d in result.dimensions)
    assert result.weighted_total == pytest.approx(expected, abs=1e-9)
    assert result.weights["tests_passed"] == 0.5
    assert result.weights["security"] == 0.5


# ---------------------------------------------------------------------------
# VAL-SCORE-004: partial overrides fall back to defaults for missing keys
# ---------------------------------------------------------------------------


def test_partial_override_falls_back_to_defaults() -> None:
    """VAL-SCORE-004: unspecified dimensions use documented default weights."""
    partial = {"tests_passed": 0.50}
    resolved = resolve_weights(partial)
    # Override takes effect
    assert resolved["tests_passed"] == 0.50
    # Unspecified keys fall back to defaults
    for name in DIMENSION_NAMES:
        if name == "tests_passed":
            continue
        assert resolved[name] == pytest.approx(DEFAULT_WEIGHTS[name])


def test_empty_override_returns_all_defaults() -> None:
    """VAL-SCORE-004: empty override dict returns defaults for all keys."""
    resolved = resolve_weights({})
    assert resolved == DEFAULT_WEIGHTS


# ---------------------------------------------------------------------------
# VAL-SCORE-005: negative weights are rejected
# ---------------------------------------------------------------------------


def test_negative_weight_raises_with_dimension_name() -> None:
    """VAL-SCORE-005: negative weights raise ValueError referencing offending dimension."""
    with pytest.raises(ValueError, match="tests_passed"):
        resolve_weights({"tests_passed": -0.1})


def test_negative_weight_in_other_dimension_raises() -> None:
    """VAL-SCORE-005: negative weight for any dimension is rejected."""
    for name in DIMENSION_NAMES:
        with pytest.raises(ValueError, match=name):
            resolve_weights({name: -1.0})


# ---------------------------------------------------------------------------
# VAL-SCORE-006: non-numeric weights are rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", ["abc", None, [], {}, (1, 2)])
def test_non_numeric_weight_raises(bad_value: object) -> None:
    """VAL-SCORE-006: non-numeric weights cause a ValueError."""
    with pytest.raises((ValueError, TypeError)):
        resolve_weights({"tests_passed": bad_value})  # type: ignore[dict-item]


# ---------------------------------------------------------------------------
# VAL-SCORE-007: zero weights are accepted; dimension still present
# ---------------------------------------------------------------------------


def test_zero_weight_accepted_dimension_present() -> None:
    """VAL-SCORE-007: zero-weighted dimensions appear in dimensions list but
    contribute zero to weighted_total."""
    weights = dict(DEFAULT_WEIGHTS)
    weights["tests_passed"] = 0.0
    trace = _perfect_trace()
    result = score_trace(trace, weights)

    # Dimension is still present
    names = [d.name for d in result.dimensions]
    assert "tests_passed" in names

    # tests_passed contributes 0 to weighted_total
    tp_score = next(d.score for d in result.dimensions if d.name == "tests_passed")
    manual_total = sum(weights[d.name] * d.score for d in result.dimensions)
    assert result.weighted_total == pytest.approx(manual_total, abs=1e-9)
    # If tp_score != 0, the contribution from tests_passed should be absent
    assert result.weighted_total == pytest.approx(
        sum(weights[d.name] * d.score for d in result.dimensions if d.name != "tests_passed"),
        abs=1e-9,
    )


# ---------------------------------------------------------------------------
# VAL-SCORE-008: all-zero weights → weighted_total == 0.0 exactly
# ---------------------------------------------------------------------------


def test_all_zero_weights_total_zero() -> None:
    """VAL-SCORE-008: all zero weights yield weighted_total == 0.0 exactly."""
    weights = {name: 0.0 for name in DIMENSION_NAMES}
    trace = _perfect_trace()
    result = score_trace(trace, weights)
    assert result.weighted_total == 0.0


# ---------------------------------------------------------------------------
# VAL-SCORE-009: TraceScore always has exactly 7 dimensions
# ---------------------------------------------------------------------------


def test_trace_score_has_seven_dimensions() -> None:
    """VAL-SCORE-009: TraceScore.dimensions contains exactly 7 documented names."""
    trace = _perfect_trace()
    result = score_trace(trace, resolve_weights(None))
    names = [d.name for d in result.dimensions]
    assert set(names) == set(DIMENSION_NAMES)
    assert len(names) == len(DIMENSION_NAMES)


def test_trace_score_dimensions_sorted() -> None:
    """VAL-SCORE-009: dimensions are sorted alphabetically by name."""
    trace = _perfect_trace()
    result = score_trace(trace, resolve_weights(None))
    names = [d.name for d in result.dimensions]
    assert names == sorted(names)


def test_trace_score_has_trace_id_and_weighted_total() -> None:
    """VAL-SCORE-009: TraceScore exposes trace_id, dimensions, weights, weighted_total."""
    trace = _perfect_trace()
    result = score_trace(trace, resolve_weights(None))
    assert isinstance(result.trace_id, str) and result.trace_id
    assert isinstance(result.weighted_total, float)
    assert isinstance(result.weights, dict)


# ---------------------------------------------------------------------------
# VAL-SCORE-010: DimensionScore.score is always in [0.0, 1.0]
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "trace_fn",
    [_perfect_trace, _zero_trace, _neutral_trace],
    ids=["perfect", "zero", "neutral"],
)
def test_dimension_scores_bounded(trace_fn) -> None:
    """VAL-SCORE-010: every DimensionScore.score is in [0.0, 1.0]."""
    trace = trace_fn()
    result = score_trace(trace, resolve_weights(None))
    for d in result.dimensions:
        assert 0.0 <= d.score <= 1.0, (
            f"Dimension {d.name!r} score {d.score} out of [0, 1]"
        )


# ---------------------------------------------------------------------------
# VAL-SCORE-011: all-zero dimension scores → weighted_total == 0.0
# ---------------------------------------------------------------------------


def test_all_dimension_scores_zero_weighted_total_zero() -> None:
    """VAL-SCORE-011: the zero-score trace produces weighted_total == 0.0."""
    trace = _zero_trace()
    result = score_trace(trace, resolve_weights(None))
    for d in result.dimensions:
        assert d.score == 0.0, f"Expected 0.0 for {d.name!r}, got {d.score}"
    assert result.weighted_total == 0.0


# ---------------------------------------------------------------------------
# VAL-SCORE-012: all-one dimension scores → weighted_total == sum(weights)
# ---------------------------------------------------------------------------


def test_all_dimension_scores_one_weighted_total_equals_weight_sum() -> None:
    """VAL-SCORE-012: perfect trace with default weights → weighted_total == 1.0."""
    trace = _perfect_trace()
    weights = resolve_weights(None)
    result = score_trace(trace, weights)
    for d in result.dimensions:
        assert d.score == 1.0, f"Expected 1.0 for {d.name!r}, got {d.score}"
    expected_total = sum(weights.values())
    assert result.weighted_total == pytest.approx(expected_total, abs=1e-9)
    assert result.weighted_total == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# VAL-SCORE-013: weights NOT auto-normalized
# ---------------------------------------------------------------------------


def test_weights_not_normalized() -> None:
    """VAL-SCORE-013: weights summing to 2.0 are NOT normalized; weighted_total
    reflects them verbatim."""
    doubled = {name: w * 2 for name, w in DEFAULT_WEIGHTS.items()}
    assert sum(doubled.values()) == pytest.approx(2.0)

    trace = _perfect_trace()
    result_default = score_trace(trace, resolve_weights(None))
    result_doubled = score_trace(trace, doubled)

    # With doubled weights and the same trace, the total should also double
    assert result_doubled.weighted_total == pytest.approx(
        result_default.weighted_total * 2, abs=1e-9
    )
    # Resolved weights preserve the un-normalized values
    assert result_doubled.weights["tests_passed"] == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# VAL-SCORE-014: TraceScore round-trip through JSON without loss
# ---------------------------------------------------------------------------


def test_trace_score_json_round_trip() -> None:
    """VAL-SCORE-014: TraceScore serializes and deserializes losslessly."""
    trace = _perfect_trace()
    result = score_trace(trace, resolve_weights(None))
    serialized = result.model_dump_json()
    reloaded = TraceScore.model_validate_json(serialized)

    assert reloaded.model_dump() == result.model_dump()
    assert reloaded.weighted_total == result.weighted_total  # bit-exact


def test_trace_score_json_has_all_seven_dimension_keys() -> None:
    """VAL-SCORE-014: JSON output contains all seven dimension names."""
    trace = _perfect_trace()
    result = score_trace(trace, resolve_weights(None))
    payload = json.loads(result.model_dump_json())
    names_in_json = [d["name"] for d in payload["dimensions"]]
    assert set(names_in_json) == set(DIMENSION_NAMES)
    assert "weighted_total" in payload


def test_score_trace_deterministic() -> None:
    """VAL-SCORE-014 (byte-determinism): two invocations on the same trace
    yield model_dump_json identical bytes."""
    trace = _perfect_trace()
    weights = resolve_weights(None)
    r1 = score_trace(trace, weights)
    r2 = score_trace(trace, weights)
    assert r1.model_dump_json() == r2.model_dump_json()


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------


def test_score_trace_does_not_mutate_input() -> None:
    """Scorers are pure: input trace is unchanged after scoring."""
    trace = _perfect_trace()
    original_dump = trace.model_dump()
    score_trace(trace, resolve_weights(None))
    assert trace.model_dump() == original_dump


def test_score_trace_with_example_traces() -> None:
    """Scoring the two bundled example traces yields TraceScore objects that
    satisfy basic shape invariants."""
    import json as _json
    from pathlib import Path

    for fname in ("skill-v1.json", "skill-v2.json"):
        path = Path(__file__).parent.parent / "examples" / "traces" / fname
        trace = Trace.model_validate_json(path.read_text())
        result = score_trace(trace, resolve_weights(None))
        assert len(result.dimensions) == 7
        assert set(d.name for d in result.dimensions) == set(DIMENSION_NAMES)
        for d in result.dimensions:
            assert 0.0 <= d.score <= 1.0


def test_scoring_module_importable() -> None:
    """DEFAULT_WEIGHTS, resolve_weights, and score_trace are importable from
    tracecaliper.scoring."""
    from tracecaliper.scoring import (  # noqa: F401
        DEFAULT_WEIGHTS,
        resolve_weights,
        score_trace,
    )


# ---------------------------------------------------------------------------
# Robustness regression tests — scorers must never raise on valid Traces
# ---------------------------------------------------------------------------


from tracecaliper.scoring import (
    score_instruction_following,
    score_over_editing,
    score_repo_conventions,
    score_reviewability,
    score_tests_passed,
)


class TestScorerRobustness:
    """Regression tests: scorers degrade gracefully on unusual-but-schema-valid metadata."""

    # --- files_in_scope edge cases ---

    def test_files_in_scope_as_int_no_raise(self) -> None:
        """files_in_scope=int does not raise; over_editing degrades to neutral."""
        trace = _make_trace(metadata={"files_in_scope": 5})
        result = score_over_editing(trace)
        assert 0.0 <= result.score <= 1.0

    def test_files_in_scope_as_dict_no_raise(self) -> None:
        """files_in_scope=dict (non-list) does not raise; over_editing degrades gracefully."""
        trace = _make_trace(metadata={"files_in_scope": {"foo": "bar"}})
        result = score_over_editing(trace)
        assert 0.0 <= result.score <= 1.0

    def test_files_in_scope_as_int_repo_conventions_no_raise(self) -> None:
        """files_in_scope=int does not raise in repo_conventions scorer."""
        trace = _make_trace(metadata={"files_in_scope": 42})
        result = score_repo_conventions(trace)
        assert 0.0 <= result.score <= 1.0

    def test_files_in_scope_as_dict_repo_conventions_no_raise(self) -> None:
        """files_in_scope=dict does not raise in repo_conventions scorer."""
        trace = _make_trace(metadata={"files_in_scope": {"a": 1}})
        result = score_repo_conventions(trace)
        assert 0.0 <= result.score <= 1.0

    def test_files_in_scope_as_int_instruction_following_no_raise(self) -> None:
        """files_in_scope=int does not raise in instruction_following scorer."""
        trace = _make_trace(metadata={"files_in_scope": 3})
        result = score_instruction_following(trace)
        assert 0.0 <= result.score <= 1.0

    def test_files_in_scope_as_dict_instruction_following_no_raise(self) -> None:
        """files_in_scope=dict does not raise in instruction_following scorer."""
        trace = _make_trace(metadata={"files_in_scope": {"k": "v"}})
        result = score_instruction_following(trace)
        assert 0.0 <= result.score <= 1.0

    # --- tests_before / tests_after edge cases ---

    def test_tests_after_passing_as_string_no_raise(self) -> None:
        """tests.after.passing/failing as strings => neutral score, no exception."""
        trace = _make_trace(
            metadata={"tests": {"after": {"passing": "15", "failing": "2"}}}
        )
        result = score_tests_passed(trace)
        assert result.score == pytest.approx(0.5)

    def test_tests_after_passing_as_none_no_raise(self) -> None:
        """tests.after.passing/failing as None => neutral score, no exception."""
        trace = _make_trace(
            metadata={"tests": {"after": {"passing": None, "failing": None}}}
        )
        result = score_tests_passed(trace)
        assert result.score == pytest.approx(0.5)

    def test_tests_after_as_string_no_raise(self) -> None:
        """tests.after as a string instead of dict => neutral score, no exception."""
        trace = _make_trace(metadata={"tests": {"after": "15 passed, 0 failed"}})
        result = score_tests_passed(trace)
        assert result.score == pytest.approx(0.5)

    def test_tests_after_as_none_no_raise(self) -> None:
        """tests.after as None => neutral score, no exception."""
        trace = _make_trace(metadata={"tests": {"after": None}})
        result = score_tests_passed(trace)
        assert result.score == pytest.approx(0.5)

    # --- review_size_loc edge cases ---

    def test_review_size_loc_as_nonnumeric_string_no_raise(self) -> None:
        """review_size_loc as non-numeric string => neutral score, no exception."""
        trace = _make_trace(metadata={"review_size_loc": "large"})
        result = score_reviewability(trace)
        assert result.score == pytest.approx(0.5)

    def test_review_size_loc_as_numeric_string_no_raise(self) -> None:
        """review_size_loc as numeric string e.g. '200' => valid score, no exception."""
        trace = _make_trace(metadata={"review_size_loc": "200"})
        result = score_reviewability(trace)
        assert 0.0 <= result.score <= 1.0

    def test_review_size_loc_as_negative_no_raise(self) -> None:
        """review_size_loc as negative number => clamped, no exception, score in [0,1]."""
        trace = _make_trace(metadata={"review_size_loc": -100})
        result = score_reviewability(trace)
        assert 0.0 <= result.score <= 1.0

    # --- missing optional metadata entirely ---

    def test_score_trace_missing_metadata_entirely_no_raise(self) -> None:
        """Trace with metadata=None does not raise on full score_trace call."""
        trace = _make_trace(metadata=None)
        result = score_trace(trace, resolve_weights(None))
        assert 0.0 <= result.weighted_total <= sum(resolve_weights(None).values())
        assert len(result.dimensions) == 7

    def test_score_trace_empty_metadata_no_raise(self) -> None:
        """Trace with metadata={} does not raise on full score_trace call."""
        trace = _make_trace(metadata={})
        result = score_trace(trace, resolve_weights(None))
        assert 0.0 <= result.weighted_total <= sum(resolve_weights(None).values())

    def test_score_trace_files_in_scope_int_no_raise(self) -> None:
        """Full score_trace call with files_in_scope=int does not raise."""
        trace = _make_trace(metadata={"files_in_scope": 7})
        result = score_trace(trace, resolve_weights(None))
        assert 0.0 <= result.weighted_total <= sum(resolve_weights(None).values())

    def test_score_trace_review_size_loc_string_no_raise(self) -> None:
        """Full score_trace call with review_size_loc as string does not raise."""
        trace = _make_trace(metadata={"review_size_loc": "huge"})
        result = score_trace(trace, resolve_weights(None))
        assert 0.0 <= result.weighted_total <= sum(resolve_weights(None).values())


# ---------------------------------------------------------------------------
# VAL-SCORE-006 extension: bool weights must be rejected like non-numeric strings
# ---------------------------------------------------------------------------


def test_resolve_weights_true_raises() -> None:
    """resolve_weights must reject True (bool) the same as a non-numeric string."""
    with pytest.raises((ValueError, TypeError)):
        resolve_weights({"tests_passed": True})


def test_resolve_weights_false_raises() -> None:
    """resolve_weights must reject False (bool) the same as a non-numeric string."""
    with pytest.raises((ValueError, TypeError)):
        resolve_weights({"tests_passed": False})


# ---------------------------------------------------------------------------
# Round-2 scrutiny regression tests
# ---------------------------------------------------------------------------


class TestRound2RegressionScoring:
    """Regression tests added in fix-engine-round2 for blocking issues."""

    # --- Issue 1: files_in_scope with unhashable elements ---

    def test_score_trace_files_in_scope_containing_dicts_no_raise(self) -> None:
        """BLOCKING fix: files_in_scope with dict elements must NOT raise TypeError.

        score_repo_conventions and score_instruction_following previously
        called set(_raw_scope) which raises TypeError on dict values.
        """
        trace = _make_trace(
            metadata={"files_in_scope": [{"path": "src/foo.py"}, {"path": "src/bar.py"}]}
        )
        # Must not raise
        result = score_trace(trace, resolve_weights(None))
        assert len(result.dimensions) == 7
        for d in result.dimensions:
            assert 0.0 <= d.score <= 1.0, (
                f"Dimension {d.name!r} score {d.score} out of [0, 1]"
            )

    def test_score_trace_files_in_scope_containing_lists_no_raise(self) -> None:
        """BLOCKING fix: files_in_scope with list elements must NOT raise TypeError.

        A list-of-lists (unhashable) previously caused set() to raise.
        """
        trace = _make_trace(
            metadata={"files_in_scope": [["src/foo.py", "src/bar.py"], ["tests/test_x.py"]]}
        )
        # Must not raise
        result = score_trace(trace, resolve_weights(None))
        assert len(result.dimensions) == 7
        for d in result.dimensions:
            assert 0.0 <= d.score <= 1.0, (
                f"Dimension {d.name!r} score {d.score} out of [0, 1]"
            )

    def test_score_repo_conventions_files_in_scope_dicts_no_raise(self) -> None:
        """BLOCKING fix: score_repo_conventions must not raise on dict elements."""
        from tracecaliper.scoring import score_repo_conventions
        trace = _make_trace(
            metadata={"files_in_scope": [{"file": "x.py"}, {"file": "y.py"}]}
        )
        result = score_repo_conventions(trace)
        assert 0.0 <= result.score <= 1.0

    def test_score_instruction_following_files_in_scope_dicts_no_raise(self) -> None:
        """BLOCKING fix: score_instruction_following must not raise on dict elements."""
        result = score_instruction_following(
            _make_trace(metadata={"files_in_scope": [{"f": "a.py"}]})
        )
        assert 0.0 <= result.score <= 1.0

    def test_score_repo_conventions_files_in_scope_lists_no_raise(self) -> None:
        """BLOCKING fix: score_repo_conventions must not raise on list-of-lists."""
        from tracecaliper.scoring import score_repo_conventions
        trace = _make_trace(
            metadata={"files_in_scope": [["foo.py"], ["bar.py"]]}
        )
        result = score_repo_conventions(trace)
        assert 0.0 <= result.score <= 1.0

    def test_score_instruction_following_files_in_scope_lists_no_raise(self) -> None:
        """BLOCKING fix: score_instruction_following must not raise on list-of-lists."""
        result = score_instruction_following(
            _make_trace(metadata={"files_in_scope": [["foo.py"], ["bar.py"]]})
        )
        assert 0.0 <= result.score <= 1.0

    # --- Issue 2: negative numeric test counts in score_tests_passed ---

    def test_score_tests_passed_negative_counts_valid_score(self) -> None:
        """BLOCKING fix: passing=-5, failing=-3 must yield a valid DimensionScore
        with score in [0, 1] (as specified in the fix-engine-round2 feature)."""
        trace = _make_trace(
            metadata={"tests": {"after": {"passing": -5, "failing": -3}}}
        )
        result = score_tests_passed(trace)
        assert 0.0 <= result.score <= 1.0, (
            f"score {result.score!r} out of [0, 1] for negative passing/failing counts"
        )

    def test_score_tests_passed_mixed_sign_positive_passing_negative_failing_valid_score(
        self,
    ) -> None:
        """BLOCKING fix: passing=5, failing=-10 must not raise pydantic.ValidationError.

        Without the fix: score = 5 / (5 + -10) = 5 / -5 = -1.0 → raises ValidationError.
        """
        trace = _make_trace(
            metadata={"tests": {"after": {"passing": 5, "failing": -10}}}
        )
        result = score_tests_passed(trace)
        assert 0.0 <= result.score <= 1.0, (
            f"score {result.score!r} out of [0, 1] for passing=5, failing=-10"
        )

    def test_score_tests_passed_mixed_sign_negative_passing_positive_failing_valid_score(
        self,
    ) -> None:
        """BLOCKING fix: passing=-5, failing=3 must not raise pydantic.ValidationError.

        Without the fix: score = -5 / (-5 + 3) = -5 / -2 = 2.5 → raises ValidationError.
        """
        trace = _make_trace(
            metadata={"tests": {"after": {"passing": -5, "failing": 3}}}
        )
        result = score_tests_passed(trace)
        assert 0.0 <= result.score <= 1.0, (
            f"score {result.score!r} out of [0, 1] for passing=-5, failing=3"
        )
