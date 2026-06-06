"""Tests for the TraceCaliper Pydantic v2 data models.

These tests exercise the assertions in the Data Models area of the
validation contract (``VAL-MODEL-001`` through ``VAL-MODEL-009``).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from tracecaliper.models import (
    Comparison,
    DEFAULT_WEIGHTS,
    DIMENSION_NAMES,
    DimensionScore,
    FAILURE_MODE_CODES,
    FailureMode,
    GateDecision,
    Skill,
    Suite,
    Trace,
    TraceScore,
    TraceStep,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_suite_payload(weights: dict[str, float] | None = None) -> dict[str, Any]:
    return {
        "name": "python-api",
        "description": "Python API skill suite",
        "weights": dict(DEFAULT_WEIGHTS) if weights is None else weights,
        "skills": [
            {
                "id": "skill-v1",
                "path": "examples/skills/skill-v1.md",
                "description": "Skill v1",
            }
        ],
    }


def _valid_trace_payload() -> dict[str, Any]:
    return {
        "skill_id": "skill-v1",
        "simulated": True,
        "label": "SIMULATED — MVP example",
        "steps": [
            {
                "index": 0,
                "action": "read README",
                "files_touched": ["README.md"],
                "evidence": "Looked at README header.",
            },
            {
                "index": 1,
                "action": "edit module",
                "files_touched": ["src/x.py"],
                "evidence": "Replaced function body.",
            },
        ],
    }


def _valid_dimensions() -> list[DimensionScore]:
    return sorted(
        [
            DimensionScore(name=name, score=0.5, rationale=f"{name} rationale")
            for name in DIMENSION_NAMES
        ],
        key=lambda d: d.name,
    )


def _valid_trace_score(trace_id: str = "skill-v1") -> TraceScore:
    return TraceScore(
        trace_id=trace_id,
        dimensions=_valid_dimensions(),
        weights=dict(DEFAULT_WEIGHTS),
        weighted_total=0.5,
    )


# ---------------------------------------------------------------------------
# VAL-MODEL-001: importability
# ---------------------------------------------------------------------------


def test_all_models_importable() -> None:
    """VAL-MODEL-001: every model imports from ``tracecaliper.models``."""

    from tracecaliper.models import (  # noqa: F401
        Comparison,
        DimensionScore,
        FailureMode,
        GateDecision,
        Skill,
        Suite,
        Trace,
        TraceScore,
        TraceStep,
    )


# ---------------------------------------------------------------------------
# VAL-MODEL-002: Suite weight validation
# ---------------------------------------------------------------------------


def test_suite_rejects_negative_weight() -> None:
    payload = _valid_suite_payload(
        weights={**DEFAULT_WEIGHTS, "tests_passed": -0.1},
    )
    with pytest.raises(ValidationError) as exc_info:
        Suite.model_validate(payload)
    assert "tests_passed" in str(exc_info.value)


def test_suite_rejects_unknown_dimension_key() -> None:
    payload = _valid_suite_payload(
        weights={**DEFAULT_WEIGHTS, "not_a_dimension": 0.1},
    )
    with pytest.raises(ValidationError) as exc_info:
        Suite.model_validate(payload)
    assert "not_a_dimension" in str(exc_info.value)


def test_suite_accepts_partial_weights() -> None:
    """The raw Suite model only stores what the YAML provides."""

    payload = _valid_suite_payload(weights={"tests_passed": 0.5})
    suite = Suite.model_validate(payload)
    assert suite.weights == {"tests_passed": 0.5}


def test_suite_accepts_empty_weights() -> None:
    payload = _valid_suite_payload(weights={})
    suite = Suite.model_validate(payload)
    assert suite.weights == {}


# ---------------------------------------------------------------------------
# VAL-MODEL-003: round-trip
# ---------------------------------------------------------------------------


def test_suite_round_trip_via_model_dump_validate() -> None:
    good = Suite.model_validate(_valid_suite_payload())
    again = Suite.model_validate(good.model_dump())
    assert again.model_dump() == good.model_dump()


# ---------------------------------------------------------------------------
# VAL-MODEL-004: Trace required fields and step-index invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["skill_id", "steps", "simulated"])
def test_trace_rejects_missing_required_field(missing: str) -> None:
    payload = _valid_trace_payload()
    payload.pop(missing)
    with pytest.raises(ValidationError) as exc_info:
        Trace.model_validate(payload)
    assert missing in str(exc_info.value)


def test_trace_rejects_duplicate_step_indices() -> None:
    payload = _valid_trace_payload()
    payload["steps"][1]["index"] = 0
    with pytest.raises(ValidationError) as exc_info:
        Trace.model_validate(payload)
    msg = str(exc_info.value).lower()
    assert "duplicate" in msg or "index" in msg


def test_trace_rejects_non_monotonic_step_indices() -> None:
    payload = _valid_trace_payload()
    payload["steps"][0]["index"] = 5
    payload["steps"][1]["index"] = 4
    with pytest.raises(ValidationError) as exc_info:
        Trace.model_validate(payload)
    assert "increasing" in str(exc_info.value) or "index" in str(exc_info.value)


def test_trace_accepts_well_formed_payload() -> None:
    trace = Trace.model_validate(_valid_trace_payload())
    assert [s.index for s in trace.steps] == [0, 1]


# ---------------------------------------------------------------------------
# VAL-MODEL-005: DimensionScore bounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [-0.1, 1.5, 2.0, -1.0])
def test_dimension_score_rejects_out_of_range(bad: float) -> None:
    with pytest.raises(ValidationError):
        DimensionScore(name="tests_passed", score=bad, rationale="x")


@pytest.mark.parametrize("ok", [0.0, 1.0])
def test_dimension_score_accepts_boundary(ok: float) -> None:
    d = DimensionScore(name="tests_passed", score=ok, rationale="x")
    assert d.score == ok


def test_dimension_score_rejects_unknown_name() -> None:
    with pytest.raises(ValidationError):
        DimensionScore(name="not_a_dimension", score=0.5, rationale="x")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# VAL-MODEL-006: TraceScore stability across serialization
# ---------------------------------------------------------------------------


def test_trace_score_round_trip_byte_identical_dump() -> None:
    score = _valid_trace_score()
    rehydrated = TraceScore.model_validate_json(score.model_dump_json())
    assert rehydrated.model_dump() == score.model_dump()
    assert rehydrated.weighted_total == score.weighted_total


def test_trace_score_rejects_missing_dimension() -> None:
    incomplete = [
        DimensionScore(name=name, score=0.5, rationale="r")
        for name in DIMENSION_NAMES[:-1]
    ]
    with pytest.raises(ValidationError):
        TraceScore(
            trace_id="t",
            dimensions=incomplete,
            weights=dict(DEFAULT_WEIGHTS),
            weighted_total=0.0,
        )


def test_trace_score_rejects_unsorted_dimensions() -> None:
    dims = sorted(
        [
            DimensionScore(name=name, score=0.5, rationale="r")
            for name in DIMENSION_NAMES
        ],
        key=lambda d: d.name,
        reverse=True,
    )
    with pytest.raises(ValidationError):
        TraceScore(
            trace_id="t",
            dimensions=dims,
            weights=dict(DEFAULT_WEIGHTS),
            weighted_total=0.0,
        )


# ---------------------------------------------------------------------------
# VAL-MODEL-007: FailureMode taxonomy and severity
# ---------------------------------------------------------------------------


def test_failure_mode_rejects_unknown_code() -> None:
    with pytest.raises(ValidationError):
        FailureMode(code="NOT_A_CODE", severity="low", evidence="x")  # type: ignore[arg-type]


def test_failure_mode_rejects_unknown_severity() -> None:
    with pytest.raises(ValidationError):
        FailureMode(code="OVER_EDITING", severity="catastrophic", evidence="x")  # type: ignore[arg-type]


def test_failure_mode_rejects_empty_evidence() -> None:
    with pytest.raises(ValidationError):
        FailureMode(code="OVER_EDITING", severity="low", evidence="")


def test_failure_mode_rejects_whitespace_evidence() -> None:
    with pytest.raises(ValidationError):
        FailureMode(code="OVER_EDITING", severity="low", evidence="   \n\t")


@pytest.mark.parametrize("code", list(FAILURE_MODE_CODES))
@pytest.mark.parametrize("severity", ["low", "medium", "high", "critical"])
def test_failure_mode_accepts_documented_code_severity(code: str, severity: str) -> None:
    fm = FailureMode(code=code, severity=severity, evidence="ok")  # type: ignore[arg-type]
    assert fm.code == code
    assert fm.severity == severity


# ---------------------------------------------------------------------------
# VAL-MODEL-008: GateDecision constraints
# ---------------------------------------------------------------------------


def test_gate_decision_rejects_unknown_outcome() -> None:
    with pytest.raises(ValidationError):
        GateDecision(decision="MAYBE", rationale=["x"])  # type: ignore[arg-type]


def test_gate_decision_rejects_empty_rationale_list() -> None:
    with pytest.raises(ValidationError):
        GateDecision(decision="HOLD", rationale=[])


@pytest.mark.parametrize("bad", ["", "   ", "\t", "\n", "  \n  "])
def test_gate_decision_rejects_blank_rationale_entry(bad: str) -> None:
    with pytest.raises(ValidationError):
        GateDecision(decision="HOLD", rationale=[bad])


@pytest.mark.parametrize("decision", ["PASS", "HOLD", "INVESTIGATE"])
def test_gate_decision_accepts_documented_outcome(decision: str) -> None:
    g = GateDecision(decision=decision, rationale=["because"])  # type: ignore[arg-type]
    assert g.decision == decision


# ---------------------------------------------------------------------------
# VAL-MODEL-009: top-level JSON round-trip and deterministic Comparison dump
# ---------------------------------------------------------------------------


def _build_comparison() -> Comparison:
    baseline = _valid_trace_score(trace_id="baseline")
    candidate = _valid_trace_score(trace_id="candidate")
    deltas = {name: 0.0 for name in DIMENSION_NAMES}
    return Comparison(
        baseline=baseline,
        candidate=candidate,
        dimension_deltas=deltas,
        aggregate_delta=0.0,
        introduced=["TEST_REGRESSION", "OVER_EDITING"],
        resolved=["INCOMPLETE_TASK"],
        persistent=["SECURITY_FLAG"],
    )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Suite.model_validate(_valid_suite_payload()),
        lambda: Trace.model_validate(_valid_trace_payload()),
        lambda: _valid_trace_score(),
        lambda: _build_comparison(),
        lambda: GateDecision(decision="PASS", rationale=["one", "two"]),
    ],
)
def test_top_level_models_json_round_trip(factory) -> None:
    instance = factory()
    cls = type(instance)
    rehydrated = cls.model_validate_json(instance.model_dump_json())
    assert rehydrated.model_dump() == instance.model_dump()


def test_value_equal_comparisons_byte_identical_indented_json() -> None:
    c1 = _build_comparison()
    c2 = _build_comparison()
    assert c1.model_dump_json(indent=2) == c2.model_dump_json(indent=2)


def test_comparison_sorts_introduced_resolved_persistent() -> None:
    c = Comparison(
        baseline=_valid_trace_score(trace_id="b"),
        candidate=_valid_trace_score(trace_id="c"),
        dimension_deltas={name: 0.0 for name in DIMENSION_NAMES},
        aggregate_delta=0.0,
        introduced=["TEST_REGRESSION", "OVER_EDITING"],
        resolved=["LOW_REVIEWABILITY", "INCOMPLETE_TASK"],
        persistent=["SECURITY_FLAG", "CONVENTION_VIOLATION"],
    )
    assert c.introduced == ["OVER_EDITING", "TEST_REGRESSION"]
    assert c.resolved == ["INCOMPLETE_TASK", "LOW_REVIEWABILITY"]
    assert c.persistent == ["CONVENTION_VIOLATION", "SECURITY_FLAG"]


def test_comparison_rejects_unknown_failure_mode_code() -> None:
    with pytest.raises(ValidationError):
        Comparison(
            baseline=_valid_trace_score(trace_id="b"),
            candidate=_valid_trace_score(trace_id="c"),
            dimension_deltas={name: 0.0 for name in DIMENSION_NAMES},
            aggregate_delta=0.0,
            introduced=["NOT_A_CODE"],
            resolved=[],
            persistent=[],
        )


def test_comparison_json_keys_are_canonically_ordered() -> None:
    c = _build_comparison()
    payload = json.loads(c.model_dump_json())
    assert list(payload["dimension_deltas"].keys()) == sorted(DIMENSION_NAMES)


# ---------------------------------------------------------------------------
# Misc invariants documented in the feature description
# ---------------------------------------------------------------------------


def test_trace_label_must_mention_simulated() -> None:
    payload = _valid_trace_payload()
    payload["label"] = "real trace, no caveat"
    with pytest.raises(ValidationError) as exc_info:
        Trace.model_validate(payload)
    assert "simulated" in str(exc_info.value).lower()


def test_trace_accepts_optional_metadata() -> None:
    payload = _valid_trace_payload()
    payload["metadata"] = {"source": "mvp-example"}
    trace = Trace.model_validate(payload)
    assert trace.metadata == {"source": "mvp-example"}


def test_skill_round_trip() -> None:
    skill = Skill(id="x", path="p", description="d")
    again = Skill.model_validate_json(skill.model_dump_json())
    assert again.model_dump() == skill.model_dump()


def test_tracestep_requires_index_action_evidence() -> None:
    with pytest.raises(ValidationError):
        TraceStep.model_validate({"index": 0, "action": "a"})
    with pytest.raises(ValidationError):
        TraceStep.model_validate({"action": "a", "evidence": "e"})
    step = TraceStep(index=0, action="a", evidence="ev")
    assert step.files_touched == []
