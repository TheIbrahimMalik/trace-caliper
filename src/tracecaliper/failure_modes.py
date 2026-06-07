"""Failure-mode detectors for TraceCaliper.

One detector per code in the taxonomy:

- ``CONVENTION_VIOLATION``: Edits violate documented repo conventions.
- ``INCOMPLETE_TASK``: Final deliverable was not produced.
- ``INSTRUCTION_DRIFT``: Steps deviate from the documented skill instructions.
- ``LOW_REVIEWABILITY``: Diff is too large or unstructured to review.
- ``OVER_EDITING``: Too many unique files touched across all steps.
- ``SECURITY_FLAG``: Step matches a security-suspect signal.
- ``TEST_REGRESSION``: Previously-passing tests now fail.

Each detector takes a :class:`~tracecaliper.models.Trace` and returns an
``Optional[FailureMode]``.  The public entry-point
:func:`detect_failure_modes` runs all detectors, dedupes by code, and returns
the list **sorted by code** for determinism.

Detectors are **pure** and **heuristic**; thresholds are documented inline
and in ``docs/eval-methodology.md``.  They never raise on edge-case inputs
(empty step lists, missing optional fields) and never mutate the input trace.
"""

from __future__ import annotations

import re
from typing import Optional

from tracecaliper.models import FailureMode, Trace


# ---------------------------------------------------------------------------
# Heuristic thresholds (documented for eval-methodology.md)
# ---------------------------------------------------------------------------

_OVER_EDIT_FILES_THRESHOLD: int = 8
"""Total unique files touched at or above which OVER_EDITING fires.

Derived from the bundled example traces: the baseline trace (v1) touches
12 unique files across all steps, well above the in-scope requirement of 2;
the candidate trace (v2) touches 6 files.  Set to 8 so v1 fires and v2
does not.
"""

_LOW_REVIEWABILITY_LOC_THRESHOLD: int = 200
"""``review_size_loc`` value above which LOW_REVIEWABILITY fires.

Example traces: v1 has 412 LOC (fires); v2 has 138 LOC (does not fire).
"""

_SECURITY_RE = re.compile(
    r"("
    r"hardcode[d]?"
    r"|api[\s_-]?key\s*="
    r"|password\s*="
    r"|credential"
    r"|disable[\s_-]?auth"
    r"|AKIA[A-Z0-9]{16}"
    r"|ghp_[A-Za-z0-9]{36}"
    r"|sk-[A-Za-z0-9]{10,}"
    r")",
    re.IGNORECASE,
)
"""Regex matching security-suspect patterns in step evidence text.

Signals include: hardcoded credentials, ``api_key=``, ``password=``,
``disable_auth``, and known secret-token prefixes (AWS, GitHub, OpenAI).
"""

_INSTRUCTION_DRIFT_RE = re.compile(
    r"("
    r"outside\s+the\s+task\s+scope"
    r"|not\s+required\s+by"
    r"|unrelated"
    r"|deviat"
    r"|drift"
    r")",
    re.IGNORECASE,
)
"""Regex matching instruction-drift signals in step evidence.

Fires when evidence explicitly describes steps that go beyond, ignore, or
deviate from the task scope or skill instructions.
"""

_CONVENTION_VIOLATION_RE = re.compile(
    r"("
    r"convention\s+violation"
    r"|violate[sd]?\s+convention"
    r"|banned\s+import"
    r"|forbidden"
    r"|wrong\s+location"
    r"|wrong\s+format"
    r")",
    re.IGNORECASE,
)
"""Regex matching convention-violation signals in step evidence.

Fires when evidence explicitly describes violations of repo conventions,
use of banned imports, forbidden patterns, or wrong-location edits.
"""

_TEST_REGRESSION_RE = re.compile(
    r"("
    r"pytest_failed"
    r"|test_regression"
    r")",
    re.IGNORECASE,
)
"""Regex matching explicit test-regression signals in step evidence.

Intentionally narrow (only matches ``pytest_failed`` and ``test_regression``)
to avoid false positives on evidence text that mentions pre-existing failures.
The metadata heuristic (after.failing > before.failing) handles the broader
regression signal.
"""

_PYTEST_FAILED_NAME_RE = re.compile(
    r"pytest_failed:\s*(\S+)",
    re.IGNORECASE,
)
"""Regex to extract the failing test identifier from a ``pytest_failed`` signal.

Applied to step evidence of the form ``pytest_failed: <test_id> [FAILED]``
to surface ``<test_id>`` (e.g. ``tests/test_items.py::test_get_item``).
"""


# ---------------------------------------------------------------------------
# Individual detectors
# ---------------------------------------------------------------------------


def detect_over_editing(trace: Trace) -> Optional[FailureMode]:
    """Detect OVER_EDITING: fires when unique files touched exceeds the threshold.

    Heuristic: count all unique ``files_touched`` values across every step.
    If that count exceeds :data:`_OVER_EDIT_FILES_THRESHOLD` (8), emit
    ``OVER_EDITING`` with ``medium`` severity.

    The threshold is calibrated against the bundled example traces (v1 touches
    12 unique files; v2 touches 6).
    """
    touched: set[str] = set()
    for step in trace.steps:
        touched.update(step.files_touched)
    count = len(touched)
    if count > _OVER_EDIT_FILES_THRESHOLD:
        sample = sorted(touched)[:5]
        ellipsis = "..." if count > 5 else ""
        return FailureMode(
            code="OVER_EDITING",
            severity="medium",
            evidence=(
                f"{count} unique file(s) touched across all steps, "
                f"exceeding the threshold of {_OVER_EDIT_FILES_THRESHOLD}. "
                f"Files include: {', '.join(sample)}{ellipsis}."
            ),
        )
    return None


def detect_test_regression(trace: Trace) -> Optional[FailureMode]:
    """Detect TEST_REGRESSION: fires when tests regress compared to the pre-state.

    Two independent heuristics:

    1. **Metadata heuristic**: ``metadata.tests.after.failing`` >
       ``metadata.tests.before.failing`` (definitive signal).  When
       ``metadata.failing_tests`` is present its entries are listed
       explicitly in the evidence; otherwise the numeric delta is reported.
    2. **Evidence heuristic**: any step's ``evidence`` matches
       :data:`_TEST_REGRESSION_RE` (``pytest_failed``, ``test_regression``).
       When ``pytest_failed: <test_id>`` patterns are found the evidence
       explicitly enumerates the extracted test identifiers.

    The metadata heuristic is checked first; if it fires, the evidence
    heuristic is skipped to avoid duplicate reporting.
    """
    meta = trace.metadata or {}
    tests = meta.get("tests")
    if isinstance(tests, dict):
        before = tests.get("before") or {}
        after = tests.get("after") or {}
        before_failing = int(before.get("failing") or 0)
        after_failing = int(after.get("failing") or 0)
        if after_failing > before_failing:
            delta = after_failing - before_failing
            # Prefer named identifiers from metadata.failing_tests when available.
            named: list[str] = []
            failing_tests_meta = meta.get("failing_tests")
            if isinstance(failing_tests_meta, list):
                named = [str(t) for t in failing_tests_meta if t]
            if named:
                tests_listed = ", ".join(named)
                return FailureMode(
                    code="TEST_REGRESSION",
                    severity="high",
                    evidence=(
                        f"Test regression detected: failing tests increased from "
                        f"{before_failing} to {after_failing} "
                        f"(+{delta} newly failing). "
                        f"Failing tests: {tests_listed}."
                    ),
                )
            else:
                return FailureMode(
                    code="TEST_REGRESSION",
                    severity="high",
                    evidence=(
                        f"{delta} test(s) regressing: "
                        f"metadata.tests_after.failing={after_failing} vs "
                        f"metadata.tests_before.failing={before_failing}."
                    ),
                )

    # Evidence heuristic: extract named test identifiers from pytest_failed patterns.
    flagged_ids: list[str] = []
    flagged_steps: list[str] = []
    for step in trace.steps:
        m = _TEST_REGRESSION_RE.search(step.evidence)
        if m:
            name_m = _PYTEST_FAILED_NAME_RE.search(step.evidence)
            if name_m:
                flagged_ids.append(name_m.group(1))
            else:
                flagged_steps.append(
                    f"step {step.index} ({step.action!r}): matched {m.group(0)!r}"
                )
    if flagged_ids or flagged_steps:
        parts: list[str] = []
        if flagged_ids:
            parts.append(f"Failing tests: {', '.join(flagged_ids)}.")
        if flagged_steps:
            parts.append(
                f"Test-regression signal(s) found in {len(flagged_steps)} step(s): "
                f"{'; '.join(flagged_steps)}."
            )
        return FailureMode(
            code="TEST_REGRESSION",
            severity="high",
            evidence=" ".join(parts),
        )
    return None


def detect_instruction_drift(trace: Trace) -> Optional[FailureMode]:
    """Detect INSTRUCTION_DRIFT: fires when steps deviate from the skill instructions.

    Heuristic: scans each step's ``evidence`` string for phrases that indicate
    the agent went beyond or ignored the task scope (e.g., "outside the task
    scope", "not required by", "unrelated").  Uses :data:`_INSTRUCTION_DRIFT_RE`.
    """
    flagged: list[str] = []
    for step in trace.steps:
        m = _INSTRUCTION_DRIFT_RE.search(step.evidence)
        if m:
            flagged.append(
                f"step {step.index} ({step.action!r}): {m.group(0)!r}"
            )
    if flagged:
        return FailureMode(
            code="INSTRUCTION_DRIFT",
            severity="medium",
            evidence=(
                f"Instruction-drift signal(s) found in "
                f"{len(flagged)} step(s): {'; '.join(flagged)}."
            ),
        )
    return None


def detect_security_flag(trace: Trace) -> Optional[FailureMode]:
    """Detect SECURITY_FLAG: fires when a step matches a security-suspect pattern.

    Heuristic: scans each step's ``evidence`` string against
    :data:`_SECURITY_RE`.  Matches include hardcoded credentials, API keys,
    ``disable_auth``, and known secret-token prefixes.  The first match per
    step is reported; evidence cites all offending steps.
    """
    flagged: list[str] = []
    for step in trace.steps:
        m = _SECURITY_RE.search(step.evidence)
        if m:
            flagged.append(
                f"step {step.index} ({step.action!r}): matched {m.group(0)!r}"
            )
    if flagged:
        return FailureMode(
            code="SECURITY_FLAG",
            severity="critical",
            evidence=(
                f"Security-suspect signal(s) found in "
                f"{len(flagged)} step(s): {'; '.join(flagged)}."
            ),
        )
    return None


def detect_convention_violation(trace: Trace) -> Optional[FailureMode]:
    """Detect CONVENTION_VIOLATION: fires when steps explicitly violate repo conventions.

    Heuristic: scans each step's ``evidence`` for phrases that explicitly
    describe convention violations, banned imports, forbidden patterns, or
    wrong-location edits.  Uses :data:`_CONVENTION_VIOLATION_RE`.
    """
    flagged: list[str] = []
    for step in trace.steps:
        m = _CONVENTION_VIOLATION_RE.search(step.evidence)
        if m:
            flagged.append(
                f"step {step.index} ({step.action!r}): {m.group(0)!r}"
            )
    if flagged:
        return FailureMode(
            code="CONVENTION_VIOLATION",
            severity="medium",
            evidence=(
                f"Convention-violation signal(s) found in "
                f"{len(flagged)} step(s): {'; '.join(flagged)}."
            ),
        )
    return None


def detect_incomplete_task(trace: Trace) -> Optional[FailureMode]:
    """Detect INCOMPLETE_TASK: fires when the task was not completed.

    Heuristic: checks ``metadata.task_completed``.  If it is explicitly
    ``False``, the task deliverable was not produced.  A missing flag (``None``)
    is treated as neutral (no detection).
    """
    meta = trace.metadata or {}
    completed = meta.get("task_completed")
    if completed is False:
        return FailureMode(
            code="INCOMPLETE_TASK",
            severity="high",
            evidence=(
                "Trace metadata reports task_completed=false; "
                "the final deliverable was not produced as required by the skill."
            ),
        )
    return None


def detect_low_reviewability(trace: Trace) -> Optional[FailureMode]:
    """Detect LOW_REVIEWABILITY: fires when the diff is too large to review.

    Heuristic: reads ``metadata.review_size_loc`` (lines of code changed).
    If it exceeds :data:`_LOW_REVIEWABILITY_LOC_THRESHOLD` (200), emit
    ``LOW_REVIEWABILITY`` with ``low`` severity.

    Example traces: v1 has 412 LOC (fires); v2 has 138 LOC (does not fire).
    """
    meta = trace.metadata or {}
    loc = meta.get("review_size_loc")
    if loc is not None:
        try:
            loc_f = float(loc)
        except (TypeError, ValueError):
            return None
        if loc_f > _LOW_REVIEWABILITY_LOC_THRESHOLD:
            return FailureMode(
                code="LOW_REVIEWABILITY",
                severity="low",
                evidence=(
                    f"Diff size is {int(loc_f)} LOC, exceeding the reviewability "
                    f"threshold of {_LOW_REVIEWABILITY_LOC_THRESHOLD} LOC. "
                    "Large diffs are difficult to review effectively."
                ),
            )
    return None


# ---------------------------------------------------------------------------
# Detector registry — alphabetical by failure-mode code for stable iteration
# ---------------------------------------------------------------------------

_DETECTORS = (
    detect_convention_violation,
    detect_incomplete_task,
    detect_instruction_drift,
    detect_low_reviewability,
    detect_over_editing,
    detect_security_flag,
    detect_test_regression,
)
"""All seven detector functions, ordered alphabetically by failure-mode code.

This ordering mirrors the sorted output of :func:`detect_failure_modes` and
makes the registry self-documenting.
"""


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def detect_failure_modes(trace: Trace) -> list[FailureMode]:
    """Run all failure-mode detectors against *trace*.

    Each detector is run independently.  Results are collected, deduped by
    code (first occurrence wins), and returned **sorted by code** for
    determinism.

    Args:
        trace: The trace to inspect.  Not mutated.

    Returns:
        Sorted list of :class:`~tracecaliper.models.FailureMode` instances.
        Returns an empty list if no failure modes are detected.
        **Never raises** — edge-case inputs (empty steps, missing optional
        fields) yield an empty list.
    """
    seen: set[str] = set()
    modes: list[FailureMode] = []
    for detector in _DETECTORS:
        try:
            result = detector(trace)
        except Exception:  # noqa: BLE001
            continue
        if result is not None and result.code not in seen:
            seen.add(result.code)
            modes.append(result)
    return sorted(modes, key=lambda m: m.code)


__all__ = [
    "_OVER_EDIT_FILES_THRESHOLD",
    "_LOW_REVIEWABILITY_LOC_THRESHOLD",
    "detect_convention_violation",
    "detect_incomplete_task",
    "detect_instruction_drift",
    "detect_low_reviewability",
    "detect_over_editing",
    "detect_security_flag",
    "detect_test_regression",
    "detect_failure_modes",
    "_PYTEST_FAILED_NAME_RE",
]
