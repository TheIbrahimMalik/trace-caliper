"""Tests for failure-mode detectors (VAL-FAIL-001 through VAL-FAIL-012).

Covers every assertion in the Failure-Mode Detection area of the
validation contract.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from tracecaliper.models import FAILURE_MODE_CODES, FailureMode, Trace, TraceStep


REPO_ROOT = Path(__file__).resolve().parents[1]
TRACE_V1_PATH = REPO_ROOT / "examples" / "traces" / "skill-v1.json"
TRACE_V2_PATH = REPO_ROOT / "examples" / "traces" / "skill-v2.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step(
    index: int,
    action: str,
    files_touched: list[str] | None = None,
    evidence: str = "no signals",
) -> TraceStep:
    return TraceStep(
        index=index,
        action=action,
        files_touched=files_touched or [],
        evidence=evidence,
    )


def _make_trace(**kwargs) -> Trace:
    """Build a minimal Trace with sensible defaults."""
    defaults: dict = {
        "skill_id": "test-skill",
        "simulated": True,
        "label": "SIMULATED — test trace",
        "steps": [],
        "metadata": None,
    }
    defaults.update(kwargs)
    return Trace.model_validate(defaults)


# ---------------------------------------------------------------------------
# Fixtures — example traces
# ---------------------------------------------------------------------------


@pytest.fixture
def trace_v1() -> Trace:
    return Trace.model_validate_json(TRACE_V1_PATH.read_text())


@pytest.fixture
def trace_v2() -> Trace:
    return Trace.model_validate_json(TRACE_V2_PATH.read_text())


# ---------------------------------------------------------------------------
# Fixtures — synthetic traces
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_trace() -> Trace:
    """A trace that fires no failure-mode detectors."""
    return _make_trace(
        steps=[
            _make_step(1, "read_task", ["docs/spec.md"], "Parsed task requirements."),
            _make_step(2, "edit_handler", ["app/handler.py"], "Implemented the handler per spec."),
            _make_step(3, "run_tests", [], "Ran pytest -q; all tests pass."),
        ],
        metadata={
            "task_completed": True,
            "files_in_scope": ["app/handler.py"],
            "tests": {
                "before": {"passing": 10, "failing": 0},
                "after": {"passing": 10, "failing": 0},
            },
            "review_size_loc": 30,
        },
    )


@pytest.fixture
def over_editing_trace() -> Trace:
    """A trace touching 11 unique files, exceeding the OVER_EDITING threshold (> 8)."""
    many_files = [
        "app/main.py",
        "app/utils.py",
        "app/helpers.py",
        "app/extra1.py",
        "app/extra2.py",
        "app/extra3.py",
        "app/extra4.py",
        "app/extra5.py",
        "app/extra6.py",
        "app/extra7.py",
        "app/extra8.py",
    ]
    return _make_trace(
        steps=[
            _make_step(1, "read_task", ["docs/spec.md"], "Parsed task."),
            _make_step(2, "edit_many", many_files, "Edited many files."),
        ],
        metadata={
            "task_completed": True,
            "files_in_scope": ["app/main.py"],
            "review_size_loc": 50,
        },
    )


@pytest.fixture
def test_regression_trace_evidence() -> Trace:
    """A trace whose step evidence contains a pytest_failed signal."""
    return _make_trace(
        steps=[
            _make_step(1, "edit_code", ["app/main.py"], "Edited code."),
            _make_step(
                2,
                "run_tests",
                [],
                "pytest_failed: tests/test_items.py::test_get_item FAILED",
            ),
        ],
        metadata={"task_completed": True, "review_size_loc": 50},
    )


@pytest.fixture
def test_regression_trace_metadata() -> Trace:
    """A trace whose metadata shows the failing-test count increased."""
    return _make_trace(
        steps=[
            _make_step(1, "edit_code", ["app/main.py"], "Edited code."),
        ],
        metadata={
            "task_completed": True,
            "tests": {
                "before": {"passing": 10, "failing": 2},
                "after": {"passing": 9, "failing": 3},
            },
            "review_size_loc": 50,
        },
    )


@pytest.fixture
def security_trace() -> Trace:
    """A trace with a hardcoded-credential signal."""
    return _make_trace(
        steps=[
            _make_step(1, "read_task", [], "Parsed task."),
            _make_step(
                2,
                "edit_config",
                ["app/config.py"],
                'Hardcoded api_key = "SECRET123" in config instead of env-var.',
            ),
        ],
        metadata={"task_completed": True, "review_size_loc": 30},
    )


@pytest.fixture
def instruction_drift_trace() -> Trace:
    """A trace whose evidence mentions steps outside the task scope."""
    return _make_trace(
        steps=[
            _make_step(1, "read_task", [], "Parsed task."),
            _make_step(
                2,
                "edit_unrelated",
                ["app/unrelated.py"],
                "Rewrote unrelated helpers outside the task scope.",
            ),
        ],
        metadata={"task_completed": True, "review_size_loc": 50},
    )


@pytest.fixture
def convention_violation_trace() -> Trace:
    """A trace with an explicit convention-violation signal in evidence."""
    return _make_trace(
        steps=[
            _make_step(1, "read_task", [], "Parsed task."),
            _make_step(
                2,
                "edit_file",
                ["app/wrong.py"],
                "Placed code in wrong location; convention violation detected.",
            ),
        ],
        metadata={"task_completed": True, "review_size_loc": 50},
    )


@pytest.fixture
def incomplete_task_trace() -> Trace:
    """A trace with task_completed=False."""
    return _make_trace(
        steps=[
            _make_step(1, "read_task", [], "Parsed task."),
            _make_step(
                2,
                "partial_edit",
                ["app/main.py"],
                "Started implementation but left incomplete.",
            ),
        ],
        metadata={"task_completed": False, "review_size_loc": 50},
    )


@pytest.fixture
def low_reviewability_trace() -> Trace:
    """A trace with review_size_loc above the LOW_REVIEWABILITY threshold."""
    return _make_trace(
        steps=[
            _make_step(1, "edit_code", ["app/main.py"], "Large-scale change."),
        ],
        metadata={"task_completed": True, "review_size_loc": 500},
    )


@pytest.fixture
def multi_failure_trace() -> Trace:
    """A trace designed to trigger both OVER_EDITING and TEST_REGRESSION."""
    many_files = [f"app/file{i}.py" for i in range(10)]
    return _make_trace(
        steps=[
            _make_step(1, "edit_many", many_files, "Edited many files."),
            _make_step(
                2,
                "run_tests",
                [],
                "pytest_failed: tests/test_core.py::test_main FAILED",
            ),
        ],
        metadata={"task_completed": True, "review_size_loc": 50},
    )


# ---------------------------------------------------------------------------
# VAL-FAIL-001: Every detected FailureMode has the correct stable shape
# ---------------------------------------------------------------------------


def test_failure_mode_shape(trace_v1: Trace, trace_v2: Trace) -> None:
    """VAL-FAIL-001: Every emitted FailureMode has code, severity, non-empty evidence."""
    from tracecaliper.failure_modes import detect_failure_modes

    for trace in (trace_v1, trace_v2):
        modes = detect_failure_modes(trace)
        for mode in modes:
            assert isinstance(mode, FailureMode)
            assert mode.code in FAILURE_MODE_CODES
            assert mode.severity in ("low", "medium", "high", "critical")
            assert mode.evidence.strip(), "evidence must be non-empty"


# ---------------------------------------------------------------------------
# VAL-FAIL-002: All codes are within the documented taxonomy
# ---------------------------------------------------------------------------


def test_failure_mode_codes_in_taxonomy(
    trace_v1: Trace,
    trace_v2: Trace,
    over_editing_trace: Trace,
    security_trace: Trace,
) -> None:
    """VAL-FAIL-002: Detected codes are always within the 7-code taxonomy."""
    from tracecaliper.failure_modes import detect_failure_modes

    for trace in (trace_v1, trace_v2, over_editing_trace, security_trace):
        modes = detect_failure_modes(trace)
        for mode in modes:
            assert mode.code in FAILURE_MODE_CODES, (
                f"Unexpected code {mode.code!r}; allowed: {FAILURE_MODE_CODES}"
            )


# ---------------------------------------------------------------------------
# VAL-FAIL-003: Detection is deterministic across repeated runs
# ---------------------------------------------------------------------------


def test_detection_is_deterministic(trace_v1: Trace, trace_v2: Trace) -> None:
    """VAL-FAIL-003: Two consecutive detections yield byte-identical results."""
    from tracecaliper.failure_modes import detect_failure_modes

    for trace in (trace_v1, trace_v2):
        modes1 = detect_failure_modes(trace)
        modes2 = detect_failure_modes(trace)
        assert [m.model_dump() for m in modes1] == [m.model_dump() for m in modes2]


# ---------------------------------------------------------------------------
# VAL-FAIL-004: Multiple detectors may fire on a single trace
# ---------------------------------------------------------------------------


def test_multiple_detectors_fire(multi_failure_trace: Trace) -> None:
    """VAL-FAIL-004: Both OVER_EDITING and TEST_REGRESSION fire on multi_failure_trace."""
    from tracecaliper.failure_modes import detect_failure_modes

    modes = detect_failure_modes(multi_failure_trace)
    codes = {m.code for m in modes}
    assert "OVER_EDITING" in codes
    assert "TEST_REGRESSION" in codes


# ---------------------------------------------------------------------------
# VAL-FAIL-005: Clean traces produce an empty failure-mode set
# ---------------------------------------------------------------------------


def test_clean_trace_produces_empty_list(clean_trace: Trace) -> None:
    """VAL-FAIL-005: A clean trace yields an empty failure-mode list, not None."""
    from tracecaliper.failure_modes import detect_failure_modes

    modes = detect_failure_modes(clean_trace)
    assert modes == []


# ---------------------------------------------------------------------------
# VAL-FAIL-006: Output is stable, sorted by code, identical across two runs
# ---------------------------------------------------------------------------


def test_failure_mode_list_sorted_by_code(
    multi_failure_trace: Trace,
    trace_v1: Trace,
) -> None:
    """VAL-FAIL-006: Output list is sorted by code; two runs produce identical ordering."""
    from tracecaliper.failure_modes import detect_failure_modes

    for trace in (multi_failure_trace, trace_v1):
        modes1 = detect_failure_modes(trace)
        modes2 = detect_failure_modes(trace)
        codes1 = [m.code for m in modes1]
        codes2 = [m.code for m in modes2]
        assert codes1 == sorted(codes1), f"codes not sorted: {codes1}"
        assert codes1 == codes2, "ordering differs between two runs"


# ---------------------------------------------------------------------------
# VAL-FAIL-007: SECURITY_FLAG fires for security-suspect traces
# ---------------------------------------------------------------------------


def test_security_flag_fires_on_synthetic(security_trace: Trace) -> None:
    """VAL-FAIL-007: SECURITY_FLAG fires with non-empty evidence citing the offending step."""
    from tracecaliper.failure_modes import detect_failure_modes

    modes = detect_failure_modes(security_trace)
    codes = {m.code for m in modes}
    assert "SECURITY_FLAG" in codes
    sf = next(m for m in modes if m.code == "SECURITY_FLAG")
    assert sf.evidence.strip()
    assert "step" in sf.evidence.lower(), "evidence must reference the offending step"


def test_security_flag_fires_on_v2(trace_v2: Trace) -> None:
    """VAL-FAIL-007: SECURITY_FLAG fires on example trace v2 (has hardcoded credential)."""
    from tracecaliper.failure_modes import detect_failure_modes

    modes = detect_failure_modes(trace_v2)
    codes = {m.code for m in modes}
    assert "SECURITY_FLAG" in codes


def test_security_flag_not_on_clean(clean_trace: Trace) -> None:
    """SECURITY_FLAG must NOT fire on a clean trace."""
    from tracecaliper.failure_modes import detect_failure_modes

    modes = detect_failure_modes(clean_trace)
    codes = {m.code for m in modes}
    assert "SECURITY_FLAG" not in codes


# ---------------------------------------------------------------------------
# VAL-FAIL-008: TEST_REGRESSION fires for regressing test outcomes
# ---------------------------------------------------------------------------


def test_test_regression_fires_evidence(
    test_regression_trace_evidence: Trace,
) -> None:
    """VAL-FAIL-008: TEST_REGRESSION fires when evidence contains pytest_failed signal;
    evidence enumerates the failing test identifier extracted from the signal."""
    from tracecaliper.failure_modes import detect_failure_modes

    modes = detect_failure_modes(test_regression_trace_evidence)
    codes = {m.code for m in modes}
    assert "TEST_REGRESSION" in codes
    tr = next(m for m in modes if m.code == "TEST_REGRESSION")
    assert tr.evidence.strip(), "evidence must be non-empty"
    # The evidence must explicitly reference the named failing test identifier.
    assert "tests/test_items.py::test_get_item" in tr.evidence, (
        f"evidence must list the failing test identifier; got: {tr.evidence!r}"
    )


def test_test_regression_fires_metadata(
    test_regression_trace_metadata: Trace,
) -> None:
    """VAL-FAIL-008: TEST_REGRESSION fires when metadata shows more failing tests."""
    from tracecaliper.failure_modes import detect_failure_modes

    modes = detect_failure_modes(test_regression_trace_metadata)
    codes = {m.code for m in modes}
    assert "TEST_REGRESSION" in codes
    tr = next(m for m in modes if m.code == "TEST_REGRESSION")
    assert tr.evidence.strip()


@pytest.fixture
def test_regression_trace_metadata_named() -> Trace:
    """A trace whose metadata shows a regression AND provides named failing tests."""
    return _make_trace(
        steps=[
            _make_step(1, "edit_code", ["app/main.py"], "Edited code."),
        ],
        metadata={
            "task_completed": True,
            "tests": {
                "before": {"passing": 10, "failing": 1},
                "after": {"passing": 9, "failing": 2},
            },
            "failing_tests": [
                "tests/test_auth.py::test_login",
                "tests/test_auth.py::test_logout",
            ],
            "review_size_loc": 50,
        },
    )


def test_test_regression_evidence_lists_failing_tests_from_metadata(
    test_regression_trace_metadata_named: Trace,
) -> None:
    """VAL-FAIL-008: When metadata.failing_tests is provided, evidence explicitly
    enumerates the named failing test identifiers."""
    from tracecaliper.failure_modes import detect_failure_modes

    modes = detect_failure_modes(test_regression_trace_metadata_named)
    codes = {m.code for m in modes}
    assert "TEST_REGRESSION" in codes
    tr = next(m for m in modes if m.code == "TEST_REGRESSION")
    assert "tests/test_auth.py::test_login" in tr.evidence, (
        f"evidence must list test_login; got: {tr.evidence!r}"
    )
    assert "tests/test_auth.py::test_logout" in tr.evidence, (
        f"evidence must list test_logout; got: {tr.evidence!r}"
    )


def test_test_regression_not_on_improving_v2(trace_v2: Trace) -> None:
    """TEST_REGRESSION must NOT fire on v2 (failing tests decreased, not increased)."""
    from tracecaliper.failure_modes import detect_failure_modes

    modes = detect_failure_modes(trace_v2)
    codes = {m.code for m in modes}
    assert "TEST_REGRESSION" not in codes


# ---------------------------------------------------------------------------
# VAL-FAIL-009: OVER_EDITING fires for traces touching too many files
# ---------------------------------------------------------------------------


def test_over_editing_fires_synthetic(over_editing_trace: Trace) -> None:
    """VAL-FAIL-009: OVER_EDITING fires when unique files touched > threshold."""
    from tracecaliper.failure_modes import detect_failure_modes

    modes = detect_failure_modes(over_editing_trace)
    codes = {m.code for m in modes}
    assert "OVER_EDITING" in codes
    oe = next(m for m in modes if m.code == "OVER_EDITING")
    assert oe.severity in ("low", "medium", "high", "critical")
    assert oe.evidence.strip()


def test_over_editing_fires_on_v1(trace_v1: Trace) -> None:
    """VAL-FAIL-009: OVER_EDITING fires on v1 trace (12 unique files touched)."""
    from tracecaliper.failure_modes import detect_failure_modes

    modes = detect_failure_modes(trace_v1)
    codes = {m.code for m in modes}
    assert "OVER_EDITING" in codes


def test_over_editing_not_on_v2(trace_v2: Trace) -> None:
    """OVER_EDITING must NOT fire on v2 (only 6 unique files touched)."""
    from tracecaliper.failure_modes import detect_failure_modes

    modes = detect_failure_modes(trace_v2)
    codes = {m.code for m in modes}
    assert "OVER_EDITING" not in codes


# ---------------------------------------------------------------------------
# VAL-FAIL-010: Evidence is non-empty and human-readable for every mode
# ---------------------------------------------------------------------------


def test_evidence_non_empty_and_readable(
    trace_v1: Trace,
    trace_v2: Trace,
    over_editing_trace: Trace,
    security_trace: Trace,
    incomplete_task_trace: Trace,
) -> None:
    """VAL-FAIL-010: Every emitted FailureMode has non-empty, non-whitespace evidence."""
    from tracecaliper.failure_modes import detect_failure_modes

    for trace in (
        trace_v1,
        trace_v2,
        over_editing_trace,
        security_trace,
        incomplete_task_trace,
    ):
        modes = detect_failure_modes(trace)
        for mode in modes:
            assert mode.evidence, f"evidence is falsy for {mode.code}"
            assert mode.evidence.strip(), f"evidence is whitespace-only for {mode.code}"


# ---------------------------------------------------------------------------
# VAL-FAIL-011: No exceptions on edge-case traces
# ---------------------------------------------------------------------------


def test_empty_steps_no_exception() -> None:
    """VAL-FAIL-011: Trace with empty steps list returns a list, never raises."""
    from tracecaliper.failure_modes import detect_failure_modes

    trace = _make_trace(steps=[])
    modes = detect_failure_modes(trace)
    assert isinstance(modes, list)


def test_none_metadata_no_exception() -> None:
    """VAL-FAIL-011: Trace with metadata=None returns a list, never raises."""
    from tracecaliper.failure_modes import detect_failure_modes

    trace = _make_trace(
        steps=[_make_step(1, "action", [], "some evidence text")],
        metadata=None,
    )
    modes = detect_failure_modes(trace)
    assert isinstance(modes, list)


def test_empty_metadata_dict_no_exception() -> None:
    """VAL-FAIL-011: Trace with empty metadata dict returns a list, never raises."""
    from tracecaliper.failure_modes import detect_failure_modes

    trace = _make_trace(
        steps=[_make_step(1, "action", [], "some evidence text")],
        metadata={},
    )
    modes = detect_failure_modes(trace)
    assert isinstance(modes, list)


def test_minimal_trace_no_exception() -> None:
    """VAL-FAIL-011: Minimal trace with no optional fields never raises."""
    from tracecaliper.failure_modes import detect_failure_modes

    trace = Trace(
        skill_id="test",
        simulated=True,
        label="SIMULATED — minimal edge case",
        steps=[],
    )
    modes = detect_failure_modes(trace)
    assert isinstance(modes, list)


def test_step_with_no_files_touched_no_exception() -> None:
    """VAL-FAIL-011: Steps with empty files_touched list never cause an exception."""
    from tracecaliper.failure_modes import detect_failure_modes

    trace = _make_trace(
        steps=[
            _make_step(1, "action", [], "evidence"),
            _make_step(2, "action2", [], "more evidence"),
        ],
        metadata=None,
    )
    modes = detect_failure_modes(trace)
    assert isinstance(modes, list)


# ---------------------------------------------------------------------------
# VAL-FAIL-012: Detection does not mutate the input trace
# ---------------------------------------------------------------------------


def test_detection_does_not_mutate_trace(trace_v1: Trace, trace_v2: Trace) -> None:
    """VAL-FAIL-012: Input trace model_dump() is identical before and after detection."""
    from tracecaliper.failure_modes import detect_failure_modes

    for trace in (trace_v1, trace_v2):
        snapshot_before = trace.model_dump()
        _ = detect_failure_modes(trace)
        snapshot_after = trace.model_dump()
        assert snapshot_before == snapshot_after, (
            "detect_failure_modes mutated the input trace"
        )
