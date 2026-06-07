# TraceCaliper

**A local, deterministic CLI tool for trace-first release gating of coding-agent skills.**

TraceCaliper loads baseline and candidate skill traces, scores them across a configurable
7-dimension rubric, detects failure modes, and produces a **Skill Delta Report** with an
explicit **PASS / HOLD / INVESTIGATE** release-gate recommendation.

## Why TraceCaliper?

Coding-agent skills ship iteratively — v1 establishes a baseline, v2 (or v3, or a patched
hotfix) is the candidate.  Without a systematic way to *compare* those iterations, teams
ship regressions silently or block safe improvements through gut feeling.  TraceCaliper
gives every skill release a structured gate:

- **Inspect** the evaluation suite to understand what dimensions matter and how they are weighted.
- **Compare** two traces deterministically — no LLMs, no network, no timestamps that break
  reproducibility — and get a JSON bundle with per-dimension deltas, failure-mode diffs,
  and a gate decision.
- **Ship** when the gate says `PASS`.  **Hold** when it says `HOLD`.  Dig deeper when it
  says `INVESTIGATE`.

## ⚠ Simulated Traces — MVP Limitation

**All example traces bundled with TraceCaliper are SIMULATED.  They do not represent real
agent execution.**  The scoring engine and failure-mode detectors are fully deterministic
and production-ready, but they run against fabricated trace data for this MVP release.
Live-trace adapters (Factory, GitHub PRs, NDJSON streams) are on the [roadmap](docs/roadmap.md).

---

## Installation

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

This installs the `tracecaliper` console script and all development dependencies (pytest,
typer, pydantic, pyyaml, rich).

---

## Quick Start

Run the three demo commands in order from the repo root:

```bash
# 1. Inspect the evaluation suite
tracecaliper inspect --suite examples/suites/python-api.yml

# 2. Compare baseline vs. candidate traces
tracecaliper compare --baseline examples/traces/skill-v1.json --candidate examples/traces/skill-v2.json --output reports/comparison.json

# 3. Render the Skill Delta Report
tracecaliper report --comparison reports/comparison.json --output reports/skill-delta-report.md
```

After step 3 you will find:
- `reports/comparison.json` — machine-readable comparison bundle with gate decision
- `reports/skill-delta-report.md` — polished Markdown report ready to screenshot or link

---

## Rubric: 7 Evaluation Dimensions

| Dimension | Default Weight | What it Measures |
|---|---|---|
| `tests_passed` | **0.25** | Fraction of recorded tests passing after the agent run |
| `task_completion` | **0.25** | Whether the agent completed the stated task objective |
| `security` | **0.20** | Absence of security-suspect signals (credentials, `disable_auth`, etc.) |
| `over_editing` | **0.10** | Inverse of the ratio of files touched to files in scope |
| `repo_conventions` | **0.08** | Fraction of touched files within the defined task scope |
| `instruction_following` | **0.07** | Fraction of steps operating within the task scope |
| `reviewability` | **0.05** | Diff readability based on diff size (LOC) |

Weights sum to 1.0 under defaults.  They are overridable per suite in the YAML `weights`
block (see `examples/suites/python-api.yml`).  Negative weights are rejected at load time.
Weights are **not** auto-normalized.

---

## Failure-Mode Taxonomy

| Code | Trigger |
|---|---|
| `OVER_EDITING` | Trace touches significantly more files/lines than warranted |
| `TEST_REGRESSION` | Previously passing tests now fail |
| `INSTRUCTION_DRIFT` | Steps deviate from documented skill instructions |
| `SECURITY_FLAG` | Step matches a security-suspect signal |
| `CONVENTION_VIOLATION` | Edits violate repo conventions |
| `INCOMPLETE_TASK` | Final step does not produce a complete deliverable |
| `LOW_REVIEWABILITY` | Diff is too large or unstructured to be reviewable |

A `SECURITY_FLAG` in `introduced` or `persistent` always blocks `PASS`.

---

## Gate Decisions

| Outcome | When it fires |
|---|---|
| `PASS` | Improvement or no-op with no introduced failures and no security flag |
| `HOLD` | Pure regression, negative aggregate delta, or introduced `SECURITY_FLAG` |
| `INVESTIGATE` | Mixed signals — some failure modes introduced AND some resolved |

---

## Example Output

After running the three demo commands you can open `reports/skill-delta-report.md` to see
the full report.  The comparison data lives in `reports/comparison.json`.

A representative gate decision line looks like:

```
Gate Decision: HOLD  Aggregate delta: +0.2444
```

(HOLD here because the candidate introduced new failure modes even though the aggregate
weighted score improved — see `reports/comparison.json` for the per-dimension breakdown.)

---

## Project Layout

```
src/tracecaliper/       Python package
  models.py             Pydantic data models
  loaders.py            Suite and trace loaders
  scoring.py            7-dimension scoring engine
  failure_modes.py      Failure-mode detectors
  comparison.py         Delta and diff computation
  gate.py               PASS/HOLD/INVESTIGATE decision logic
  report.py             Markdown report renderer
  cli.py                Typer CLI (inspect / compare / report)
  __main__.py           python -m tracecaliper entrypoint

examples/
  suites/python-api.yml   Example evaluation suite
  skills/skill-v1.md      Baseline skill spec
  skills/skill-v2.md      Candidate skill spec
  traces/skill-v1.json    Simulated baseline trace
  traces/skill-v2.json    Simulated candidate trace

reports/
  comparison.json         Generated by `compare`
  skill-delta-report.md   Generated by `report`

tests/                  Pytest suite (unit + CLI + end-to-end)
docs/                   Methodology and case-study docs
  eval-methodology.md
  roadmap.md
  factory-usage-log.md
  readiness-report-notes.md
  security-review-notes.md
  review-notes.md
  tessl-technical-writeup.md
```

---

## Documentation

- [Eval Methodology](docs/eval-methodology.md) — scoring rubric, detectors, gate rules
- [Roadmap](docs/roadmap.md) — planned live-trace adapters and future work
- [Tessl Technical Writeup](docs/tessl-technical-writeup.md) — portfolio narrative
- [Factory Usage Log](docs/factory-usage-log.md) — how this project was built with Factory.ai
- [Security Review Notes](docs/security-review-notes.md) — offline/no-network security posture
- [Readiness Report Notes](docs/readiness-report-notes.md) — validation readiness analysis
- [Code Review Notes](docs/review-notes.md) — code review observations

---

## Design Principles

**Deterministic.** Same inputs always produce identical bytes in `comparison.json` and the
Skill Delta Report.  No wall-clock timestamps, no random seeds, stable sorted iteration.

**Offline.** No network calls, no LLM, no telemetry.  Everything runs locally from the venv.

**Honest.** Every report and every example trace clearly state that traces are simulated.

**Extensible.** Trace loading is behind a clean `load_trace` interface so future adapters
(Factory, GitHub PRs, NDJSON streams) can be plugged in without changing the engine.

---

## Development

```bash
# Run the full test suite
.venv/bin/pytest -q

# Compile-check all source
.venv/bin/python -m compileall -q src tests
```

---

## License

MIT
