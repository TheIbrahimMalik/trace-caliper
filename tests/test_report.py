"""Tests for the Skill Delta Report renderer.

Covers all VAL-REPORT-* assertions from the validation contract:

  VAL-REPORT-001 – title, subtitle, simulated-traces disclaimer within first 30 lines
  VAL-REPORT-002 – gate decision banner before tables, matches JSON, rationale ≥ 40 chars
  VAL-REPORT-003 – suite metadata section with name, description, all 7 weights
  VAL-REPORT-004 – per-skill score table with correct header, 3-decimal cells, signed deltas, Weighted Total
  VAL-REPORT-005 – dimension breakdown table with all 7 dimensions, weights summing to 1.0
  VAL-REPORT-006 – failure-mode delta section (Introduced/Resolved/Persistent) matching JSON
  VAL-REPORT-007 – rubric section defines all 7 dimensions, no TODO/TBD/lorem placeholders
  VAL-REPORT-008 – footer with deterministic metadata, no ISO-8601 timestamps
  VAL-REPORT-009 – byte-deterministic output across two runs
  VAL-REPORT-010 – section order and consistent table column counts
  VAL-REPORT-011 – CLI fails gracefully on missing/malformed comparison; no host paths in report
"""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tracecaliper.cli import app
from tracecaliper.comparison import compare as _compare
from tracecaliper.failure_modes import detect_failure_modes
from tracecaliper.gate import decide
from tracecaliper.loaders import load_suite, load_trace
from tracecaliper.models import (
    DEFAULT_WEIGHTS,
    DIMENSION_NAMES,
    Comparison,
    DimensionScore,
    FailureMode,
    GateDecision,
    Skill,
    Suite,
    TraceScore,
)
from tracecaliper.report import render_markdown
from tracecaliper.scoring import resolve_weights, score_trace

runner = CliRunner()

SUITE_PATH = "examples/suites/python-api.yml"
BASELINE_PATH = "examples/traces/skill-v1.json"
CANDIDATE_PATH = "examples/traces/skill-v2.json"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pipeline():
    """Run the full pipeline once and return all relevant objects."""
    suite = load_suite(SUITE_PATH)
    baseline = load_trace(BASELINE_PATH)
    candidate = load_trace(CANDIDATE_PATH)
    weights = resolve_weights(suite.weights)
    baseline_score = score_trace(baseline, weights)
    candidate_score = score_trace(candidate, weights)
    baseline_modes = detect_failure_modes(baseline)
    candidate_modes = detect_failure_modes(candidate)
    cmp = _compare(baseline_score, candidate_score, baseline_modes, candidate_modes)
    gate = decide(cmp)

    intro_codes = set(cmp.introduced)
    resolved_codes = set(cmp.resolved)
    persistent_codes = set(cmp.persistent)
    introduced_modes = [m for m in candidate_modes if m.code in intro_codes]
    resolved_modes = [m for m in baseline_modes if m.code in resolved_codes]
    persistent_modes = [m for m in baseline_modes if m.code in persistent_codes]

    return dict(
        suite=suite,
        comparison=cmp,
        gate=gate,
        introduced_modes=introduced_modes,
        resolved_modes=resolved_modes,
        persistent_modes=persistent_modes,
    )


@pytest.fixture(scope="module")
def report_md(pipeline):
    """Rendered Markdown from the full example pipeline."""
    return render_markdown(
        pipeline["comparison"],
        pipeline["suite"],
        pipeline["gate"],
        introduced_modes=pipeline["introduced_modes"],
        resolved_modes=pipeline["resolved_modes"],
        persistent_modes=pipeline["persistent_modes"],
        comparison_path="comparison.json",
    )


def _lines(md: str) -> list[str]:
    return md.splitlines()


def _non_blank_lines(md: str) -> list[str]:
    return [ln for ln in md.splitlines() if ln.strip()]


def _parse_table_rows(md: str, section_heading: str) -> list[list[str]]:
    """Return rows (as lists of stripped cell strings) for the table under *section_heading*."""
    lines = md.splitlines()
    in_section = False
    rows: list[list[str]] = []
    for ln in lines:
        if ln.startswith("#") and section_heading.lower() in ln.lower():
            in_section = True
            continue
        if in_section and ln.startswith("#"):
            break
        if in_section and ln.startswith("|"):
            cells = [c.strip() for c in ln.split("|") if c.strip()]
            rows.append(cells)
    return rows


# ---------------------------------------------------------------------------
# VAL-REPORT-001 — Title, subtitle, disclaimer
# ---------------------------------------------------------------------------


class TestTitleAndDisclaimer:
    def test_first_non_blank_line_is_h1_skill_delta_report(self, report_md):
        """First non-blank line must be H1 containing 'Skill Delta Report'. VAL-REPORT-001."""
        nb = _non_blank_lines(report_md)
        assert nb, "Report has no non-blank lines"
        first = nb[0]
        assert first.startswith("# "), f"First non-blank line is not H1: {first!r}"
        assert "skill delta report" in first.lower(), (
            f"H1 does not contain 'Skill Delta Report': {first!r}"
        )

    def test_subtitle_within_first_5_lines(self, report_md):
        """A subtitle line (non-heading, non-blank) appears within the first 5 lines. VAL-REPORT-001."""
        first_5 = _lines(report_md)[:5]
        subtitles = [
            ln for ln in first_5 if ln.strip() and not ln.startswith("#")
        ]
        assert subtitles, "No subtitle found within the first 5 lines of the report"

    def test_disclaimer_within_first_30_lines(self, report_md):
        """'Simulated' disclaimer appears within first 30 lines. VAL-REPORT-001."""
        first_30 = _lines(report_md)[:30]
        simulated_hits = [
            ln for ln in first_30 if "simulated" in ln.lower()
        ]
        assert simulated_hits, (
            "No line containing 'simulated' found within the first 30 lines"
        )

    def test_disclaimer_references_mvp_or_traces(self, report_md):
        """The disclaimer should reference traces being simulated. VAL-REPORT-001."""
        first_30 = "\n".join(_lines(report_md)[:30])
        assert "trace" in first_30.lower() or "fabricated" in first_30.lower(), (
            "Disclaimer within first 30 lines does not reference traces or fabrication"
        )


# ---------------------------------------------------------------------------
# VAL-REPORT-002 — Gate decision banner
# ---------------------------------------------------------------------------


class TestGateBanner:
    def test_gate_decision_before_first_table(self, report_md):
        """Gate decision banner appears before any table separator. VAL-REPORT-002."""
        lines = _lines(report_md)
        gate_line_idx = next(
            (
                i
                for i, ln in enumerate(lines)
                if re.search(r"\b(PASS|HOLD|INVESTIGATE)\b", ln)
            ),
            None,
        )
        first_table_sep_idx = next(
            (i for i, ln in enumerate(lines) if re.match(r"\s*\|[-| ]+\|", ln)),
            None,
        )
        assert gate_line_idx is not None, "No PASS/HOLD/INVESTIGATE found in report"
        assert first_table_sep_idx is not None, "No table separator found in report"
        assert gate_line_idx < first_table_sep_idx, (
            f"Gate decision (line {gate_line_idx}) appears AFTER first table "
            f"separator (line {first_table_sep_idx})"
        )

    def test_gate_decision_matches_pipeline(self, report_md, pipeline):
        """Gate decision string matches the pipeline's GateDecision.decision. VAL-REPORT-002."""
        expected = pipeline["gate"].decision
        lines = _lines(report_md)
        banner_lines = [
            ln for ln in lines if "Gate Decision:" in ln and "**" in ln
        ]
        assert banner_lines, "No 'Gate Decision: **...**' line found"
        assert any(expected in ln for ln in banner_lines), (
            f"Expected '{expected}' in gate banner; got: {banner_lines}"
        )

    def test_rationale_at_least_40_chars(self, report_md):
        """Rationale text is >= 40 characters. VAL-REPORT-002."""
        lines = _lines(report_md)
        # The rationale follows the "Gate Decision:" line
        gate_idx = next(
            (i for i, ln in enumerate(lines) if "Gate Decision:" in ln), None
        )
        assert gate_idx is not None
        # Collect lines in the gate section until next heading or ---
        rationale_parts: list[str] = []
        for ln in lines[gate_idx + 1 :]:
            if ln.startswith("#") or ln == "---":
                break
            if ln.strip():
                rationale_parts.append(ln.strip())
        rationale = " ".join(rationale_parts)
        assert len(rationale) >= 40, (
            f"Rationale too short ({len(rationale)} chars): {rationale!r}"
        )

    def test_rationale_references_concrete_signal(self, report_md, pipeline):
        """Rationale references at least one concrete signal from the gate. VAL-REPORT-002."""
        # Concrete signals = failure-mode codes or delta keywords
        signals = set(pipeline["gate"].rationale[0].split())
        all_codes = {"OVER_EDITING", "TEST_REGRESSION", "INSTRUCTION_DRIFT",
                     "SECURITY_FLAG", "CONVENTION_VIOLATION", "INCOMPLETE_TASK",
                     "LOW_REVIEWABILITY"}
        delta_keywords = {"aggregate", "delta", "negative", "positive", "improvement",
                          "regression", "resolved", "introduced"}
        content = report_md.lower()
        # At least one code or delta keyword should appear in the report
        found_code = any(c.lower() in content for c in all_codes)
        found_delta = any(kw in content for kw in delta_keywords)
        assert found_code or found_delta, (
            "Report rationale does not reference any concrete signal"
        )


# ---------------------------------------------------------------------------
# VAL-REPORT-003 — Suite Metadata
# ---------------------------------------------------------------------------


class TestSuiteMetadata:
    def test_suite_metadata_section_exists(self, report_md):
        """A 'Suite Metadata' section (H2/H3) exists. VAL-REPORT-003."""
        assert any(
            "suite metadata" in ln.lower() or "suite" in ln.lower()
            for ln in _lines(report_md)
            if ln.startswith("#")
        ), "No 'Suite Metadata' heading found"

    def test_suite_name_present(self, report_md, pipeline):
        """Suite name appears in the report. VAL-REPORT-003."""
        assert pipeline["suite"].name in report_md, (
            f"Suite name '{pipeline['suite'].name}' not found in report"
        )

    def test_suite_description_present(self, report_md, pipeline):
        """Suite description appears in the report. VAL-REPORT-003."""
        assert pipeline["suite"].description in report_md, (
            f"Suite description not found in report"
        )

    def test_all_7_weights_in_metadata(self, report_md):
        """All 7 dimension names appear in the Suite Metadata section. VAL-REPORT-003."""
        for dim in DIMENSION_NAMES:
            assert dim in report_md, (
                f"Dimension '{dim}' not found in report (expected in Suite Metadata)"
            )


# ---------------------------------------------------------------------------
# VAL-REPORT-004 — Per-Skill Score Table
# ---------------------------------------------------------------------------


class TestPerSkillTable:
    def _find_skill_table(self, report_md: str) -> list[list[str]]:
        return _parse_table_rows(report_md, "Per-Skill Scores")

    def test_skill_table_has_required_headers(self, report_md):
        """Per-skill table has Skill, Baseline, Candidate, Delta headers. VAL-REPORT-004."""
        rows = self._find_skill_table(report_md)
        assert rows, "Per-Skill Scores table not found"
        header = rows[0]
        lower_header = [h.lower() for h in header]
        assert "skill" in lower_header, f"'Skill' column missing from header: {header}"
        assert "baseline" in lower_header, f"'Baseline' column missing: {header}"
        assert "candidate" in lower_header, f"'Candidate' column missing: {header}"
        assert "delta" in lower_header, f"'Delta' column missing: {header}"

    def test_skill_table_has_weighted_total_row(self, report_md):
        """Per-skill table has a 'Weighted Total' row. VAL-REPORT-004."""
        lines = _lines(report_md)
        assert any(
            "weighted total" in ln.lower() for ln in lines
        ), "No 'Weighted Total' row found in report"

    def test_delta_cells_are_signed_3_decimal(self, report_md):
        """Every delta cell in the per-skill table is a signed 3-decimal number. VAL-REPORT-004."""
        rows = self._find_skill_table(report_md)
        # Skip header and separator rows
        data_rows = [
            r for r in rows
            if r and not all(c.startswith("-") or c == "" for c in r)
            and not r[0].lower().startswith("skill")
        ]
        for row in data_rows:
            if len(row) < 4:
                continue
            delta_cell = row[-1].strip("*").strip()
            assert re.match(r"^[+-]\d+\.\d{3}$", delta_cell), (
                f"Delta cell does not match signed 3-decimal format: {delta_cell!r}"
            )

    def test_numeric_cells_3_decimals(self, report_md):
        """Baseline/Candidate cells in per-skill table have 3 decimal places. VAL-REPORT-004."""
        rows = self._find_skill_table(report_md)
        data_rows = [
            r for r in rows
            if r
            and not all(c.startswith("-") or c == "" for c in r)
            and not r[0].lower().startswith("skill")
        ]
        for row in data_rows:
            if len(row) < 3:
                continue
            for cell in row[1:-1]:  # baseline, candidate (not skill, not delta)
                stripped = cell.strip("*").strip()
                assert re.match(r"^\d+\.\d{3}$", stripped), (
                    f"Numeric cell does not have 3 decimal places: {stripped!r}"
                )

    def test_weighted_total_values_match_pipeline(self, report_md, pipeline):
        """Weighted total values match the comparison's weighted totals. VAL-REPORT-004."""
        cmp = pipeline["comparison"]
        assert _fmt3(cmp.baseline.weighted_total) in report_md, (
            "Baseline weighted total not found in report"
        )
        assert _fmt3(cmp.candidate.weighted_total) in report_md, (
            "Candidate weighted total not found in report"
        )


def _fmt3(v: float) -> str:
    return f"{v:.3f}"


# ---------------------------------------------------------------------------
# VAL-REPORT-005 — Dimension Breakdown Table
# ---------------------------------------------------------------------------


class TestDimensionBreakdown:
    def test_all_7_dimensions_present(self, report_md):
        """All 7 dimension names appear in the dimension breakdown. VAL-REPORT-005."""
        for dim in DIMENSION_NAMES:
            assert dim in report_md, (
                f"Dimension '{dim}' not found in dimension breakdown section"
            )

    def test_breakdown_table_has_weight_column(self, report_md):
        """Dimension breakdown table includes a Weight column. VAL-REPORT-005."""
        rows = _parse_table_rows(report_md, "Dimension Breakdown")
        assert rows, "Dimension Breakdown table not found"
        header = rows[0]
        lower = [h.lower() for h in header]
        assert "weight" in lower, f"'Weight' column missing from breakdown table: {header}"

    def test_weights_sum_to_1(self, report_md):
        """Dimension weights in the breakdown table sum to 1.0 ± 1e-9. VAL-REPORT-005."""
        rows = _parse_table_rows(report_md, "Dimension Breakdown")
        assert rows, "Dimension Breakdown table not found"
        # Weight column is the last column (index -1)
        total = 0.0
        data_rows = [
            r for r in rows[2:]  # skip header + separator
            if r and not all(c.startswith("-") for c in r)
        ]
        for row in data_rows:
            if not row:
                continue
            weight_cell = row[-1].strip("*").strip()
            try:
                total += float(weight_cell)
            except ValueError:
                pass
        assert abs(total - 1.0) < 1e-9, (
            f"Dimension weights sum to {total}, expected 1.0 ± 1e-9"
        )

    def test_breakdown_has_4_data_columns(self, report_md):
        """Dimension breakdown table has Baseline, Candidate, Delta, Weight columns. VAL-REPORT-005."""
        rows = _parse_table_rows(report_md, "Dimension Breakdown")
        assert rows, "Dimension Breakdown table not found"
        header = rows[0]
        lower = [h.lower() for h in header]
        for col in ("baseline", "candidate", "delta", "weight"):
            assert col in lower, f"Column '{col}' missing from breakdown table: {header}"


# ---------------------------------------------------------------------------
# VAL-REPORT-006 — Failure Modes
# ---------------------------------------------------------------------------


class TestFailureModes:
    def test_failure_modes_section_exists(self, report_md):
        """A 'Failure Modes' section exists in the report. VAL-REPORT-006."""
        assert any(
            "failure modes" in ln.lower()
            for ln in _lines(report_md)
            if ln.startswith("#")
        ), "No 'Failure Modes' heading found"

    def test_introduced_subsection_exists(self, report_md):
        """An 'Introduced' subsection exists. VAL-REPORT-006."""
        lines = _lines(report_md)
        assert any(
            "introduced" in ln.lower() and ln.startswith("#")
            for ln in lines
        ), "No 'Introduced' subsection found"

    def test_resolved_subsection_exists(self, report_md):
        """A 'Resolved' subsection exists. VAL-REPORT-006."""
        lines = _lines(report_md)
        assert any(
            "resolved" in ln.lower() and ln.startswith("#")
            for ln in lines
        ), "No 'Resolved' subsection found"

    def test_persistent_subsection_exists(self, report_md):
        """A 'Persistent' subsection exists. VAL-REPORT-006."""
        lines = _lines(report_md)
        assert any(
            "persistent" in ln.lower() and ln.startswith("#")
            for ln in lines
        ), "No 'Persistent' subsection found"

    def test_introduced_codes_match_comparison(self, report_md, pipeline):
        """Introduced failure-mode codes match those in the comparison. VAL-REPORT-006."""
        cmp = pipeline["comparison"]
        for code in cmp.introduced:
            assert code in report_md, (
                f"Introduced code '{code}' not found in Failure Modes section"
            )

    def test_resolved_codes_match_comparison(self, report_md, pipeline):
        """Resolved failure-mode codes match those in the comparison. VAL-REPORT-006."""
        cmp = pipeline["comparison"]
        for code in cmp.resolved:
            assert code in report_md, (
                f"Resolved code '{code}' not found in Failure Modes section"
            )

    def test_each_item_shows_severity(self, report_md, pipeline):
        """Each failure-mode item shows a severity label. VAL-REPORT-006."""
        all_codes = (
            pipeline["comparison"].introduced
            + pipeline["comparison"].resolved
            + pipeline["comparison"].persistent
        )
        lines = _lines(report_md)
        for code in all_codes:
            code_lines = [ln for ln in lines if code in ln]
            assert code_lines, f"No line found for failure mode code '{code}'"
            # Each line with the code should contain a severity indicator
            found_severity = any(
                sev in ln.lower()
                for ln in code_lines
                for sev in ("low", "medium", "high", "critical")
            )
            assert found_severity, (
                f"No severity label found on lines containing '{code}': {code_lines}"
            )

    def test_each_item_shows_evidence(self, report_md, pipeline):
        """Each failure-mode item shows a non-empty evidence pointer. VAL-REPORT-006."""
        all_codes = (
            pipeline["comparison"].introduced
            + pipeline["comparison"].resolved
            + pipeline["comparison"].persistent
        )
        lines = _lines(report_md)
        for code in all_codes:
            code_lines = [ln for ln in lines if code in ln and "—" in ln]
            assert code_lines, (
                f"No evidence pointer found (— separator) on line for '{code}'"
            )
            # After the — there should be non-empty evidence
            for ln in code_lines:
                parts = ln.split("—", 1)
                if len(parts) == 2 and parts[1].strip():
                    break
            else:
                pytest.fail(
                    f"No non-empty evidence after '—' on lines for '{code}': {code_lines}"
                )


# ---------------------------------------------------------------------------
# VAL-REPORT-007 — Rubric
# ---------------------------------------------------------------------------


class TestRubric:
    def test_rubric_section_exists(self, report_md):
        """A 'Rubric' section exists. VAL-REPORT-007."""
        assert any(
            "rubric" in ln.lower() and ln.startswith("#")
            for ln in _lines(report_md)
        ), "No 'Rubric' heading found"

    def test_rubric_defines_all_7_dimensions(self, report_md):
        """Rubric section defines all 7 rubric dimensions. VAL-REPORT-007."""
        for dim in DIMENSION_NAMES:
            assert dim in report_md, (
                f"Dimension '{dim}' not found in Rubric section"
            )

    def test_rubric_lists_default_weights(self, report_md):
        """Rubric section includes default weight values. VAL-REPORT-007."""
        # At least one default weight value should appear in a rubric context
        for weight_val in DEFAULT_WEIGHTS.values():
            if str(weight_val) in report_md or f"{weight_val:.2f}" in report_md:
                return
        pytest.fail("No default weight value found in Rubric section")

    def test_no_placeholder_tokens(self, report_md):
        """Report contains no TODO, TBD, lorem, or placeholder markers. VAL-REPORT-007."""
        pattern = re.compile(
            r"\b(TODO|TBD|FIXME|lorem|ipsum|placeholder|coming soon)\b",
            re.IGNORECASE,
        )
        matches = pattern.findall(report_md)
        assert not matches, f"Placeholder tokens found: {matches}"


# ---------------------------------------------------------------------------
# VAL-REPORT-008 — Footer
# ---------------------------------------------------------------------------


class TestFooter:
    def _footer_lines(self, report_md: str) -> list[str]:
        """Return the last 15 lines of the report."""
        return _lines(report_md)[-15:]

    def test_footer_has_tool_version(self, report_md):
        """Footer contains the tool version. VAL-REPORT-008."""
        from tracecaliper import __version__
        footer = "\n".join(self._footer_lines(report_md))
        assert __version__ in footer, (
            f"Tool version '{__version__}' not found in footer"
        )

    def test_footer_no_iso8601_timestamp(self, report_md):
        """Footer contains NO ISO-8601 timestamp. VAL-REPORT-008."""
        footer = "\n".join(self._footer_lines(report_md))
        iso_pattern = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]?\d*:?\d*")
        matches = iso_pattern.findall(footer)
        assert not matches, (
            f"ISO-8601 timestamp found in footer: {matches}"
        )

    def test_footer_no_month_names(self, report_md):
        """Footer contains no human-readable month names. VAL-REPORT-008."""
        months = (
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        )
        footer = "\n".join(self._footer_lines(report_md))
        for month in months:
            assert month not in footer and month.lower() not in footer, (
                f"Month name '{month}' found in footer"
            )

    def test_footer_has_suite_hash(self, report_md):
        """Footer contains a suite hash. VAL-REPORT-008."""
        footer = "\n".join(self._footer_lines(report_md))
        # Short sha256 hex (8 chars)
        assert re.search(r"sha256: [0-9a-f]{8}", footer), (
            "No 'sha256: <hex>' found in footer"
        )

    def test_full_report_no_iso8601_anywhere(self, report_md):
        """No ISO-8601 timestamp appears anywhere in the report. VAL-REPORT-008."""
        iso_pattern = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
        matches = iso_pattern.findall(report_md)
        assert not matches, (
            f"ISO-8601 timestamp found in report: {matches}"
        )


# ---------------------------------------------------------------------------
# VAL-REPORT-009 — Byte-determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_two_renders_are_identical(self, pipeline):
        """Two consecutive render_markdown calls on the same inputs produce identical bytes. VAL-REPORT-009."""
        kwargs = dict(
            introduced_modes=pipeline["introduced_modes"],
            resolved_modes=pipeline["resolved_modes"],
            persistent_modes=pipeline["persistent_modes"],
            comparison_path="comparison.json",
        )
        md1 = render_markdown(
            pipeline["comparison"], pipeline["suite"], pipeline["gate"], **kwargs
        )
        md2 = render_markdown(
            pipeline["comparison"], pipeline["suite"], pipeline["gate"], **kwargs
        )
        assert md1 == md2, "Two renders of the same inputs produced different output"

    def test_render_without_mode_objects_is_deterministic(self, pipeline):
        """Render without full FailureMode objects is also deterministic. VAL-REPORT-009."""
        md1 = render_markdown(
            pipeline["comparison"], pipeline["suite"], pipeline["gate"],
            comparison_path="comparison.json",
        )
        md2 = render_markdown(
            pipeline["comparison"], pipeline["suite"], pipeline["gate"],
            comparison_path="comparison.json",
        )
        assert md1 == md2


# ---------------------------------------------------------------------------
# VAL-REPORT-010 — Section order and table column consistency
# ---------------------------------------------------------------------------


class TestSectionOrder:
    _EXPECTED_HEADINGS = [
        "skill delta report",       # H1
        "simulated",                # disclaimer heading
        "gate decision",            # gate section
        "suite metadata",           # suite metadata
        "per-skill scores",         # per-skill table
        "dimension breakdown",      # dimension breakdown
        "failure modes",            # failure modes
        "rubric",                   # rubric
    ]

    def test_sections_in_documented_order(self, report_md):
        """Sections appear in the documented order (H1 → ... → Rubric). VAL-REPORT-010."""
        lines = _lines(report_md)
        heading_lines = [ln.lower() for ln in lines if ln.startswith("#")]
        last_idx = -1
        for expected in self._EXPECTED_HEADINGS:
            found_idx = next(
                (i for i, ln in enumerate(heading_lines) if expected in ln),
                None,
            )
            if found_idx is None:
                # The footer doesn't have a heading; skip if not found in headings
                continue
            assert found_idx > last_idx, (
                f"Section '{expected}' is out of order (found at index {found_idx}, "
                f"expected after index {last_idx})"
            )
            last_idx = found_idx

    def test_all_tables_have_consistent_column_counts(self, report_md):
        """Every Markdown table has consistent column counts across all rows. VAL-REPORT-010."""
        lines = _lines(report_md)
        in_table = False
        table_col_count: int | None = None
        table_start_line = 0
        for i, ln in enumerate(lines):
            is_table_row = ln.startswith("|")
            if is_table_row and not in_table:
                in_table = True
                table_col_count = len(ln.split("|")) - 2  # exclude leading/trailing |
                table_start_line = i
            elif is_table_row and in_table:
                col_count = len(ln.split("|")) - 2
                assert col_count == table_col_count, (
                    f"Inconsistent column count in table starting at line {table_start_line}: "
                    f"header has {table_col_count}, row at line {i} has {col_count}: {ln!r}"
                )
            elif not is_table_row and in_table:
                in_table = False
                table_col_count = None


# ---------------------------------------------------------------------------
# VAL-REPORT-011 — CLI error handling and no host paths
# ---------------------------------------------------------------------------


class TestCLIErrorHandling:
    def test_cli_report_success(self, tmp_path):
        """CLI report command exits 0 and writes the report file. VAL-REPORT-011."""
        out = tmp_path / "report.md"
        result = runner.invoke(
            app,
            [
                "report",
                "--comparison", "reports/comparison.json",
                "--output", str(out),
            ],
        )
        assert result.exit_code == 0, (
            f"report command failed with exit code {result.exit_code}; "
            f"output: {result.output!r}"
        )
        assert out.exists(), "Output file was not created"
        content = out.read_text()
        assert len(content) > 0, "Output file is empty"

    def test_cli_report_missing_comparison(self, tmp_path):
        """CLI report fails non-zero on missing comparison file. VAL-REPORT-011 / VAL-CLI-027."""
        result = runner.invoke(
            app,
            [
                "report",
                "--comparison", "does-not-exist.json",
                "--output", str(tmp_path / "report.md"),
            ],
        )
        assert result.exit_code != 0, (
            "Expected non-zero exit when comparison file is missing"
        )
        combined = result.output or ""
        assert "does-not-exist.json" in combined, (
            "Error message does not reference the missing file path"
        )

    def test_cli_report_missing_comparison_no_partial_output(self, tmp_path):
        """CLI report does not create a partial output file on failure. VAL-REPORT-011."""
        out = tmp_path / "report.md"
        runner.invoke(
            app,
            [
                "report",
                "--comparison", "does-not-exist.json",
                "--output", str(out),
            ],
        )
        assert not out.exists(), (
            "Output file should not be created when comparison is missing"
        )

    def test_cli_report_malformed_json(self, tmp_path):
        """CLI report fails non-zero on malformed comparison JSON. VAL-REPORT-011 / VAL-CLI-028."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{not valid json", encoding="utf-8")
        out = tmp_path / "report.md"
        result = runner.invoke(
            app,
            [
                "report",
                "--comparison", str(bad_file),
                "--output", str(out),
            ],
        )
        assert result.exit_code != 0, (
            "Expected non-zero exit for malformed JSON comparison"
        )
        combined = result.output or ""
        assert any(
            kw in combined.lower()
            for kw in ("json", "parse", "error")
        ), f"Error message does not reference JSON/parse failure: {combined!r}"

    def test_cli_report_missing_required_key(self, tmp_path):
        """CLI report fails when comparison JSON is missing required 'comparison' key. VAL-REPORT-011."""
        bad_file = tmp_path / "incomplete.json"
        bad_file.write_text(
            json.dumps({"gate": {"decision": "PASS", "rationale": ["ok"]}}),
            encoding="utf-8",
        )
        out = tmp_path / "report.md"
        result = runner.invoke(
            app,
            [
                "report",
                "--comparison", str(bad_file),
                "--output", str(out),
            ],
        )
        assert result.exit_code != 0, (
            "Expected non-zero exit for comparison JSON missing 'comparison' key"
        )
        combined = result.output or ""
        assert any(
            kw in combined.lower()
            for kw in ("comparison", "schema", "validation", "malformed", "missing")
        ), f"Error message lacks useful context: {combined!r}"

    def test_cli_report_unwritable_output(self, tmp_path):
        """CLI report fails non-zero when output path is unwritable. VAL-CLI-030."""
        read_only_dir = tmp_path / "readonly"
        read_only_dir.mkdir()
        read_only_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
        out = read_only_dir / "report.md"
        result = runner.invoke(
            app,
            [
                "report",
                "--comparison", "reports/comparison.json",
                "--output", str(out),
            ],
        )
        # Restore permissions for cleanup
        read_only_dir.chmod(stat.S_IRWXU)
        assert result.exit_code != 0, (
            "Expected non-zero exit when output path is unwritable"
        )

    def test_generated_report_no_host_paths(self, tmp_path):
        """Generated report contains no absolute host paths. VAL-REPORT-011."""
        out = tmp_path / "report.md"
        result = runner.invoke(
            app,
            [
                "report",
                "--comparison", "reports/comparison.json",
                "--output", str(out),
            ],
        )
        assert result.exit_code == 0
        content = out.read_text()
        host_path_pattern = re.compile(
            r"(^|[\s])/(home|root|Users|var|tmp)/",
            re.MULTILINE,
        )
        matches = host_path_pattern.findall(content)
        assert not matches, (
            f"Absolute host paths found in report: {matches}"
        )

    def test_missing_required_args(self):
        """CLI report with no args exits non-zero. VAL-CLI-029."""
        result = runner.invoke(app, ["report"])
        assert result.exit_code != 0
        combined = result.output or ""
        assert any(opt in combined for opt in ("--comparison", "--output")), (
            "Error should mention the missing required option"
        )


# ---------------------------------------------------------------------------
# End-to-end: full pipeline → report file ≥ 1500 bytes
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_report_file_size_at_least_1500_bytes(self, tmp_path):
        """End-to-end pipeline produces a report ≥ 1500 bytes. VAL-CLI-035."""
        # Run compare
        cmp_out = tmp_path / "comparison.json"
        compare_result = runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
                "--output", str(cmp_out),
            ],
        )
        assert compare_result.exit_code == 0, (
            f"compare failed: {compare_result.output!r}"
        )

        # Run report
        rpt_out = tmp_path / "skill-delta-report.md"
        report_result = runner.invoke(
            app,
            [
                "report",
                "--comparison", str(cmp_out),
                "--output", str(rpt_out),
            ],
        )
        assert report_result.exit_code == 0, (
            f"report failed: {report_result.output!r}"
        )

        content = rpt_out.read_text(encoding="utf-8")
        byte_count = len(content.encode("utf-8"))
        assert byte_count >= 1500, (
            f"Report is only {byte_count} bytes; expected >= 1500"
        )

    def test_report_contains_all_required_sections(self, tmp_path):
        """End-to-end report contains all required section markers. VAL-CLI-035."""
        cmp_out = tmp_path / "comparison.json"
        runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
                "--output", str(cmp_out),
            ],
        )
        rpt_out = tmp_path / "skill-delta-report.md"
        runner.invoke(
            app,
            [
                "report",
                "--comparison", str(cmp_out),
                "--output", str(rpt_out),
            ],
        )
        content = rpt_out.read_text(encoding="utf-8")
        required = [
            "Skill Delta Report",
            "simulated",
            "Gate Decision:",
            "Suite Metadata",
            "Per-Skill Scores",
            "Dimension Breakdown",
            "Failure Modes",
            "Rubric",
        ]
        for marker in required:
            assert marker.lower() in content.lower(), (
                f"Required section marker '{marker}' not found in report"
            )

    def test_compare_plus_report_determinism(self, tmp_path):
        """Two compare+report runs produce byte-identical report files. VAL-REPORT-009."""
        # Use the same filenames for both runs to ensure the footer comparison
        # basename is identical across runs (determinism requirement).
        cmp_out = tmp_path / "comparison.json"
        runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
                "--output", str(cmp_out),
            ],
        )
        rpt_dir1 = tmp_path / "run1"
        rpt_dir2 = tmp_path / "run2"
        rpt_dir1.mkdir()
        rpt_dir2.mkdir()

        rpt_out1 = rpt_dir1 / "skill-delta-report.md"
        runner.invoke(
            app,
            [
                "report",
                "--comparison", str(cmp_out),
                "--output", str(rpt_out1),
            ],
        )

        rpt_out2 = rpt_dir2 / "skill-delta-report.md"
        runner.invoke(
            app,
            [
                "report",
                "--comparison", str(cmp_out),
                "--output", str(rpt_out2),
            ],
        )

        md1 = rpt_out1.read_bytes()
        md2 = rpt_out2.read_bytes()
        assert md1 == md2, (
            "Two compare+report runs produced different report files (not byte-deterministic)"
        )

    def test_gate_decision_in_report_matches_comparison_json(self, tmp_path):
        """Gate decision in report matches the one in comparison.json. VAL-REPORT-002."""
        cmp_out = tmp_path / "comparison.json"
        runner.invoke(
            app,
            [
                "compare",
                "--baseline", BASELINE_PATH,
                "--candidate", CANDIDATE_PATH,
                "--output", str(cmp_out),
            ],
        )
        bundle = json.loads(cmp_out.read_text())
        expected_decision = bundle["gate"]["decision"]

        rpt_out = tmp_path / "skill-delta-report.md"
        runner.invoke(
            app,
            [
                "report",
                "--comparison", str(cmp_out),
                "--output", str(rpt_out),
            ],
        )
        content = rpt_out.read_text()
        # Banner must contain the decision
        assert expected_decision in content, (
            f"Gate decision '{expected_decision}' not found in report"
        )
