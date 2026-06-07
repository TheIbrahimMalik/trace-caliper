"""Deterministic scoring engine for TraceCaliper.

Module-level :data:`DEFAULT_WEIGHTS` re-exports the seven default rubric
weights from :mod:`tracecaliper.models`.

:func:`resolve_weights` layers suite-level overrides onto the defaults.

Seven pure scorer functions — one per rubric dimension — each accept a
:class:`~tracecaliper.models.Trace` and return a
:class:`~tracecaliper.models.DimensionScore`.

:func:`score_trace` aggregates them into a
:class:`~tracecaliper.models.TraceScore`, computing
``weighted_total`` as the dot product of per-dimension scores and weights.
No auto-normalisation is performed.
"""

from __future__ import annotations

import re

from tracecaliper.models import (
    DEFAULT_WEIGHTS,  # re-exported so ``from tracecaliper.scoring import DEFAULT_WEIGHTS`` works
    DIMENSION_NAMES,
    DimensionScore,
    Trace,
    TraceScore,
)

__all__ = [
    "DEFAULT_WEIGHTS",
    "resolve_weights",
    "score_instruction_following",
    "score_over_editing",
    "score_repo_conventions",
    "score_reviewability",
    "score_security",
    "score_task_completion",
    "score_tests_passed",
    "score_trace",
]

# ---------------------------------------------------------------------------
# Heuristic thresholds (documented for eval-methodology.md)
# ---------------------------------------------------------------------------

_OVER_EDIT_MAX_RATIO: float = 5.0
"""Files-touched / scope-size ratio at which ``over_editing`` score reaches 0.0.

Linear interpolation between 1.0 (ratio=1.0) and 0.0 (ratio>=5.0).
"""

_REVIEWABILITY_MIN_LOC: int = 50
"""Diff size (LOC) at or below which ``reviewability`` score is 1.0."""

_REVIEWABILITY_MAX_LOC: int = 1000
"""Diff size (LOC) at or above which ``reviewability`` score is 0.0.

Linear interpolation between 1.0 (<=50 LOC) and 0.0 (>=1000 LOC).
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
"""Regex matching security-suspect patterns in step evidence text."""


# ---------------------------------------------------------------------------
# Weight resolution
# ---------------------------------------------------------------------------


def resolve_weights(suite_weights: dict[str, float] | None) -> dict[str, float]:
    """Return the complete resolved weight dict for all seven dimensions.

    Layers *suite_weights* overrides onto :data:`DEFAULT_WEIGHTS`.  Partial
    overrides fall back to defaults for any unspecified dimension.

    Args:
        suite_weights: Suite-level weight overrides (may be partial or empty).
            Pass ``None`` to receive a fresh copy of :data:`DEFAULT_WEIGHTS`.

    Returns:
        Dict mapping every dimension name to its resolved ``float`` weight,
        with keys in insertion order (matches ``DEFAULT_WEIGHTS`` order plus
        any extra overrides).

    Raises:
        ValueError: If any value is negative, non-numeric, or a bool, with the
            error message referencing the offending dimension name.
    """
    if suite_weights is None:
        return dict(DEFAULT_WEIGHTS)

    resolved = dict(DEFAULT_WEIGHTS)
    for key, value in suite_weights.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(
                f"Non-numeric weight for dimension {key!r}: {value!r}; "
                "weights must be a numeric int or float (not bool)"
            )
        fval = float(value)
        if fval < 0:
            raise ValueError(
                f"Negative weight for dimension {key!r}: {value!r}; "
                "weights must be non-negative (>= 0)"
            )
        resolved[key] = fval
    return resolved


# ---------------------------------------------------------------------------
# Per-dimension scorer functions
# ---------------------------------------------------------------------------


def score_tests_passed(trace: Trace) -> DimensionScore:
    """Score based on test outcomes recorded in ``trace.metadata``.

    Heuristic:

    - ``score = passing / (passing + failing)`` when outcome data present.
    - 0.5 neutral when ``metadata.tests.after`` is absent.

    Thresholds: 0.0 (all failing) … 1.0 (all passing).
    """
    meta = trace.metadata or {}
    tests = meta.get("tests")
    after = tests.get("after") if isinstance(tests, dict) else None
    if not isinstance(after, dict):
        return DimensionScore(
            name="tests_passed",
            score=0.5,
            rationale="No test outcome data in trace metadata; neutral score.",
        )
    passing = after.get("passing")
    failing = after.get("failing")
    if passing is None or failing is None:
        return DimensionScore(
            name="tests_passed",
            score=0.5,
            rationale="Incomplete test outcome data in trace metadata; neutral score.",
        )
    if not isinstance(passing, (int, float)) or not isinstance(failing, (int, float)):
        return DimensionScore(
            name="tests_passed",
            score=0.5,
            rationale="Non-numeric test counts in metadata; neutral score.",
        )
    # Clamp to non-negative integers to avoid division-by-negative and scores
    # outside [0, 1] when negative counts are provided.
    passing = max(0, int(passing))
    failing = max(0, int(failing))
    total = passing + failing
    if total == 0:
        return DimensionScore(
            name="tests_passed",
            score=0.5,
            rationale="Trace metadata shows 0 tests recorded; neutral score.",
        )
    score = passing / total
    return DimensionScore(
        name="tests_passed",
        score=float(score),
        rationale=(
            f"{passing}/{total} tests passing after execution"
            f" ({failing} failing)."
        ),
    )


def score_task_completion(trace: Trace) -> DimensionScore:
    """Score based on the ``task_completed`` flag in ``trace.metadata``.

    Heuristic:

    - 1.0 when ``task_completed == True``.
    - 0.0 when ``task_completed == False``.
    - 0.5 neutral when the flag is absent.
    """
    meta = trace.metadata or {}
    completed = meta.get("task_completed")
    if completed is True:
        return DimensionScore(
            name="task_completion",
            score=1.0,
            rationale="Trace metadata confirms task_completed=true.",
        )
    if completed is False:
        return DimensionScore(
            name="task_completion",
            score=0.0,
            rationale=(
                "Trace metadata reports task_completed=false;"
                " deliverable incomplete."
            ),
        )
    return DimensionScore(
        name="task_completion",
        score=0.5,
        rationale="No task_completed flag in metadata; neutral score.",
    )


def score_security(trace: Trace) -> DimensionScore:
    """Score based on security-suspect signals in step evidence text.

    Scans each step's ``evidence`` string against :data:`_SECURITY_RE`.
    Any match sets the score to 0.0.  A clean trace scores 1.0.

    Signals detected include: hardcoded credentials, ``api_key=``,
    ``password=``, ``disable_auth``, and common secret-token prefixes.
    """
    flags: list[str] = []
    for step in trace.steps:
        if _SECURITY_RE.search(step.evidence):
            flags.append(f"step {step.index} ({step.action!r})")
    if not flags:
        return DimensionScore(
            name="security",
            score=1.0,
            rationale="No security-suspect signals detected in any step evidence.",
        )
    return DimensionScore(
        name="security",
        score=0.0,
        rationale=(
            f"Security-suspect signal(s) detected in "
            f"{len(flags)} step(s): {'; '.join(flags)}."
        ),
    )


def score_over_editing(trace: Trace) -> DimensionScore:
    """Score the inverse of over-editing: 1.0 = tight scope, 0.0 = severe excess.

    Heuristic: ``ratio = unique_files_touched / scope_size`` where
    ``scope_size = len(metadata.files_in_scope)`` (minimum 1).

    Thresholds (documented in ``docs/eval-methodology.md``):

    - ratio ≤ 1.0 → 1.0
    - 1.0 < ratio < :data:`_OVER_EDIT_MAX_RATIO` → linear interpolation
    - ratio ≥ :data:`_OVER_EDIT_MAX_RATIO` → 0.0
    """
    meta = trace.metadata or {}
    _raw_scope = meta.get("files_in_scope")
    scope: list[str] = list(_raw_scope) if isinstance(_raw_scope, (list, tuple, set)) else []
    scope_size = max(len(scope), 1)

    touched: set[str] = set()
    for step in trace.steps:
        touched.update(step.files_touched)
    touched_count = len(touched)

    ratio = touched_count / scope_size

    if ratio <= 1.0:
        return DimensionScore(
            name="over_editing",
            score=1.0,
            rationale=(
                f"{touched_count} file(s) touched vs {scope_size} in-scope;"
                " no over-editing."
            ),
        )
    if ratio >= _OVER_EDIT_MAX_RATIO:
        return DimensionScore(
            name="over_editing",
            score=0.0,
            rationale=(
                f"{touched_count} file(s) touched vs {scope_size} in-scope"
                f" (ratio={ratio:.2f} >= {_OVER_EDIT_MAX_RATIO});"
                " severe over-editing."
            ),
        )
    score = 1.0 - (ratio - 1.0) / (_OVER_EDIT_MAX_RATIO - 1.0)
    return DimensionScore(
        name="over_editing",
        score=score,
        rationale=(
            f"{touched_count} file(s) touched vs {scope_size} in-scope"
            f" (ratio={ratio:.2f}); over-editing detected."
        ),
    )


def score_repo_conventions(trace: Trace) -> DimensionScore:
    """Score the proportion of touched files that lie within the defined scope.

    Heuristic: ``score = in_scope_touched / total_touched``.

    Edge cases:

    - No files touched → 1.0 (nothing to violate).
    - No ``files_in_scope`` defined → 0.5 neutral.
    """
    meta = trace.metadata or {}
    _raw_scope = meta.get("files_in_scope")
    # Sanitize: convert each element to str before building the set to avoid
    # TypeError when files_in_scope contains unhashable elements (dicts, lists).
    scope: set[str] = (
        {str(e) for e in _raw_scope}
        if isinstance(_raw_scope, (list, tuple, set))
        else set()
    )

    if not scope:
        return DimensionScore(
            name="repo_conventions",
            score=0.5,
            rationale=(
                "No files_in_scope defined; cannot assess conventions;"
                " neutral score."
            ),
        )

    touched: set[str] = set()
    for step in trace.steps:
        touched.update(step.files_touched)

    if not touched:
        return DimensionScore(
            name="repo_conventions",
            score=1.0,
            rationale="No files touched; no convention violations possible.",
        )

    in_scope = touched & scope
    out_of_scope = touched - scope
    score = len(in_scope) / len(touched)

    if score == 1.0:
        rationale = (
            f"All {len(touched)} touched file(s) are within scope;"
            " conventions respected."
        )
    elif score == 0.0:
        rationale = (
            f"All {len(touched)} touched file(s) are outside scope;"
            " severe convention violation."
        )
    else:
        sample = sorted(out_of_scope)[:3]
        ellipsis_str = "..." if len(out_of_scope) > 3 else ""
        rationale = (
            f"{len(out_of_scope)} out-of-scope file(s) touched"
            f" (e.g., {', '.join(sample)}{ellipsis_str});"
            f" {len(in_scope)}/{len(touched)} within scope."
        )
    return DimensionScore(name="repo_conventions", score=score, rationale=rationale)


def score_instruction_following(trace: Trace) -> DimensionScore:
    """Score the proportion of steps that stay within the task scope.

    A step is considered "in-scope" when it touches no files, OR when all
    files it touches are listed in ``metadata.files_in_scope``.

    Edge cases:

    - No ``files_in_scope`` defined → 0.5 neutral.
    - No steps → 1.0 (instructions trivially followed).
    """
    meta = trace.metadata or {}
    _raw_scope = meta.get("files_in_scope")
    # Sanitize: convert each element to str before building the set to avoid
    # TypeError when files_in_scope contains unhashable elements (dicts, lists).
    scope: set[str] = (
        {str(e) for e in _raw_scope}
        if isinstance(_raw_scope, (list, tuple, set))
        else set()
    )

    if not scope:
        return DimensionScore(
            name="instruction_following",
            score=0.5,
            rationale=(
                "No files_in_scope defined; cannot assess instruction"
                " following; neutral score."
            ),
        )

    steps = trace.steps
    if not steps:
        return DimensionScore(
            name="instruction_following",
            score=1.0,
            rationale="No steps recorded; instructions trivially followed.",
        )

    in_scope_steps = sum(
        1
        for step in steps
        if not step.files_touched
        or all(f in scope for f in step.files_touched)
    )
    score = in_scope_steps / len(steps)

    if score == 1.0:
        rationale = (
            f"All {len(steps)} step(s) operate within task scope;"
            " instructions fully followed."
        )
    elif score == 0.0:
        rationale = (
            f"All {len(steps)} step(s) deviate from task scope;"
            " instructions not followed."
        )
    else:
        rationale = (
            f"{in_scope_steps}/{len(steps)} step(s) within task scope;"
            " partial instruction following."
        )
    return DimensionScore(
        name="instruction_following", score=score, rationale=rationale
    )


def score_reviewability(trace: Trace) -> DimensionScore:
    """Score based on diff size (``review_size_loc``) in trace metadata.

    Heuristic (documented in ``docs/eval-methodology.md``):

    - LOC ≤ :data:`_REVIEWABILITY_MIN_LOC` → 1.0
    - LOC ≥ :data:`_REVIEWABILITY_MAX_LOC` → 0.0
    - Linear interpolation in between.
    - Absent → 0.5 neutral.
    """
    meta = trace.metadata or {}
    loc = meta.get("review_size_loc")

    if loc is None:
        return DimensionScore(
            name="reviewability",
            score=0.5,
            rationale="No review_size_loc in metadata; neutral score.",
        )

    try:
        loc_f = float(loc)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DimensionScore(
            name="reviewability",
            score=0.5,
            rationale="Non-numeric review_size_loc in metadata; neutral score.",
        )
    loc_f = max(0.0, loc_f)
    if loc_f <= _REVIEWABILITY_MIN_LOC:
        return DimensionScore(
            name="reviewability",
            score=1.0,
            rationale=(
                f"Diff is {loc_f:.0f} LOC"
                f" (<={_REVIEWABILITY_MIN_LOC} threshold); highly reviewable."
            ),
        )
    if loc_f >= _REVIEWABILITY_MAX_LOC:
        return DimensionScore(
            name="reviewability",
            score=0.0,
            rationale=(
                f"Diff is {loc_f:.0f} LOC"
                f" (>={_REVIEWABILITY_MAX_LOC} threshold); too large to review."
            ),
        )
    score = 1.0 - (loc_f - _REVIEWABILITY_MIN_LOC) / (
        _REVIEWABILITY_MAX_LOC - _REVIEWABILITY_MIN_LOC
    )
    return DimensionScore(
        name="reviewability",
        score=score,
        rationale=f"Diff is {loc_f:.0f} LOC; partially reviewable.",
    )


# ---------------------------------------------------------------------------
# Scorer registry (alphabetical by dimension name for stable iteration)
# ---------------------------------------------------------------------------

_SCORERS = (
    score_instruction_following,
    score_over_editing,
    score_repo_conventions,
    score_reviewability,
    score_security,
    score_task_completion,
    score_tests_passed,
)
"""All seven scorer functions in alphabetical order by their dimension name."""


# ---------------------------------------------------------------------------
# Aggregate scorer
# ---------------------------------------------------------------------------


def score_trace(trace: Trace, weights: dict[str, float]) -> TraceScore:
    """Score *trace* across all seven rubric dimensions.

    Runs all seven per-dimension scorers, sorts the results alphabetically by
    dimension name, and computes ``weighted_total`` as the dot product of
    scores and weights.  Weights are **not** auto-normalised.

    Args:
        trace: The trace to score.  Not mutated.
        weights: Resolved weight dict mapping all seven dimension names to
            non-negative floats.  Obtain via :func:`resolve_weights`.

    Returns:
        :class:`~tracecaliper.models.TraceScore` with ``dimensions`` in
        alphabetical order, ``weights`` preserved verbatim, and
        ``trace_id`` set to ``trace.label``.
    """
    dimensions = sorted(
        [scorer(trace) for scorer in _SCORERS],
        key=lambda d: d.name,
    )
    weighted_total = sum(
        weights.get(d.name, 0.0) * d.score for d in dimensions
    )
    return TraceScore(
        trace_id=trace.label,
        dimensions=dimensions,
        weights=dict(weights),
        weighted_total=weighted_total,
    )
