"""Tests for the TraceCaliper CLI commands.

Covers the VAL-CLI-* assertions from the validation contract using
``typer.testing.CliRunner`` (VAL-CLI-034).

Assertion mapping:
  VAL-CLI-001 – top-level --help lists inspect/compare/report
  VAL-CLI-002 – -h works identically
  VAL-CLI-003 – python -m tracecaliper (tested indirectly via CliRunner)
  VAL-CLI-004 – console script and module equivalence (CliRunner equivalent)
  VAL-CLI-005 – inspect --help documents --suite
  VAL-CLI-006 – compare --help documents --baseline/--candidate/--output
  VAL-CLI-007 – report --help documents --comparison/--output
  VAL-CLI-008 – inspect happy path: suite name, skill id, "simulated"
  VAL-CLI-009 – inspect shows weight overrides
  VAL-CLI-010 – inspect displays simulated-traces disclaimer
  VAL-CLI-011 – inspect fails on missing suite file
  VAL-CLI-012 – inspect fails on malformed YAML
  VAL-CLI-013 – inspect fails on schema-invalid suite
  VAL-CLI-014 – inspect fails when --suite arg is missing
  VAL-CLI-015 – compare happy path: exits 0, writes JSON with required keys
  VAL-CLI-016 – compare stdout contains gate decision label
  VAL-CLI-017 – compare is deterministic (byte-identical JSON)
  VAL-CLI-018 – HOLD/INVESTIGATE does NOT cause non-zero exit
  VAL-CLI-019 – compare fails on missing baseline
  VAL-CLI-020 – compare fails on missing candidate
  VAL-CLI-021 – compare fails on malformed JSON trace
  VAL-CLI-022 – compare fails on schema-invalid trace
  VAL-CLI-023 – compare fails when required args missing
  VAL-CLI-024 – compare fails on unwritable output path
  VAL-CLI-025 – compare creates output parent dir (or errors clearly)
  VAL-CLI-029 – report fails when required args missing
  VAL-CLI-031 – unknown subcommand exits non-zero
  VAL-CLI-032 – unknown flag exits non-zero
  VAL-CLI-034 – CLI smoke tests via CliRunner (all happy paths)
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tracecaliper.cli import app

runner = CliRunner()

# Canonical paths (relative to project root — tests run from there)
SUITE_PATH = "examples/suites/python-api.yml"
BASELINE_PATH = "examples/traces/skill-v1.json"
CANDIDATE_PATH = "examples/traces/skill-v2.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compare_output(result) -> str:
    """Return all captured output from a CliRunner result (stdout + stderr combined)."""
    return result.output or ""


# ---------------------------------------------------------------------------
# Top-level help (VAL-CLI-001, VAL-CLI-002, VAL-CLI-031)
# ---------------------------------------------------------------------------


class TestTopLevel:
    def test_help_lists_all_commands(self):
        """VAL-CLI-001: --help exits 0 and lists inspect, compare, report."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "inspect" in result.output
        assert "compare" in result.output
        assert "report" in result.output

    def test_short_help_flag(self):
        """VAL-CLI-002: -h exits 0 and lists the same commands."""
        result = runner.invoke(app, ["-h"])
        assert result.exit_code == 0
        assert "inspect" in result.output
        assert "compare" in result.output
        assert "report" in result.output

    def test_module_invocation_equivalence(self):
        """VAL-CLI-003 / VAL-CLI-004: CliRunner app is the same object used by __main__."""
        # Both the console-script entry point and ``python -m tracecaliper``
        # import ``tracecaliper.cli:app``, so invoking the app directly via
        # CliRunner exercises exactly the same code path.
        from tracecaliper.cli import app as cli_app
        from tracecaliper import __version__

        result = runner.invoke(cli_app, ["--help"])
        assert result.exit_code == 0
        assert "inspect" in result.output
        assert "compare" in result.output
        assert "report" in result.output
        # __version__ is importable from the same package
        assert isinstance(__version__, str)
        assert __version__

    def test_unknown_subcommand_exits_nonzero(self):
        """VAL-CLI-031: unknown subcommand exits non-zero."""
        result = runner.invoke(app, ["bogus"])
        assert result.exit_code != 0

    def test_unknown_flag_inspect_exits_nonzero(self):
        """VAL-CLI-032: unknown flag on inspect exits non-zero."""
        result = runner.invoke(app, ["inspect", "--not-a-real-flag", "x"])
        assert result.exit_code != 0

    def test_unknown_flag_compare_exits_nonzero(self):
        """VAL-CLI-032: unknown flag on compare exits non-zero."""
        result = runner.invoke(app, ["compare", "--not-a-real-flag", "x"])
        assert result.exit_code != 0

    def test_unknown_flag_report_exits_nonzero(self):
        """VAL-CLI-032: unknown flag on report exits non-zero."""
        result = runner.invoke(app, ["report", "--not-a-real-flag", "x"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# inspect subcommand
# ---------------------------------------------------------------------------


class TestInspect:
    def test_help_documents_suite_flag(self):
        """VAL-CLI-005: inspect --help documents --suite."""
        result = runner.invoke(app, ["inspect", "--help"])
        assert result.exit_code == 0
        assert "--suite" in result.output

    def test_happy_path_exit_zero(self):
        """VAL-CLI-008: inspect happy path exits 0."""
        result = runner.invoke(app, ["inspect", "--suite", SUITE_PATH])
        assert result.exit_code == 0

    def test_happy_path_contains_suite_name(self):
        """VAL-CLI-008: output contains the suite name."""
        result = runner.invoke(app, ["inspect", "--suite", SUITE_PATH])
        assert result.exit_code == 0
        # python-api.yml has name: python-api
        assert "python-api" in result.output.lower()

    def test_happy_path_contains_skill_id(self):
        """VAL-CLI-008: output contains at least one skill identifier."""
        result = runner.invoke(app, ["inspect", "--suite", SUITE_PATH])
        assert result.exit_code == 0
        # The suite has skills python-api-v1 and python-api-v2
        assert "python-api-v" in result.output

    def test_happy_path_shows_simulated_disclaimer(self):
        """VAL-CLI-008 / VAL-CLI-010: output contains 'simulated'."""
        result = runner.invoke(app, ["inspect", "--suite", SUITE_PATH])
        assert result.exit_code == 0
        assert "simulated" in result.output.lower()

    def test_weight_overrides_displayed(self):
        """VAL-CLI-009: resolved weights appear in output with their values."""
        result = runner.invoke(app, ["inspect", "--suite", SUITE_PATH])
        assert result.exit_code == 0
        # python-api.yml has all 7 weights; they should all appear
        assert "tests_passed" in result.output
        assert "security" in result.output
        # At least one numeric weight value visible
        assert "0.25" in result.output or "0.20" in result.output

    def test_simulated_disclaimer_present(self):
        """VAL-CLI-010: simulated-traces disclaimer is in the output."""
        result = runner.invoke(app, ["inspect", "--suite", SUITE_PATH])
        assert "simulated" in result.output.lower()

    def test_missing_suite_file(self):
        """VAL-CLI-011: missing suite exits non-zero; error names the path."""
        result = runner.invoke(app, ["inspect", "--suite", "examples/suites/does-not-exist.yml"])
        assert result.exit_code != 0
        combined = _compare_output(result)
        assert "does-not-exist.yml" in combined

    def test_malformed_yaml(self, tmp_path: Path):
        """VAL-CLI-012: malformed YAML exits non-zero; error mentions yaml/parse."""
        bad = tmp_path / "bad.yml"
        bad.write_text(": : {{{ invalid yaml syntax :::}")
        result = runner.invoke(app, ["inspect", "--suite", str(bad)])
        assert result.exit_code != 0
        combined = _compare_output(result).lower()
        assert any(kw in combined for kw in ["yaml", "parse", "error"])

    def test_schema_invalid_suite(self, tmp_path: Path):
        """VAL-CLI-013: schema-invalid YAML exits non-zero; error mentions validation/field."""
        invalid = tmp_path / "invalid.yml"
        # Valid YAML but missing required 'description' and 'skills' fields
        invalid.write_text("name: test-only\n")
        result = runner.invoke(app, ["inspect", "--suite", str(invalid)])
        assert result.exit_code != 0
        combined = _compare_output(result).lower()
        assert any(kw in combined for kw in ["validation", "error", "description", "skills"])

    def test_missing_suite_arg(self):
        """VAL-CLI-014: inspect with no --suite arg exits non-zero and names --suite."""
        result = runner.invoke(app, ["inspect"])
        assert result.exit_code != 0
        combined = _compare_output(result)
        assert "--suite" in combined


# ---------------------------------------------------------------------------
# compare subcommand
# ---------------------------------------------------------------------------


class TestCompare:
    def test_help_documents_all_flags(self):
        """VAL-CLI-006: compare --help documents --baseline, --candidate, --output."""
        result = runner.invoke(app, ["compare", "--help"])
        assert result.exit_code == 0
        assert "--baseline" in result.output
        assert "--candidate" in result.output
        assert "--output" in result.output

    def test_happy_path_exit_zero(self, tmp_path: Path):
        """VAL-CLI-015 / VAL-CLI-018: compare exits 0 (even HOLD/INVESTIGATE)."""
        out = tmp_path / "comparison.json"
        result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
                "--output", str(out),
            ],
        )
        assert result.exit_code == 0

    def test_happy_path_writes_json_file(self, tmp_path: Path):
        """VAL-CLI-015: compare creates the output JSON file."""
        out = tmp_path / "comparison.json"
        runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
                "--output", str(out),
            ],
        )
        assert out.exists()
        data = json.loads(out.read_text())
        assert isinstance(data, dict)

    def test_happy_path_json_has_required_keys(self, tmp_path: Path):
        """VAL-CLI-015: output JSON contains required top-level keys."""
        out = tmp_path / "comparison.json"
        runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
                "--output", str(out),
            ],
        )
        data = json.loads(out.read_text())
        # Must have a 'deltas' key (satisfies "dimensions"|"deltas")
        assert "deltas" in data
        # Must have a 'gate' key (satisfies "gate"|"decision")
        assert "gate" in data
        # Must have a 'failure_modes' key
        assert "failure_modes" in data

    def test_happy_path_gate_decision_in_stdout(self, tmp_path: Path):
        """VAL-CLI-016: stdout contains gate decision label."""
        out = tmp_path / "comparison.json"
        result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
                "--output", str(out),
            ],
        )
        assert result.exit_code == 0
        assert any(label in result.output for label in ["PASS", "HOLD", "INVESTIGATE"])

    def test_hold_investigate_exits_zero(self, tmp_path: Path):
        """VAL-CLI-018: gate decisions HOLD/INVESTIGATE still exit 0."""
        out = tmp_path / "comparison.json"
        result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
                "--output", str(out),
            ],
        )
        # Exit code must be 0 regardless of the gate outcome
        assert result.exit_code == 0
        # Verify the gate decision is recorded in the JSON
        data = json.loads(out.read_text())
        assert data["gate"]["decision"] in {"PASS", "HOLD", "INVESTIGATE"}

    def test_deterministic_byte_identical(self, tmp_path: Path):
        """VAL-CLI-017: two runs produce byte-identical JSON output."""
        out1 = tmp_path / "cmp1.json"
        out2 = tmp_path / "cmp2.json"
        args = [
            "compare",
            "--baseline", BASELINE_PATH,
            "--candidate", CANDIDATE_PATH,
        ]
        runner.invoke(app, args + ["--output", str(out1)])
        runner.invoke(app, args + ["--output", str(out2)])
        assert out1.read_bytes() == out2.read_bytes(), (
            "Two runs of `compare` produced different output bytes"
        )

    def test_creates_parent_directory(self, tmp_path: Path):
        """VAL-CLI-025 option (a): output parent dir is created automatically."""
        out = tmp_path / "new_subdir" / "deeper" / "comparison.json"
        result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
                "--output", str(out),
            ],
        )
        assert result.exit_code == 0
        assert out.exists()

    def test_missing_baseline(self, tmp_path: Path):
        """VAL-CLI-019: missing baseline exits non-zero; error names the path."""
        result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", "does-not-exist.json",
                "--candidate", CANDIDATE_PATH,
                "--output", str(tmp_path / "out.json"),
            ],
        )
        assert result.exit_code != 0
        combined = _compare_output(result)
        assert "does-not-exist.json" in combined

    def test_missing_candidate(self, tmp_path: Path):
        """VAL-CLI-020: missing candidate exits non-zero; error names the path."""
        result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", "does-not-exist.json",
                "--output", str(tmp_path / "out.json"),
            ],
        )
        assert result.exit_code != 0
        combined = _compare_output(result)
        assert "does-not-exist.json" in combined

    def test_malformed_json_baseline(self, tmp_path: Path):
        """VAL-CLI-021: malformed JSON baseline exits non-zero; error mentions json/parse."""
        bad = tmp_path / "bad.json"
        bad.write_text("not valid json {{{")
        result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", str(bad),
                "--candidate", CANDIDATE_PATH,
                "--output", str(tmp_path / "out.json"),
            ],
        )
        assert result.exit_code != 0
        combined = _compare_output(result).lower()
        assert any(kw in combined for kw in ["json", "parse", "error"])

    def test_malformed_json_candidate(self, tmp_path: Path):
        """VAL-CLI-021: malformed JSON candidate exits non-zero."""
        bad = tmp_path / "bad.json"
        bad.write_text("{broken json")
        result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", str(bad),
                "--output", str(tmp_path / "out.json"),
            ],
        )
        assert result.exit_code != 0
        combined = _compare_output(result).lower()
        assert any(kw in combined for kw in ["json", "parse", "error"])

    def test_schema_invalid_trace_baseline(self, tmp_path: Path):
        """VAL-CLI-022: schema-invalid baseline trace exits non-zero."""
        bad = tmp_path / "invalid_trace.json"
        # Valid JSON but missing required trace fields (skill_id, simulated, etc.)
        bad.write_text('{"not_a_trace": true}')
        result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", str(bad),
                "--candidate", CANDIDATE_PATH,
                "--output", str(tmp_path / "out.json"),
            ],
        )
        assert result.exit_code != 0
        combined = _compare_output(result).lower()
        assert any(kw in combined for kw in ["validation", "schema", "error", "skill_id", "steps"])

    def test_missing_required_args(self):
        """VAL-CLI-023: compare with no args exits non-zero; names a required option."""
        result = runner.invoke(app, ["compare"])
        assert result.exit_code != 0
        combined = _compare_output(result)
        assert any(opt in combined for opt in ["--baseline", "--candidate", "--output"])

    def test_missing_baseline_arg(self, tmp_path: Path):
        """VAL-CLI-023: omitting --baseline exits non-zero."""
        result = runner.invoke(
            app,
            [
                "compare",
                "--candidate", CANDIDATE_PATH,
                "--output", str(tmp_path / "out.json"),
            ],
        )
        assert result.exit_code != 0

    def test_missing_candidate_arg(self, tmp_path: Path):
        """VAL-CLI-023: omitting --candidate exits non-zero."""
        result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--output", str(tmp_path / "out.json"),
            ],
        )
        assert result.exit_code != 0

    def test_missing_output_arg(self):
        """VAL-CLI-023: omitting --output exits non-zero."""
        result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
            ],
        )
        assert result.exit_code != 0

    def test_unwritable_output_path(self, tmp_path: Path):
        """VAL-CLI-024: unwritable output exits non-zero with a clear error."""
        # Create a read-only directory
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # no write permission

        out = readonly_dir / "comparison.json"
        result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
                "--output", str(out),
            ],
        )
        # Restore permissions so pytest can clean up tmp_path
        readonly_dir.chmod(stat.S_IRWXU)

        assert result.exit_code != 0
        combined = _compare_output(result).lower()
        assert any(kw in combined for kw in ["permission", "output", "cannot", "error"])

    def test_json_bundle_structure(self, tmp_path: Path):
        """VAL-CLI-015: bundle JSON has correct nested structure."""
        out = tmp_path / "comparison.json"
        runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
                "--output", str(out),
            ],
        )
        data = json.loads(out.read_text())

        # deltas section
        assert "dimensions" in data["deltas"]
        assert "aggregate" in data["deltas"]

        # failure_modes section
        assert "introduced" in data["failure_modes"]
        assert "resolved" in data["failure_modes"]
        assert "persistent" in data["failure_modes"]

        # gate section
        assert "decision" in data["gate"]
        assert data["gate"]["decision"] in {"PASS", "HOLD", "INVESTIGATE"}
        assert "rationale" in data["gate"]
        assert len(data["gate"]["rationale"]) >= 1

    def test_comparison_section_present(self, tmp_path: Path):
        """VAL-CLI-015: bundle contains full comparison data."""
        out = tmp_path / "comparison.json"
        runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
                "--output", str(out),
            ],
        )
        data = json.loads(out.read_text())
        assert "comparison" in data
        cmp_data = data["comparison"]
        assert "aggregate_delta" in cmp_data
        assert "dimension_deltas" in cmp_data


# ---------------------------------------------------------------------------
# report subcommand (stub — full implementation in skill-delta-report feature)
# ---------------------------------------------------------------------------


class TestReport:
    def test_help_documents_comparison_flag(self):
        """VAL-CLI-007: report --help documents --comparison."""
        result = runner.invoke(app, ["report", "--help"])
        assert result.exit_code == 0
        assert "--comparison" in result.output

    def test_help_documents_output_flag(self):
        """VAL-CLI-007: report --help documents --output."""
        result = runner.invoke(app, ["report", "--help"])
        assert result.exit_code == 0
        assert "--output" in result.output

    def test_help_exits_zero(self):
        """VAL-CLI-007: report --help exits 0."""
        result = runner.invoke(app, ["report", "--help"])
        assert result.exit_code == 0

    def test_missing_required_args(self):
        """VAL-CLI-029: report with no args exits non-zero."""
        result = runner.invoke(app, ["report"])
        assert result.exit_code != 0
        combined = _compare_output(result)
        assert any(opt in combined for opt in ["--comparison", "--output"])

    def test_missing_comparison_arg(self, tmp_path: Path):
        """VAL-CLI-029: omitting --comparison exits non-zero."""
        result = runner.invoke(
            app,
            ["report", "--output", str(tmp_path / "report.md")],
        )
        assert result.exit_code != 0

    def test_missing_output_arg(self):
        """VAL-CLI-029: omitting --output exits non-zero."""
        result = runner.invoke(
            app,
            ["report", "--comparison", "reports/comparison.json"],
        )
        assert result.exit_code != 0

    def test_stub_exits_nonzero_with_valid_args(self, tmp_path: Path):
        """Report stub exits non-zero (not implemented yet)."""
        result = runner.invoke(
            app,
            [
                "report",
                "--comparison", "reports/comparison.json",
                "--output", str(tmp_path / "report.md"),
            ],
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# VAL-CLI-034: end-to-end smoke test via CliRunner
# ---------------------------------------------------------------------------


class TestSmoke:
    """End-to-end smoke tests using CliRunner (VAL-CLI-034)."""

    def test_inspect_smoke(self):
        """Smoke: inspect runs without exception on the bundled example suite."""
        result = runner.invoke(app, ["inspect", "--suite", SUITE_PATH])
        assert result.exit_code == 0
        assert result.exception is None

    def test_compare_smoke(self, tmp_path: Path):
        """Smoke: compare runs without exception on the bundled example traces."""
        out = tmp_path / "comparison.json"
        result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
                "--output", str(out),
            ],
        )
        assert result.exit_code == 0
        assert result.exception is None
        assert out.exists()

    def test_report_stub_smoke(self, tmp_path: Path):
        """Smoke: report stub runs without unexpected exception."""
        result = runner.invoke(
            app,
            [
                "report",
                "--comparison", "reports/comparison.json",
                "--output", str(tmp_path / "report.md"),
            ],
        )
        # Stub exits non-zero — that's expected
        assert result.exit_code != 0
        # Should not be an unhandled exception (typer.Exit is expected)
        # result.exception can be SystemExit(1) which is from typer.Exit
        if result.exception is not None:
            assert isinstance(result.exception, SystemExit)

    def test_full_compare_pipeline_output(self, tmp_path: Path):
        """Smoke: compare produces a fully valid JSON bundle."""
        out = tmp_path / "comparison.json"
        result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
                "--output", str(out),
            ],
        )
        assert result.exit_code == 0

        data = json.loads(out.read_text())

        # All top-level sections present
        assert "comparison" in data
        assert "deltas" in data
        assert "failure_modes" in data
        assert "gate" in data

        # Gate is valid
        assert data["gate"]["decision"] in {"PASS", "HOLD", "INVESTIGATE"}

        # Comparison has all 7 dimension deltas
        from tracecaliper.models import DIMENSION_NAMES
        dim_deltas = data["comparison"]["dimension_deltas"]
        for name in DIMENSION_NAMES:
            assert name in dim_deltas, f"Missing dimension delta: {name}"

        # Output file contains gate decision label in stdout
        decision = data["gate"]["decision"]
        assert decision in result.output

    def test_no_traceback_in_error_output(self, tmp_path: Path):
        """Error cases emit clean messages without raw Python tracebacks."""
        # Missing baseline file
        result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", "nonexistent.json",
                "--candidate", CANDIDATE_PATH,
                "--output", str(tmp_path / "out.json"),
            ],
        )
        combined = _compare_output(result)
        # Should not have Traceback header
        assert "Traceback (most recent call last)" not in combined

    def test_inspect_no_traceback_on_missing_file(self):
        """Inspect error on missing file is clean, no traceback."""
        result = runner.invoke(app, ["inspect", "--suite", "missing.yml"])
        combined = _compare_output(result)
        assert "Traceback (most recent call last)" not in combined
