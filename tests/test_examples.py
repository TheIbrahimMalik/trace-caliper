"""Tests for the bundled example artifacts.

These tests exercise the assertions in the Example Artifacts area of the
validation contract (``VAL-EX-001`` through ``VAL-EX-009``) that are
testable at this stage of the build (before the scoring, failure-mode,
and comparison engines exist).
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

import pytest
import yaml

from tracecaliper.models import (
    DEFAULT_WEIGHTS,
    DIMENSION_NAMES,
    Suite,
    Trace,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"

SUITE_PATH = EXAMPLES / "suites" / "python-api.yml"
SKILL_V1_PATH = EXAMPLES / "skills" / "skill-v1.md"
SKILL_V2_PATH = EXAMPLES / "skills" / "skill-v2.md"
TRACE_V1_PATH = EXAMPLES / "traces" / "skill-v1.json"
TRACE_V2_PATH = EXAMPLES / "traces" / "skill-v2.json"

ALL_EXAMPLE_PATHS: tuple[Path, ...] = (
    SUITE_PATH,
    SKILL_V1_PATH,
    SKILL_V2_PATH,
    TRACE_V1_PATH,
    TRACE_V2_PATH,
)

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AKIA[0-9A-Z]{0,}"),
    re.compile(r"ghp_[A-Za-z0-9]{0,}"),
    re.compile(r"sk-[A-Za-z0-9]{10,}"),
)

HOST_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|[\s\"'])/home/"),
    re.compile(r"(^|[\s\"'])/Users/"),
    re.compile(r"(^|[\s\"'])/root/"),
)


# ---------------------------------------------------------------------------
# VAL-EX-001: all example files exist and are non-empty
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ALL_EXAMPLE_PATHS, ids=lambda p: p.name)
def test_example_file_exists_and_non_empty(path: Path) -> None:
    assert path.exists(), f"missing example artifact: {path}"
    assert path.stat().st_size > 0, f"empty example artifact: {path}"


# ---------------------------------------------------------------------------
# VAL-EX-002: Suite YAML parses + validates with sane weights
# ---------------------------------------------------------------------------


def _load_suite() -> Suite:
    raw = yaml.safe_load(SUITE_PATH.read_text())
    return Suite.model_validate(raw)


def test_suite_yaml_parses_and_validates() -> None:
    suite = _load_suite()
    assert suite.name == "python-api"
    assert suite.description.strip()
    assert len(suite.skills) >= 2


def test_suite_has_complete_weight_map() -> None:
    suite = _load_suite()
    assert set(suite.weights.keys()) == set(DIMENSION_NAMES)
    for name, value in suite.weights.items():
        assert value >= 0.0, f"negative weight for {name}: {value}"


def test_suite_weights_sum_to_one() -> None:
    suite = _load_suite()
    total = sum(suite.weights.values())
    assert total == pytest.approx(1.0, abs=1e-9), (
        f"suite weights sum to {total!r}, expected 1.0 (±1e-9)"
    )


def test_suite_weights_match_documented_defaults() -> None:
    suite = _load_suite()
    for name, default in DEFAULT_WEIGHTS.items():
        assert suite.weights[name] == pytest.approx(default, abs=1e-9), (
            f"weight {name!r} = {suite.weights[name]!r}, "
            f"expected documented default {default!r}"
        )


# ---------------------------------------------------------------------------
# VAL-EX-003: Suite skill references resolve to existing files
# ---------------------------------------------------------------------------


def test_suite_skill_paths_resolve() -> None:
    suite = _load_suite()
    for skill in suite.skills:
        skill_path = REPO_ROOT / skill.path
        assert skill_path.exists(), (
            f"suite skill {skill.id!r} references missing file {skill.path!r}"
        )
        assert skill_path.is_file()


def test_suite_references_both_skill_versions() -> None:
    suite = _load_suite()
    paths = {skill.path for skill in suite.skills}
    assert "examples/skills/skill-v1.md" in paths
    assert "examples/skills/skill-v2.md" in paths


# ---------------------------------------------------------------------------
# VAL-EX-004: skill markdown files are well-formed and meaningfully differ
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [SKILL_V1_PATH, SKILL_V2_PATH], ids=lambda p: p.name)
def test_skill_markdown_starts_with_h1_title(path: Path) -> None:
    lines = path.read_text().splitlines()
    first_non_blank = next((ln for ln in lines if ln.strip()), "")
    assert first_non_blank.startswith("# "), (
        f"{path.name} must start with an H1 title (e.g., '# ...'); got {first_non_blank!r}"
    )


@pytest.mark.parametrize("path", [SKILL_V1_PATH, SKILL_V2_PATH], ids=lambda p: p.name)
def test_skill_markdown_contains_description_block(path: Path) -> None:
    text = path.read_text()
    lowered = text.lower()
    assert "## description" in lowered or "description" in lowered, (
        f"{path.name} must contain a description block"
    )


def test_skill_v1_and_v2_meaningfully_differ() -> None:
    v1_lines = [
        ln.strip()
        for ln in SKILL_V1_PATH.read_text().splitlines()
        if ln.strip()
    ]
    v2_lines = [
        ln.strip()
        for ln in SKILL_V2_PATH.read_text().splitlines()
        if ln.strip()
    ]
    differ = difflib.Differ()
    diff = list(differ.compare(v1_lines, v2_lines))
    differing = [line for line in diff if line.startswith(("+ ", "- "))]
    assert len(differing) >= 4, (
        "skill-v1.md and skill-v2.md must differ in at least 4 non-whitespace "
        f"lines; saw {len(differing)} differing lines"
    )


# ---------------------------------------------------------------------------
# VAL-EX-005: trace JSONs validate, indices unique and strictly increasing
# ---------------------------------------------------------------------------


def _load_trace(path: Path) -> Trace:
    return Trace.model_validate_json(path.read_text())


@pytest.mark.parametrize("path", [TRACE_V1_PATH, TRACE_V2_PATH], ids=lambda p: p.name)
def test_trace_validates_via_model(path: Path) -> None:
    trace = _load_trace(path)
    assert trace.steps, f"{path.name} must have at least one step"


@pytest.mark.parametrize("path", [TRACE_V1_PATH, TRACE_V2_PATH], ids=lambda p: p.name)
def test_trace_step_indices_unique_and_strictly_increasing(path: Path) -> None:
    trace = _load_trace(path)
    indices = [step.index for step in trace.steps]
    assert len(indices) == len(set(indices)), (
        f"{path.name} has duplicate step indices: {indices}"
    )
    for prev, curr in zip(indices, indices[1:]):
        assert curr > prev, (
            f"{path.name} step indices must be strictly increasing; "
            f"saw {prev} followed by {curr}"
        )


# ---------------------------------------------------------------------------
# VAL-EX-006: each trace explicitly labelled simulated
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [TRACE_V1_PATH, TRACE_V2_PATH], ids=lambda p: p.name)
def test_trace_simulated_flag_and_label(path: Path) -> None:
    raw = json.loads(path.read_text())
    assert raw.get("simulated") is True, (
        f"{path.name} must have simulated: true"
    )
    label = raw.get("label", "")
    assert isinstance(label, str)
    assert "simulated" in label.lower(), (
        f"{path.name} label must contain 'simulated' (case-insensitive); "
        f"got {label!r}"
    )


# ---------------------------------------------------------------------------
# VAL-EX-007: v1 and v2 target the same skill but differ in failure signatures
# ---------------------------------------------------------------------------


def test_traces_share_skill_id() -> None:
    v1 = _load_trace(TRACE_V1_PATH)
    v2 = _load_trace(TRACE_V2_PATH)
    assert v1.skill_id == v2.skill_id, (
        f"v1 and v2 traces must share skill_id; got {v1.skill_id!r} vs {v2.skill_id!r}"
    )


def test_traces_advertise_distinct_failure_mode_signatures() -> None:
    """v1 and v2 must be designed to produce different failure-mode sets.

    The detection engine lands in a later feature, so we assert the
    intended signatures via the traces' ``metadata.expected_failure_modes``
    field, requiring a non-trivial symmetric difference.
    """

    v1 = _load_trace(TRACE_V1_PATH)
    v2 = _load_trace(TRACE_V2_PATH)
    assert v1.metadata is not None and v2.metadata is not None
    v1_modes = set(v1.metadata.get("expected_failure_modes", []))
    v2_modes = set(v2.metadata.get("expected_failure_modes", []))
    assert v1_modes, "v1 must declare expected_failure_modes in metadata"
    assert v2_modes, "v2 must declare expected_failure_modes in metadata"
    introduced = v2_modes - v1_modes
    resolved = v1_modes - v2_modes
    assert (
        len(introduced) + len(resolved) >= 2
    ), f"introduced={introduced}, resolved={resolved}; expected non-trivial diff"
    assert introduced != resolved, (
        "introduced and resolved must not be identical sets"
    )


# ---------------------------------------------------------------------------
# VAL-EX-008: no secrets or absolute host paths inside trace JSONs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [TRACE_V1_PATH, TRACE_V2_PATH], ids=lambda p: p.name)
def test_trace_contains_no_secret_tokens(path: Path) -> None:
    text = path.read_text()
    for pat in SECRET_PATTERNS:
        match = pat.search(text)
        assert match is None, (
            f"{path.name} matched forbidden secret pattern {pat.pattern!r} "
            f"at {match.group(0)!r}"
        )


@pytest.mark.parametrize("path", [TRACE_V1_PATH, TRACE_V2_PATH], ids=lambda p: p.name)
def test_trace_contains_no_absolute_host_paths(path: Path) -> None:
    text = path.read_text()
    for pat in HOST_PATH_PATTERNS:
        match = pat.search(text)
        assert match is None, (
            f"{path.name} contains absolute host path matching {pat.pattern!r} "
            f"at {match.group(0)!r}"
        )


# ---------------------------------------------------------------------------
# VAL-EX-009: trace JSON round-trips losslessly via the Pydantic model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [TRACE_V1_PATH, TRACE_V2_PATH], ids=lambda p: p.name)
def test_trace_round_trip_via_model_dump_json(path: Path) -> None:
    trace = _load_trace(path)
    rehydrated = Trace.model_validate_json(trace.model_dump_json())
    assert rehydrated.model_dump() == trace.model_dump()
