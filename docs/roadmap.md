# Roadmap

TraceCaliper MVP is intentionally scoped to a local, deterministic CLI that operates on
simulated traces.  This document describes the planned evolution of the tool across
future releases.

---

## Current State (MVP)

The MVP delivers:

- A fully deterministic eval harness scoring 7 rubric dimensions
- Failure-mode detection across 7 taxonomy codes
- A release-gate decision (PASS / HOLD / INVESTIGATE) with explainable rationale
- A polished Skill Delta Report Markdown artifact
- Simulated example traces for end-to-end demonstration

The primary MVP limitation is that all traces are **simulated**.  The roadmap addresses
this by introducing live-trace adapters and CI integration.

---

## Phase 1: Live Trace Adapters

The `load_trace(path)` interface was designed from day one to be adapter-compatible.
The `Trace` Pydantic model is the contract; any adapter that produces a `Trace` plugs
directly into the existing eval engine without changes.

### Planned Adapters

#### Factory.ai Droid Traces

Factory.ai Droids emit structured session logs capturing tool calls, file edits, and
test outcomes.  A Factory trace adapter will:

1. Query the Factory.ai API (or read an exported session JSON) for a Droid session.
2. Map the Factory session schema to the TraceCaliper `Trace` model.
3. Set `simulated: false` to flag the trace as a live capture.

This is the highest-priority live-trace adapter because TraceCaliper itself was built
using Factory.ai — dogfooding the integration is a natural first step.

#### GitHub PR Traces

Pull requests on GitHub contain all the signals needed for trace evaluation: diff (files
touched, LOC), CI check outcomes (test results), and commit messages (instruction
adherence).  A GitHub adapter will:

1. Accept a GitHub PR URL or PR number via `--source github://owner/repo/pulls/N`.
2. Fetch the PR diff, CI status, and review metadata via the GitHub REST API.
3. Synthesize a `Trace` with steps derived from commits and a metadata block from CI.

#### NDJSON Streaming Traces

For high-throughput eval pipelines, a streaming NDJSON format is more efficient than
loading a single large JSON blob.  A NDJSON adapter will:

1. Read a `.ndjson` file where each line is a `TraceStep` JSON object.
2. Stream-parse the file to build a `Trace` incrementally.
3. Support arbitrarily large traces without loading them entirely into memory.

---

## Phase 2: CI Integration

Once live traces are available, the natural next step is to run TraceCaliper
automatically as part of a CI pipeline.

### GitHub Actions Integration

A GitHub Action `tracecaliper-gate` will:

1. Trigger on pull requests that modify skill files or traces.
2. Run `tracecaliper compare` against the baseline from the default branch.
3. Post a PR comment with the gate decision and a link to the Skill Delta Report.
4. Block merge if the gate decision is `HOLD`.

This closes the feedback loop: every skill PR gets an automated eval gate decision
before human review.

---

## Phase 3: Rubric Calibration and Adapter Ecosystem

### Calibrated Weights per Skill Domain

Default weights work well for general coding skills, but different domains may need
different calibrations:

- **Security-critical skills** might weight `security` at 0.40 and reduce `reviewability` to 0.02.
- **Refactoring skills** might weight `over_editing` and `repo_conventions` higher.
- **Test-writing skills** might weight `tests_passed` lower (the skill *is* writing tests)
  and `instruction_following` higher.

The suite YAML `weights` block already supports this — the roadmap item is providing
curated example suites for common domains.

### Adapter Registry

A formal adapter registry will allow third parties to publish trace adapters as plugins:

```bash
pip install tracecaliper-adapter-github
tracecaliper compare --source github://owner/repo/pulls/42 ...
```

---

## Phase 4: Report Enhancements

The Skill Delta Report is already polished enough to screenshot for a portfolio.  Future
enhancements include:

- **HTML export** — a styled HTML version of the Skill Delta Report for embedding in
  dashboards or static sites.
- **Trend reports** — comparing a series of trace versions (v1, v2, v3, ...) to show
  the improvement trajectory over time.
- **Drill-down evidence** — expanding the failure-mode evidence section to show the
  exact step evidence that triggered each detector.

---

## Out of Scope (Permanent)

The following are explicitly out of scope for TraceCaliper and will not be added:

- **LLM-based scoring** — scoring must remain deterministic and offline.
- **Web UI / dashboard** — TraceCaliper is a CLI tool; UI is a separate concern.
- **Database persistence** — all state lives in files; no database.
- **Multi-user or auth surfaces** — single-user local tool.

These constraints are not limitations but design choices that make TraceCaliper
auditable, reproducible, and deployable in air-gapped environments.
