"""TraceCaliper CLI entrypoint.

Three subcommands:

- ``inspect``: load and pretty-print a suite configuration.
- ``compare``: run the full scoring/detection/comparison/gate pipeline and
  write a deterministic JSON bundle.
- ``report``: generate a Skill Delta Report (stub — implemented in the
  ``skill-delta-report`` feature).

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
from rich.console import Console
from rich.table import Table

from tracecaliper.comparison import compare as _run_compare
from tracecaliper.failure_modes import detect_failure_modes
from tracecaliper.gate import decide
from tracecaliper.loaders import LoaderError, load_suite, load_trace
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

    # ── build deterministic JSON bundle ──────────────────────────────────────
    # Top-level keys are chosen to satisfy the validation contract:
    #   "deltas"       ← matches "dimensions"|"deltas"
    #   "failure_modes" ← exact match
    #   "gate"         ← matches "gate"|"decision"
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
        "gate": json.loads(gate.model_dump_json()),
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
    """Generate a Skill Delta Report from a comparison JSON file."""
    typer.echo(
        "Error: report command is not yet implemented. "
        "It will be available after the skill-delta-report feature.",
        err=True,
    )
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
