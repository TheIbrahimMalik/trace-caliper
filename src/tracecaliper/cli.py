"""TraceCaliper CLI entrypoint.

Three subcommands:

- ``inspect``: load and pretty-print a suite configuration.
- ``compare``: run the full scoring/detection/comparison/gate pipeline and
  write a deterministic JSON bundle.
- ``report``: generate a Skill Delta Report from a comparison JSON bundle.

Error contract: all user-input errors emit a human-readable message to
stderr and exit with a non-zero code.  HOLD/INVESTIGATE gate decisions are
valid outcomes and exit 0.
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Annotated, NoReturn

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from tracecaliper.comparison import compare as _run_compare
from tracecaliper.failure_modes import detect_failure_modes
from tracecaliper.gate import decide
from tracecaliper.loaders import LoaderError, load_suite, load_trace
from tracecaliper.models import (
    Comparison,
    FailureMode,
    GateDecision,
    Skill,
    Suite,
)
from tracecaliper.report import render_markdown
from tracecaliper.scoring import resolve_weights, score_trace

app = typer.Typer(
    name="tracecaliper",
    help="Trace-first release gate for coding-agent skills.",
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rich_str(renderable: object, width: int = 100) -> str:
    """Render a Rich renderable to a plain string via an in-memory buffer.

    Using a StringIO buffer (not sys.stdout) guarantees the output is
    captured by ``typer.testing.CliRunner`` regardless of how it intercepts
    I/O streams.
    """
    buf = StringIO()
    console = Console(file=buf, highlight=False, width=width)
    console.print(renderable)
    return buf.getvalue()


def _emit_error(message: str) -> NoReturn:
    """Write a human-readable error message to stderr and exit 1."""
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


@app.command()
def inspect(
    suite: Annotated[
        Path,
        typer.Option(
            "--suite",
            help="Path to the suite YAML file.",
            show_default=False,
        ),
    ],
) -> None:
    """Load and pretty-print a suite: name, description, weights, skills, disclaimer."""
    try:
        loaded = load_suite(suite)
    except FileNotFoundError as exc:
        _emit_error(str(exc))
    except yaml.YAMLError as exc:
        _emit_error(f"YAML parse error in '{suite}': {exc}")
    except LoaderError as exc:
        _emit_error(str(exc))

    resolved = resolve_weights(loaded.weights)

    typer.echo(f"Suite:       {loaded.name}")
    typer.echo(f"Description: {loaded.description}")
    typer.echo("")

    # Weights table — rendered to string so CliRunner captures it
    wt = Table(title="Resolved Weights", show_header=True, header_style="bold")
    wt.add_column("Dimension", style="cyan", no_wrap=True)
    wt.add_column("Weight", justify="right")
    wt.add_column("Source")
    for dim in sorted(resolved.keys()):
        source = "override" if dim in loaded.weights else "default"
        wt.add_row(dim, f"{resolved[dim]:.4f}", source)
    typer.echo(_rich_str(wt))

    # Skills list
    typer.echo(f"Skills ({len(loaded.skills)}):")
    for skill in loaded.skills:
        typer.echo(f"  {skill.id}  ->  {skill.path}")

    typer.echo("")
    typer.echo(
        "WARNING - SIMULATED TRACES DISCLAIMER: All traces are SIMULATED "
        "for MVP purposes and do not represent real agent execution."
    )


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


@app.command()
def compare(
    baseline: Annotated[
        Path,
        typer.Option(
            "--baseline",
            help="Path to the baseline trace JSON.",
            show_default=False,
        ),
    ],
    candidate: Annotated[
        Path,
        typer.Option(
            "--candidate",
            help="Path to the candidate trace JSON.",
            show_default=False,
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            help="Destination path for the comparison JSON bundle.",
            show_default=False,
        ),
    ],
) -> None:
    """Run the full comparison pipeline and write a deterministic JSON bundle."""
    # ── load baseline trace ──────────────────────────────────────────────────
    try:
        baseline_trace = load_trace(baseline)
    except FileNotFoundError as exc:
        _emit_error(str(exc))
    except json.JSONDecodeError as exc:
        _emit_error(f"JSON parse error in baseline '{baseline}': {exc}")
    except LoaderError as exc:
        _emit_error(str(exc))

    # ── load candidate trace ─────────────────────────────────────────────────
    try:
        candidate_trace = load_trace(candidate)
    except FileNotFoundError as exc:
        _emit_error(str(exc))
    except json.JSONDecodeError as exc:
        _emit_error(f"JSON parse error in candidate '{candidate}': {exc}")
    except LoaderError as exc:
        _emit_error(str(exc))

    # ── run pipeline (deterministic) ─────────────────────────────────────────
    weights = resolve_weights(None)
    baseline_score = score_trace(baseline_trace, weights)
    candidate_score = score_trace(candidate_trace, weights)
    baseline_modes = detect_failure_modes(baseline_trace)
    candidate_modes = detect_failure_modes(candidate_trace)
    cmp = _run_compare(baseline_score, candidate_score, baseline_modes, candidate_modes)
    gate = decide(cmp)

    # ── build failure-mode detail lookups ────────────────────────────────────
    intro_codes = set(cmp.introduced)
    resolved_codes = set(cmp.resolved)
    persistent_codes = set(cmp.persistent)
    introduced_mode_objs = [m for m in candidate_modes if m.code in intro_codes]
    resolved_mode_objs = [m for m in baseline_modes if m.code in resolved_codes]
    persistent_mode_objs = [m for m in baseline_modes if m.code in persistent_codes]

    # ── build deterministic JSON bundle ──────────────────────────────────────
    # Top-level keys are chosen to satisfy the validation contract:
    #   "deltas"              ← matches "dimensions"|"deltas"
    #   "failure_modes"       ← exact match (codes only, for compatibility)
    #   "failure_mode_details" ← full FailureMode objects for the report renderer
    #   "gate"                ← matches "gate"|"decision"
    #   "suite_metadata"      ← name/description for the report renderer
    bundle: dict = {
        "comparison": json.loads(cmp.model_dump_json()),
        "deltas": {
            "dimensions": cmp.dimension_deltas,
            "aggregate": cmp.aggregate_delta,
        },
        "failure_modes": {
            "introduced": cmp.introduced,
            "resolved": cmp.resolved,
            "persistent": cmp.persistent,
        },
        "failure_mode_details": {
            "introduced": [json.loads(m.model_dump_json()) for m in introduced_mode_objs],
            "resolved": [json.loads(m.model_dump_json()) for m in resolved_mode_objs],
            "persistent": [json.loads(m.model_dump_json()) for m in persistent_mode_objs],
        },
        "gate": json.loads(gate.model_dump_json()),
        "suite_metadata": {
            "name": "default",
            "description": (
                "Default TraceCaliper evaluation suite "
                "(applies documented default dimension weights)."
            ),
        },
    }
    json_text = json.dumps(bundle, indent=2, sort_keys=True)

    # ── write output (create parent dirs automatically) ───────────────────────
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        _emit_error(
            f"Cannot create output directory '{output.parent}': permission denied — {exc}"
        )
    except OSError as exc:
        _emit_error(f"Cannot create output directory '{output.parent}': {exc}")

    try:
        output.write_text(json_text, encoding="utf-8")
    except PermissionError as exc:
        _emit_error(f"Cannot write output '{output}': permission denied — {exc}")
    except OSError as exc:
        _emit_error(f"Cannot write output '{output}': {exc}")

    # ── print Rich summary (always exit 0 — HOLD/INVESTIGATE are valid) ───────
    _styles = {
        "PASS": "bold green",
        "HOLD": "bold yellow",
        "INVESTIGATE": "bold blue",
    }
    delta_str = f"{cmp.aggregate_delta:+.4f}"
    decision_label = gate.decision
    summary_line = _rich_str(
        f"Gate Decision: [{_styles[decision_label]}]{decision_label}"
        f"[/{_styles[decision_label]}]  "
        f"Aggregate delta: {delta_str}  |  Written -> {output}"
    ).rstrip()
    typer.echo(summary_line)


# ---------------------------------------------------------------------------
# report (stub — implemented in the skill-delta-report feature)
# ---------------------------------------------------------------------------


@app.command()
def report(
    comparison: Annotated[
        Path,
        typer.Option(
            "--comparison",
            help="Comparison JSON produced by the `compare` command.",
            show_default=False,
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            help="Destination path for the Markdown Skill Delta Report.",
            show_default=False,
        ),
    ],
) -> None:
    """Generate a polished Skill Delta Report from a comparison JSON bundle."""
    # ── load and validate the comparison bundle ───────────────────────────────
    if not comparison.exists():
        _emit_error(f"Comparison file not found: {comparison}")

    try:
        raw_text = comparison.read_text(encoding="utf-8")
    except OSError as exc:
        _emit_error(f"Cannot read comparison file '{comparison}': {exc}")

    try:
        bundle = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        _emit_error(f"JSON parse error in '{comparison}': {exc}")

    if not isinstance(bundle, dict):
        _emit_error(
            f"Malformed comparison file '{comparison}': "
            "expected a JSON object at the top level."
        )

    # ── extract Comparison model ──────────────────────────────────────────────
    if "comparison" not in bundle:
        _emit_error(
            f"Malformed comparison file '{comparison}': "
            "missing required key 'comparison'."
        )
    try:
        cmp = Comparison.model_validate(bundle["comparison"])
    except (ValidationError, Exception) as exc:
        _emit_error(
            f"Schema validation failed for comparison in '{comparison}': {exc}"
        )

    # ── extract GateDecision model ────────────────────────────────────────────
    if "gate" not in bundle:
        _emit_error(
            f"Malformed comparison file '{comparison}': "
            "missing required key 'gate'."
        )
    try:
        gate = GateDecision.model_validate(bundle["gate"])
    except (ValidationError, Exception) as exc:
        _emit_error(
            f"Schema validation failed for gate in '{comparison}': {exc}"
        )

    # ── reconstruct Suite from embedded metadata + resolved weights ───────────
    suite_meta = bundle.get("suite_metadata") or {}
    suite_name = suite_meta.get("name") or "default"
    suite_desc = suite_meta.get("description") or (
        "Default TraceCaliper evaluation suite "
        "(applies documented default dimension weights)."
    )
    # Weights come from the comparison's baseline score (already resolved)
    weights_data: dict = {}
    try:
        weights_data = dict(bundle["comparison"]["baseline"]["weights"])
    except (KeyError, TypeError):
        pass
    suite = Suite(
        name=suite_name,
        description=suite_desc,
        skills=[],
        weights=weights_data,
    )

    # ── extract full failure-mode detail objects ──────────────────────────────
    fmd = bundle.get("failure_mode_details") or {}
    try:
        introduced_modes: list[FailureMode] = [
            FailureMode.model_validate(m) for m in (fmd.get("introduced") or [])
        ]
        resolved_modes: list[FailureMode] = [
            FailureMode.model_validate(m) for m in (fmd.get("resolved") or [])
        ]
        persistent_modes: list[FailureMode] = [
            FailureMode.model_validate(m) for m in (fmd.get("persistent") or [])
        ]
    except (ValidationError, Exception) as exc:
        _emit_error(
            f"Schema validation failed for failure_mode_details in '{comparison}': {exc}"
        )

    # ── render the report ─────────────────────────────────────────────────────
    md = render_markdown(
        cmp,
        suite,
        gate,
        introduced_modes=introduced_modes or None,
        resolved_modes=resolved_modes or None,
        persistent_modes=persistent_modes or None,
        comparison_path=comparison.name,
    )

    # ── write output (no partial write on error) ───────────────────────────────
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        _emit_error(
            f"Cannot create output directory '{output.parent}': "
            f"permission denied — {exc}"
        )
    except OSError as exc:
        _emit_error(f"Cannot create output directory '{output.parent}': {exc}")

    try:
        output.write_text(md, encoding="utf-8")
    except PermissionError as exc:
        _emit_error(
            f"Cannot write report to '{output}': permission denied — {exc}"
        )
    except OSError as exc:
        _emit_error(f"Cannot write report to '{output}': {exc}")

    typer.echo(f"Report written → {output}")


if __name__ == "__main__":
    app()
