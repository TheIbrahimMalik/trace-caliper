"""Tests for tracecaliper.loaders: load_suite and load_trace.

Covers happy paths (real example files), missing-file errors, malformed
YAML/JSON parse errors, and schema-invalid content errors.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from tracecaliper.loaders import load_suite, load_trace
from tracecaliper.models import Suite, Trace


REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = REPO_ROOT / "examples" / "suites" / "python-api.yml"
TRACE_V1_PATH = REPO_ROOT / "examples" / "traces" / "skill-v1.json"
TRACE_V2_PATH = REPO_ROOT / "examples" / "traces" / "skill-v2.json"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_load_suite_happy_path() -> None:
    """load_suite returns a valid Suite from the bundled example file."""
    suite = load_suite(SUITE_PATH)
    assert isinstance(suite, Suite)
    assert suite.name == "python-api"
    assert suite.description
    assert len(suite.skills) == 2
    assert suite.weights


def test_load_suite_happy_path_str_path() -> None:
    """load_suite accepts a plain str as well as a Path."""
    suite = load_suite(str(SUITE_PATH))
    assert isinstance(suite, Suite)
    assert suite.name == "python-api"


def test_load_trace_happy_path_v1() -> None:
    """load_trace returns a valid Trace from the bundled skill-v1 example."""
    trace = load_trace(TRACE_V1_PATH)
    assert isinstance(trace, Trace)
    assert trace.skill_id == "python-api"
    assert trace.simulated is True
    assert "simulated" in trace.label.lower()
    assert len(trace.steps) > 0


def test_load_trace_happy_path_v2() -> None:
    """load_trace returns a valid Trace from the bundled skill-v2 example."""
    trace = load_trace(TRACE_V2_PATH)
    assert isinstance(trace, Trace)
    assert trace.skill_id == "python-api"
    assert trace.simulated is True


def test_load_trace_happy_path_str_path() -> None:
    """load_trace accepts a plain str as well as a Path."""
    trace = load_trace(str(TRACE_V1_PATH))
    assert isinstance(trace, Trace)


# ---------------------------------------------------------------------------
# Missing-file errors
# ---------------------------------------------------------------------------


def test_load_suite_missing_file(tmp_path: Path) -> None:
    """load_suite raises FileNotFoundError whose message contains the path."""
    missing = tmp_path / "no-such-suite.yml"
    with pytest.raises(FileNotFoundError) as exc_info:
        load_suite(missing)
    assert str(missing) in str(exc_info.value)


def test_load_trace_missing_file(tmp_path: Path) -> None:
    """load_trace raises FileNotFoundError whose message contains the path."""
    missing = tmp_path / "no-such-trace.json"
    with pytest.raises(FileNotFoundError) as exc_info:
        load_trace(missing)
    assert str(missing) in str(exc_info.value)


def test_load_suite_missing_file_str_path() -> None:
    """load_suite embeds the path string in the error when given a str."""
    missing_str = "/tmp/does-not-exist-tracecaliper-suite.yml"
    with pytest.raises(FileNotFoundError) as exc_info:
        load_suite(missing_str)
    assert missing_str in str(exc_info.value)


def test_load_trace_missing_file_str_path() -> None:
    """load_trace embeds the path string in the error when given a str."""
    missing_str = "/tmp/does-not-exist-tracecaliper-trace.json"
    with pytest.raises(FileNotFoundError) as exc_info:
        load_trace(missing_str)
    assert missing_str in str(exc_info.value)


# ---------------------------------------------------------------------------
# Parse failures
# ---------------------------------------------------------------------------


def test_load_suite_malformed_yaml(tmp_path: Path) -> None:
    """load_suite raises yaml.YAMLError on malformed YAML content."""
    bad_yaml = tmp_path / "bad.yml"
    bad_yaml.write_text("key: [unclosed bracket\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_suite(bad_yaml)


def test_load_suite_malformed_yaml_tabs(tmp_path: Path) -> None:
    """load_suite raises yaml.YAMLError on YAML that uses tab indentation."""
    bad_yaml = tmp_path / "tabs.yml"
    bad_yaml.write_text("name: test\n\tkey: bad_tab_indent\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_suite(bad_yaml)


def test_load_trace_malformed_json(tmp_path: Path) -> None:
    """load_trace raises json.JSONDecodeError on malformed JSON content."""
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{unclosed: json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_trace(bad_json)


def test_load_trace_malformed_json_trailing_comma(tmp_path: Path) -> None:
    """load_trace raises json.JSONDecodeError on invalid JSON with trailing comma."""
    bad_json = tmp_path / "trailing.json"
    bad_json.write_text('{"key": "value",}', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_trace(bad_json)


# ---------------------------------------------------------------------------
# Schema-invalid content
# ---------------------------------------------------------------------------


def test_load_suite_schema_invalid_missing_required_field(tmp_path: Path) -> None:
    """load_suite raises ValidationError when required fields are absent."""
    # Missing 'description' and 'skills'
    bad_suite = tmp_path / "invalid-suite.yml"
    bad_suite.write_text("name: broken-suite\n", encoding="utf-8")
    with pytest.raises(ValidationError) as exc_info:
        load_suite(bad_suite)
    error_str = str(exc_info.value)
    # Pydantic names the offending field in its error output
    assert "skills" in error_str or "description" in error_str


def test_load_suite_schema_invalid_negative_weight(tmp_path: Path) -> None:
    """load_suite raises ValidationError for negative dimension weights."""
    content = """
name: bad-suite
description: suite with negative weight
weights:
  tests_passed: -0.5
skills: []
"""
    bad_suite = tmp_path / "neg-weight.yml"
    bad_suite.write_text(content, encoding="utf-8")
    with pytest.raises(ValidationError) as exc_info:
        load_suite(bad_suite)
    assert "tests_passed" in str(exc_info.value) or "negative" in str(exc_info.value).lower()


def test_load_suite_schema_invalid_unknown_weight_key(tmp_path: Path) -> None:
    """load_suite raises ValidationError for unknown dimension weight keys."""
    content = """
name: bad-suite
description: suite with unknown dimension
weights:
  not_a_dimension: 0.5
skills: []
"""
    bad_suite = tmp_path / "unknown-dim.yml"
    bad_suite.write_text(content, encoding="utf-8")
    with pytest.raises(ValidationError) as exc_info:
        load_suite(bad_suite)
    assert "not_a_dimension" in str(exc_info.value)


def test_load_trace_schema_invalid_missing_required_field(tmp_path: Path) -> None:
    """load_trace raises ValidationError when required fields are absent."""
    # Missing 'steps', 'simulated', 'label'
    bad_trace = tmp_path / "invalid-trace.json"
    bad_trace.write_text(json.dumps({"skill_id": "test-skill"}), encoding="utf-8")
    with pytest.raises(ValidationError) as exc_info:
        load_trace(bad_trace)
    error_str = str(exc_info.value)
    assert "steps" in error_str or "simulated" in error_str or "label" in error_str


def test_load_trace_schema_invalid_label_missing_simulated(tmp_path: Path) -> None:
    """load_trace raises ValidationError when label does not contain 'simulated'."""
    bad_trace = tmp_path / "bad-label.json"
    data = {
        "skill_id": "test-skill",
        "simulated": True,
        "label": "production trace",
        "steps": [
            {"index": 1, "action": "read", "files_touched": [], "evidence": "read task"}
        ],
    }
    bad_trace.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError) as exc_info:
        load_trace(bad_trace)
    assert "simulated" in str(exc_info.value).lower()


def test_load_trace_schema_invalid_duplicate_step_indices(tmp_path: Path) -> None:
    """load_trace raises ValidationError for duplicate step indices."""
    bad_trace = tmp_path / "dup-indices.json"
    data = {
        "skill_id": "test-skill",
        "simulated": True,
        "label": "simulated test trace",
        "steps": [
            {"index": 1, "action": "read", "files_touched": [], "evidence": "step 1"},
            {"index": 1, "action": "write", "files_touched": [], "evidence": "step 1 again"},
        ],
    }
    bad_trace.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError) as exc_info:
        load_trace(bad_trace)
    assert "duplicate" in str(exc_info.value).lower() or "index" in str(exc_info.value).lower()


def test_load_trace_schema_invalid_non_monotonic_indices(tmp_path: Path) -> None:
    """load_trace raises ValidationError for non-monotonically-increasing step indices."""
    bad_trace = tmp_path / "non-mono.json"
    data = {
        "skill_id": "test-skill",
        "simulated": True,
        "label": "simulated test trace",
        "steps": [
            {"index": 3, "action": "read", "files_touched": [], "evidence": "step 3"},
            {"index": 1, "action": "write", "files_touched": [], "evidence": "step 1"},
        ],
    }
    bad_trace.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError) as exc_info:
        load_trace(bad_trace)
    assert "increasing" in str(exc_info.value).lower() or "index" in str(exc_info.value).lower()
