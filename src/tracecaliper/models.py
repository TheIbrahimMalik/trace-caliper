"""TraceCaliper Pydantic v2 data models.

This module is the single source of truth for the TraceCaliper schemas:
:class:`Suite`, :class:`Skill`, :class:`Trace`, :class:`TraceStep`,
:class:`DimensionScore`, :class:`TraceScore`, :class:`FailureMode`,
:class:`Comparison`, and :class:`GateDecision`.

All models are deterministic: collections that participate in serialization
(weight maps, dimension-delta maps, failure-mode code lists) are sorted at
validation time so that two value-equal instances always produce
byte-identical ``model_dump_json(indent=2)`` output.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


DIMENSION_NAMES: tuple[str, ...] = (
    "tests_passed",
    "task_completion",
    "security",
    "over_editing",
    "repo_conventions",
    "instruction_following",
    "reviewability",
)
"""Canonical ordering of the seven rubric dimensions."""


DEFAULT_WEIGHTS: dict[str, float] = {
    "tests_passed": 0.25,
    "task_completion": 0.25,
    "security": 0.20,
    "over_editing": 0.10,
    "repo_conventions": 0.08,
    "instruction_following": 0.07,
    "reviewability": 0.05,
}
"""Documented default weights for the seven rubric dimensions."""


FAILURE_MODE_CODES: tuple[str, ...] = (
    "OVER_EDITING",
    "TEST_REGRESSION",
    "INSTRUCTION_DRIFT",
    "SECURITY_FLAG",
    "CONVENTION_VIOLATION",
    "INCOMPLETE_TASK",
    "LOW_REVIEWABILITY",
)
"""Canonical taxonomy of failure-mode codes."""


DimensionName = Literal[
    "tests_passed",
    "task_completion",
    "security",
    "over_editing",
    "repo_conventions",
    "instruction_following",
    "reviewability",
]

FailureModeCode = Literal[
    "OVER_EDITING",
    "TEST_REGRESSION",
    "INSTRUCTION_DRIFT",
    "SECURITY_FLAG",
    "CONVENTION_VIOLATION",
    "INCOMPLETE_TASK",
    "LOW_REVIEWABILITY",
]

Severity = Literal["low", "medium", "high", "critical"]

DecisionOutcome = Literal["PASS", "HOLD", "INVESTIGATE"]


class _Base(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )


class Skill(_Base):
    """A skill referenced by a :class:`Suite`."""

    id: str
    path: str
    description: str


class Suite(_Base):
    """An evaluation suite: a named, weighted set of skills.

    The ``weights`` field stores only what the YAML provides; defaults are
    layered in by a separate ``resolve_weights`` helper (implemented in the
    scoring module). The raw model rejects negative weights and any key
    outside the seven-dimension allow-list.
    """

    name: str
    description: str
    weights: dict[str, float] = Field(default_factory=dict)
    skills: list[Skill]

    @field_validator("weights")
    @classmethod
    def _validate_weights(cls, value: dict[str, float]) -> dict[str, float]:
        allowed = set(DIMENSION_NAMES)
        for key, weight in value.items():
            if key not in allowed:
                raise ValueError(
                    f"Unknown weight dimension key {key!r}; "
                    f"allowed dimensions: {sorted(allowed)}"
                )
            if weight < 0:
                raise ValueError(
                    f"Negative weight for dimension {key!r}: {weight!r}; "
                    "weights must be non-negative"
                )
        return {k: value[k] for k in sorted(value.keys())}


class TraceStep(_Base):
    """A single ordered step within a :class:`Trace`."""

    index: int
    action: str
    files_touched: list[str] = Field(default_factory=list)
    evidence: str


class Trace(_Base):
    """A recorded (simulated, for the MVP) execution trace of a skill."""

    skill_id: str
    simulated: bool
    label: str
    steps: list[TraceStep]
    metadata: dict[str, Any] | None = None

    @field_validator("label")
    @classmethod
    def _label_mentions_simulated(cls, value: str) -> str:
        if "simulated" not in value.lower():
            raise ValueError(
                "Trace.label must contain the word 'simulated' "
                "(case-insensitive)"
            )
        return value

    @model_validator(mode="after")
    def _validate_step_indices(self) -> "Trace":
        indices = [s.index for s in self.steps]
        if len(indices) != len(set(indices)):
            raise ValueError(
                "Trace.steps contains duplicate index values; "
                f"saw indices {indices!r}"
            )
        for prev, curr in zip(indices, indices[1:]):
            if curr <= prev:
                raise ValueError(
                    "Trace.steps index values must be strictly increasing; "
                    f"saw {prev!r} followed by {curr!r}"
                )
        return self


class DimensionScore(_Base):
    """A per-dimension score with bounded value and a rationale."""

    name: DimensionName
    score: float = Field(ge=0.0, le=1.0)
    rationale: str


class TraceScore(_Base):
    """The aggregate score of a trace across all seven rubric dimensions."""

    trace_id: str
    dimensions: list[DimensionScore]
    weights: dict[str, float]
    weighted_total: float

    @field_validator("weights")
    @classmethod
    def _sort_weights(cls, value: dict[str, float]) -> dict[str, float]:
        return {k: value[k] for k in sorted(value.keys())}

    @model_validator(mode="after")
    def _validate_dimensions(self) -> "TraceScore":
        names = [d.name for d in self.dimensions]
        if len(names) != len(DIMENSION_NAMES) or set(names) != set(DIMENSION_NAMES):
            raise ValueError(
                "TraceScore.dimensions must contain exactly one DimensionScore "
                f"per rubric dimension; got names {sorted(names)!r}"
            )
        if names != sorted(names):
            raise ValueError(
                "TraceScore.dimensions must be sorted alphabetically by name"
            )
        return self


class FailureMode(_Base):
    """A detected failure-mode signal attached to a trace."""

    code: FailureModeCode
    severity: Severity
    evidence: str

    @field_validator("evidence")
    @classmethod
    def _non_empty_evidence(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("FailureMode.evidence must be non-empty")
        return value


class Comparison(_Base):
    """A pairwise comparison between baseline and candidate trace scores."""

    baseline: TraceScore
    candidate: TraceScore
    dimension_deltas: dict[str, float]
    aggregate_delta: float
    introduced: list[str]
    resolved: list[str]
    persistent: list[str]

    @field_validator("dimension_deltas")
    @classmethod
    def _sort_dimension_deltas(cls, value: dict[str, float]) -> dict[str, float]:
        allowed = set(DIMENSION_NAMES)
        for key in value:
            if key not in allowed:
                raise ValueError(
                    f"Unknown dimension key in dimension_deltas: {key!r}; "
                    f"allowed dimensions: {sorted(allowed)}"
                )
        return {k: value[k] for k in sorted(value.keys())}

    @field_validator("introduced", "resolved", "persistent")
    @classmethod
    def _validate_failure_mode_codes(cls, value: list[str]) -> list[str]:
        allowed = set(FAILURE_MODE_CODES)
        for code in value:
            if code not in allowed:
                raise ValueError(
                    f"Unknown failure-mode code {code!r}; "
                    f"allowed codes: {sorted(allowed)}"
                )
        return sorted(value)


class GateDecision(_Base):
    """The release-gate verdict and rationale."""

    decision: DecisionOutcome
    rationale: list[str]

    @field_validator("rationale")
    @classmethod
    def _validate_rationale(cls, value: list[str]) -> list[str]:
        if len(value) == 0:
            raise ValueError(
                "GateDecision.rationale must contain at least one entry"
            )
        for entry in value:
            if not isinstance(entry, str) or entry.strip() == "":
                raise ValueError(
                    "Each GateDecision.rationale entry must be a non-empty, "
                    "non-whitespace string"
                )
        return value


__all__ = [
    "DIMENSION_NAMES",
    "DEFAULT_WEIGHTS",
    "FAILURE_MODE_CODES",
    "DimensionName",
    "FailureModeCode",
    "Severity",
    "DecisionOutcome",
    "Skill",
    "Suite",
    "TraceStep",
    "Trace",
    "DimensionScore",
    "TraceScore",
    "FailureMode",
    "Comparison",
    "GateDecision",
]
