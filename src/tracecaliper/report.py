"""Skill Delta Report renderer for TraceCaliper.

:func:`render_markdown` produces a polished Markdown Skill Delta Report from
a :class:`~tracecaliper.models.Comparison`, a
:class:`~tracecaliper.models.Suite`, and a
:class:`~tracecaliper.models.GateDecision`.

The output is **byte-deterministic**: same inputs always produce identical
bytes.  No wall-clock timestamps, no UUIDs, no absolute host paths are
embedded anywhere in the output.

Section order (fixed):
  1. H1 title + subtitle (within first 5 lines)
  2. Simulated-traces disclaimer (within first 30 lines)
  3. Gate decision banner (before any tables)
  4. Suite Metadata (name, description, all 7 weights)
  5. Per-Skill Score Table (Skill | Baseline | Candidate | Delta)
  6. Dimension Breakdown Table (all 7 dimensions + Weight column)
  7. Failure Modes (Introduced / Resolved / Persistent subsections)
  8. Rubric (all 7 dimension definitions + gate decision rules)
  9. Footer (tool version, suite name/hash, comparison file basename)
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from tracecaliper.models import (
    DEFAULT_WEIGHTS,
    DIMENSION_NAMES,
    Comparison,
    FailureMode,
    GateDecision,
    Suite,
)

# ---------------------------------------------------------------------------
# Rubric dimension definitions
# ---------------------------------------------------------------------------

_RUBRIC_DEFINITIONS: dict[str, str] = {
    "tests_passed": (
        "Fraction of recorded tests passing after the agent's execution "
        "(passing / total). A score of 1.0 means all tests pass; 0.0 means "
        "all tests fail. When test outcome data is absent, a neutral 0.5 is "
        "assigned."
    ),
    "task_completion": (
        "Whether the agent completed the stated task objective, as indicated "
        "by the `task_completed` flag in the trace metadata. 1.0 = confirmed "
        "complete; 0.0 = explicitly incomplete; 0.5 = unknown or absent."
    ),
    "security": (
        "Absence of security-suspect signals in any step evidence. Detected "
        "signals include hardcoded credentials, `api_key=` / `password=` "
        "patterns, `disable_auth`, and common secret-token prefixes (AKIA, "
        "ghp_, sk-...). 1.0 = clean; 0.0 = at least one signal detected."
    ),
    "over_editing": (
        "Inverse of the ratio of unique files touched to files in scope "
        "(scope defined by `metadata.files_in_scope`). A ratio ≤ 1 scores "
        "1.0; a ratio ≥ 5 scores 0.0; linear interpolation in between. "
        "Scope-undefined traces receive a ratio based on absolute file count."
    ),
    "repo_conventions": (
        "Fraction of touched files that lie within the defined task scope "
        "(`metadata.files_in_scope`). A score of 1.0 means every edit is "
        "within scope; 0.0 means no edited file is in scope. Neutral 0.5 "
        "when scope is undefined."
    ),
    "instruction_following": (
        "Fraction of steps that operate entirely within the task scope, where "
        "a step is in-scope if it touches no files or all files it touches are "
        "in `metadata.files_in_scope`. Neutral 0.5 when scope is undefined."
    ),
    "reviewability": (
        "Diff readability based on diff size (`metadata.review_size_loc`). "
        "Diffs ≤ 50 LOC score 1.0; ≥ 1000 LOC score 0.0; linear "
        "interpolation in between. Neutral 0.5 when `review_size_loc` is "
        "absent."
    ),
}

# Gate decision rules table (static Markdown)
_GATE_RULES_TABLE = """\
| Condition | Outcome |
|---|---|
| `SECURITY_FLAG` in introduced | HOLD (never PASS) |
| `SECURITY_FLAG` in persistent | INVESTIGATE (never PASS) |
| Identical traces (zero deltas, empty diffs) | PASS |
| resolved non-empty, introduced empty, delta ≥ 0, no security flag | PASS |
| introduced non-empty, resolved non-empty, no security flag | INVESTIGATE |
| introduced non-empty, resolved empty, no security flag | HOLD |
| aggregate delta < 0, no introductions | HOLD |
| Default (delta ≥ 0, no failures introduced) | PASS |
"""

# Default severity per failure-mode code (fallback when full FailureMode
# objects are not available)
_DEFAULT_SEVERITY: dict[str, str] = {
    "CONVENTION_VIOLATION": "medium",
    "INCOMPLETE_TASK": "high",
    "INSTRUCTION_DRIFT": "medium",
    "LOW_REVIEWABILITY": "low",
    "OVER_EDITING": "medium",
    "SECURITY_FLAG": "critical",
    "TEST_REGRESSION": "high",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _suite_hash(suite: Suite) -> str:
    """Return a short (8-char) SHA-256 hex digest of the suite's canonical JSON."""
    canonical = suite.model_dump_json()
    return hashlib.sha256(canonical.encode()).hexdigest()[:8]


def _fmt(value: float, decimals: int = 3) -> str:
    """Format *value* to fixed *decimals* decimal places."""
    return f"{value:.{decimals}f}"


def _fmt_delta(value: float, decimals: int = 3) -> str:
    """Format *value* as a signed delta (explicit + or -)."""
    return f"{value:+.{decimals}f}"


def _mode_lookup(modes: list[FailureMode] | None) -> dict[str, FailureMode]:
    """Build a code → FailureMode mapping from *modes* (or empty dict if None)."""
    if modes is None:
        return {}
    return {m.code: m for m in modes}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_markdown(
    comparison: Comparison,
    suite: Suite,
    gate: GateDecision,
    *,
    introduced_modes: list[FailureMode] | None = None,
    resolved_modes: list[FailureMode] | None = None,
    persistent_modes: list[FailureMode] | None = None,
    comparison_path: str = "",
) -> str:
    """Render a polished Skill Delta Report in Markdown.

    The output is byte-deterministic: identical inputs always produce
    identical bytes.  No wall-clock timestamps or absolute host paths are
    included.

    Args:
        comparison: The pairwise comparison result (baseline vs. candidate).
        suite: The evaluation suite, providing name, description, and weights.
        gate: The release-gate decision with rationale.
        introduced_modes: Full :class:`FailureMode` objects for codes that
            were introduced in the candidate.  When ``None``, default severity
            labels are used.
        resolved_modes: Full :class:`FailureMode` objects for codes resolved
            compared to the baseline.
        persistent_modes: Full :class:`FailureMode` objects for codes present
            in both traces.
        comparison_path: Basename of the source comparison JSON file (used in
            the footer; no absolute path is embedded).

    Returns:
        Deterministic Markdown string with all nine required sections.
    """
    # Import version here to avoid any potential import-order issues; this
    # module is not imported by tracecaliper/__init__.py so there is no cycle.
    from tracecaliper import __version__ as _version

    lines: list[str] = []

    # -------------------------------------------------------------------------
    # Section 1 — H1 Title + Subtitle (within first 5 lines)
    # -------------------------------------------------------------------------
    lines.append("# Skill Delta Report")
    lines.append("")
    lines.append(
        f"*Comparing candidate **{comparison.candidate.trace_id}** "
        f"against baseline **{comparison.baseline.trace_id}**.*"
    )
    lines.append("")

    # -------------------------------------------------------------------------
    # Section 2 — Simulated-Traces Disclaimer (within first 30 lines)
    # -------------------------------------------------------------------------
    lines.append("## ⚠ Simulated Traces Disclaimer")
    lines.append("")
    lines.append(
        "> **All traces in this report are SIMULATED for MVP demonstration "
        "purposes and do not represent real agent execution.**"
    )
    lines.append(
        "> Scores, failure modes, and the gate recommendation are derived "
        "from fabricated trace data."
    )
    lines.append(
        "> Do not use these results to evaluate production systems."
    )
    lines.append("")

    # -------------------------------------------------------------------------
    # Section 3 — Gate Decision Banner (before any score tables)
    # -------------------------------------------------------------------------
    lines.append("## Gate Decision")
    lines.append("")
    lines.append(f"Gate Decision: **{gate.decision}**")
    lines.append("")
    # Compose a 1–3 sentence rationale summary from the GateDecision.rationale
    # list.  Limit to the first 3 entries for readability.
    rationale_text = "  ".join(gate.rationale[:3])
    lines.append(rationale_text)
    lines.append("")
    lines.append("---")
    lines.append("")

    # -------------------------------------------------------------------------
    # Section 4 — Suite Metadata
    # -------------------------------------------------------------------------
    lines.append("## Suite Metadata")
    lines.append("")
    lines.append(f"- **Name:** {suite.name}")
    lines.append(f"- **Description:** {suite.description}")
    lines.append("")
    lines.append("**Dimension Weights Used**")
    lines.append("")
    lines.append("| Dimension | Weight |")
    lines.append("|---|---|")
    # Use the resolved weights stored in the comparison (all 7 dimensions)
    weights = comparison.baseline.weights
    for dim in sorted(weights.keys()):
        lines.append(f"| {dim} | {weights[dim]:.4f} |")
    lines.append("")

    # -------------------------------------------------------------------------
    # Section 5 — Per-Skill Score Table
    # -------------------------------------------------------------------------
    lines.append("## Per-Skill Scores")
    lines.append("")
    lines.append("| Skill | Baseline | Candidate | Delta |")
    lines.append("|---|---|---|---|")
    baseline_total = comparison.baseline.weighted_total
    candidate_total = comparison.candidate.weighted_total
    skill_label = suite.name
    lines.append(
        f"| {skill_label} | "
        f"{_fmt(baseline_total)} | "
        f"{_fmt(candidate_total)} | "
        f"{_fmt_delta(comparison.aggregate_delta)} |"
    )
    lines.append(
        f"| **Weighted Total** | "
        f"{_fmt(baseline_total)} | "
        f"{_fmt(candidate_total)} | "
        f"{_fmt_delta(comparison.aggregate_delta)} |"
    )
    lines.append("")

    # -------------------------------------------------------------------------
    # Section 6 — Dimension Breakdown Table
    # -------------------------------------------------------------------------
    lines.append("## Dimension Breakdown")
    lines.append("")
    lines.append("| Dimension | Baseline | Candidate | Delta | Weight |")
    lines.append("|---|---|---|---|---|")
    baseline_dims = {d.name: d.score for d in comparison.baseline.dimensions}
    candidate_dims = {d.name: d.score for d in comparison.candidate.dimensions}
    for dim in sorted(DIMENSION_NAMES):
        b_score = baseline_dims.get(dim, 0.0)
        c_score = candidate_dims.get(dim, 0.0)
        delta = comparison.dimension_deltas.get(dim, 0.0)
        w = weights.get(dim, 0.0)
        lines.append(
            f"| {dim} | "
            f"{_fmt(b_score)} | "
            f"{_fmt(c_score)} | "
            f"{_fmt_delta(delta)} | "
            f"{w:.4f} |"
        )
    lines.append("")

    # -------------------------------------------------------------------------
    # Section 7 — Failure Modes
    # -------------------------------------------------------------------------
    lines.append("## Failure Modes")
    lines.append("")
    intro_lookup = _mode_lookup(introduced_modes)
    resolved_lookup = _mode_lookup(resolved_modes)
    persistent_lookup = _mode_lookup(persistent_modes)

    def _render_mode_list(codes: list[str], lookup: dict[str, FailureMode]) -> None:
        if not codes:
            lines.append("*(none)*")
        else:
            for code in sorted(codes):
                mode = lookup.get(code)
                if mode is not None:
                    severity = mode.severity
                    evidence = mode.evidence
                else:
                    severity = _DEFAULT_SEVERITY.get(code, "medium")
                    evidence = "Detected during comparison analysis."
                lines.append(f"- **{code}** ({severity}) — {evidence}")

    lines.append("### Introduced")
    lines.append("")
    _render_mode_list(comparison.introduced, intro_lookup)
    lines.append("")

    lines.append("### Resolved")
    lines.append("")
    _render_mode_list(comparison.resolved, resolved_lookup)
    lines.append("")

    lines.append("### Persistent")
    lines.append("")
    _render_mode_list(comparison.persistent, persistent_lookup)
    lines.append("")
    lines.append("---")
    lines.append("")

    # -------------------------------------------------------------------------
    # Section 8 — Rubric
    # -------------------------------------------------------------------------
    lines.append("## Rubric")
    lines.append("")
    lines.append(
        "This section defines the seven evaluation dimensions, their default "
        "weights, and the gate decision rules applied to all comparisons."
    )
    lines.append("")
    for dim in sorted(DIMENSION_NAMES):
        default_w = DEFAULT_WEIGHTS[dim]
        lines.append(f"### {dim} (default weight: {default_w})")
        lines.append("")
        lines.append(_RUBRIC_DEFINITIONS[dim])
        lines.append("")
    lines.append("### Gate Decision Rules")
    lines.append("")
    lines.append(
        "Rules are evaluated in priority order.  The first matching rule "
        "determines the outcome."
    )
    lines.append("")
    lines.append(_GATE_RULES_TABLE)

    # -------------------------------------------------------------------------
    # Section 9 — Footer (deterministic metadata only, no timestamps)
    # -------------------------------------------------------------------------
    short_hash = _suite_hash(suite)
    comp_basename = Path(comparison_path).name if comparison_path else "comparison.json"
    lines.append("---")
    lines.append("")
    lines.append(
        f"*TraceCaliper v{_version} | "
        f"Suite: {suite.name} (sha256: {short_hash}) | "
        f"Comparison: {comp_basename}*"
    )
    lines.append("")

    return "\n".join(lines)


__all__ = ["render_markdown"]
