# AGENTS.md

## Project overview

TraceCaliper is a local, deterministic Python CLI for trace-first release gating of coding-agent skill changes.

It compares baseline and candidate coding-agent skill traces, scores them across a configurable rubric, detects failure modes, and generates a Skill Delta Report with a PASS / HOLD / INVESTIGATE recommendation.

The project is intentionally offline and deterministic. The bundled traces are simulated for MVP demonstration purposes.

## Core commands

### Install

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

### Run tests

```bash
.venv/bin/pytest -q
```

### Run the demo workflow

```bash
tracecaliper inspect --suite examples/suites/python-api.yml

tracecaliper compare \
  --baseline examples/traces/skill-v1.json \
  --candidate examples/traces/skill-v2.json \
  --output reports/comparison.json

tracecaliper report \
  --comparison reports/comparison.json \
  --output reports/skill-delta-report.md
```

## Important files

* `src/tracecaliper/models.py`: Pydantic models
* `src/tracecaliper/loaders.py`: Suite and trace loading
* `src/tracecaliper/scoring.py`: Deterministic scoring engine
* `src/tracecaliper/failure_modes.py`: Failure-mode detection
* `src/tracecaliper/comparison.py`: Score/failure-mode comparison
* `src/tracecaliper/gate.py`: PASS / HOLD / INVESTIGATE logic
* `src/tracecaliper/report.py`: Markdown Skill Delta Report renderer
* `src/tracecaliper/cli.py`: Typer CLI
* `examples/`: Simulated suite, skill files, and traces
* `reports/comparison.json`: Generated comparison artifact
* `reports/skill-delta-report.md`: Flagship generated artifact
* `docs/eval-methodology.md`: Rubric and methodology
* `docs/factory-usage-log.md`: Factory.ai usage case study
* `docs/factory-readiness-report.md`: Standalone Factory `/readiness-report` summary
* `docs/readiness-report-notes.md`: Mission/environment validation readiness notes
* `docs/tessl-technical-writeup.md`: Tessl-facing technical narrative

## Editing guidance

When modifying this repo:

1. Keep the CLI local and deterministic
2. Do not add network calls, API keys, telemetry, a database, or a frontend
3. Do not claim simulated traces are real production traces
4. Keep scoring explainable and reproducible
5. Update tests when changing scoring, failure detection, comparison, or gate logic
6. Keep the README demo commands accurate
7. Run `pytest -q` before committing
8. Preserve the Skill Delta Report as the flagship artifact
9. It is okay to regenerate `reports/comparison.json` and `reports/skill-delta-report.md` using the documented demo commands

## Out of scope for the MVP

* Live LLM calls
* Live Factory/Droid trace ingestion
* GitHub App integration
* Web dashboard
* Hosted service
* Database persistence
* Multi-agent orchestration runtime

These belong in the roadmap, not the current MVP.
