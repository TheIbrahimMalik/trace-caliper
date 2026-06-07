# Tessl Research Engineer — Technical Writeup

## TraceCaliper: A Trace-First Eval Harness for Coding-Agent Skills

This document frames TraceCaliper as a portfolio artifact for a Tessl Research Engineer
application, articulating the design decisions behind the eval harness, rubric, and
failure-mode taxonomy.

---

## Problem Statement

Coding agents (LLM-powered software engineering assistants) iterate rapidly.  A skill
ships as v1, gets patched to v2, v3, and beyond.  Without a systematic eval harness,
teams have no principled way to answer:

> *Is this new version of the agent better or worse than the baseline — and how do we
> know?*

The naive answer is "run the tests" — but passing tests are necessary, not sufficient.
An agent might pass all tests while regressing on reviewability (touching thousands of
lines unnecessarily), convention following (editing files outside task scope), or security
(hardcoding a credential in a fixture).

TraceCaliper is an answer to this gap: a local, deterministic eval harness that scores
agent traces across a configurable rubric, detects failure modes, and produces a
**release-gate decision** — PASS, HOLD, or INVESTIGATE — with an explainable rationale.

---

## What Is a Trace?

A **trace** is a structured record of an agent's execution: the sequence of tool calls,
file edits, test runs, and metadata produced during a single skill invocation.  Traces
are the primary artifact of agent evaluation — they capture not just what the agent
produced (the diff) but how it got there (the steps).

TraceCaliper defines a `Trace` schema (via Pydantic) with:

- `skill_id` — which skill the agent was executing
- `steps` — ordered list of `TraceStep` records, each with a tool name, arguments, and
  evidence text
- `metadata` — task-level context: files in scope, test outcomes, diff size (LOC),
  task completion flag
- `simulated: true` — explicit label for MVP traces

In the MVP, traces are **simulated**: fabricated JSON files that exhibit realistic
patterns (file edits, test results, security-flag signals) without requiring a live
agent.  The eval harness is production-ready; the data is not.

---

## Eval Harness Architecture

The harness is a deterministic pipeline:

```
Trace (JSON)
    ↓
Scoring Engine       ← 7 rubric dimensions, configurable weights
    ↓
Failure-Mode Detectors ← 7 taxonomy codes, pure heuristics
    ↓
Comparison Engine    ← per-dimension deltas, failure-mode set diff
    ↓
Gate Logic           ← PASS / HOLD / INVESTIGATE with rationale
    ↓
Skill Delta Report   ← polished Markdown artifact
```

Every component is **pure** (no I/O, no mutation) and **deterministic** (sorted
iteration, stable serialization, no random seeds or timestamps).  This is a deliberate
design choice: an eval harness that produces different results on repeated runs is not
trustworthy.

---

## Rubric Design

The 7-dimension rubric reflects the properties that matter most for production-quality
agent skill evaluation:

| Dimension | Rationale |
|---|---|
| `tests_passed` | The most direct signal of functional correctness |
| `task_completion` | Did the agent actually finish the job? |
| `security` | Any credential or auth-disabling pattern is an immediate blocker |
| `over_editing` | Agents that touch too many files increase blast radius and review cost |
| `repo_conventions` | Editing outside scope often indicates the agent is confused |
| `instruction_following` | Measures adherence to the skill spec |
| `reviewability` | Large diffs are hard to review, increasing merge risk |

Default weights sum to 1.0: `tests_passed` (0.25) and `task_completion` (0.25) dominate
because functional correctness is the primary goal.  `security` (0.20) is weighted high
because a `SECURITY_FLAG` always blocks `PASS` regardless of aggregate score.

Weights are **not auto-normalized** — if an evaluator sets custom weights summing to 2.0,
the `weighted_total` will be up to 2.0.  This is intentional: the rubric respects the
evaluator's intent without silent magic.

---

## Failure-Mode Taxonomy

The 7 failure modes are designed to be:

1. **Mutually recognizable** — each code has a clear, non-overlapping definition
2. **Actionable** — each failure mode points to a specific remediation
3. **Detectable from trace data** — every detector fires on observable signals in the
   trace, not on speculation

The taxonomy:

| Code | Signal | Severity |
|---|---|---|
| `OVER_EDITING` | files-touched / scope-size ratio ≥ 5× | medium |
| `TEST_REGRESSION` | previously-passing tests now failing | high |
| `INSTRUCTION_DRIFT` | steps touch out-of-scope files beyond threshold | medium |
| `SECURITY_FLAG` | credential patterns, auth-disable signals | critical |
| `CONVENTION_VIOLATION` | edits fall outside defined file scope | medium |
| `INCOMPLETE_TASK` | `task_completed = false` in trace metadata | high |
| `LOW_REVIEWABILITY` | diff ≥ 1000 LOC | low |

A `SECURITY_FLAG` is the only failure mode that **always blocks PASS**, regardless of
aggregate weighted score.  This reflects the real-world principle that security issues
are non-negotiable blockers that cannot be offset by other improvements.

---

## Gate Decision Rules

The gate logic applies rules in strict priority order:

1. `SECURITY_FLAG` introduced → **HOLD**
2. `SECURITY_FLAG` persistent → **INVESTIGATE**
3. No-op (zero delta, empty diffs) → **PASS**
4. Pure improvement (resolved failures, no new failures, delta ≥ 0) → **PASS**
5. Mixed signals (some introduced + some resolved) → **INVESTIGATE**
6. Pure regression (only new failures) → **HOLD**
7. Negative aggregate delta only → **HOLD**
8. Default (positive/zero delta, no new failures) → **PASS**

The `rationale` list in `GateDecision` always cites at least one concrete signal —
a failure-mode code, the sign of the aggregate delta, or a dimension name — so the
output is self-explanatory to a human reviewer.

---

## Design for Extensibility

A core design goal of TraceCaliper is that **live-trace adapters can be added without
changing the engine**.  The `load_trace(path)` function sits behind a clean interface;
future adapters for Factory.ai Droid traces, GitHub PR diffs as traces, or NDJSON
streaming trace formats can be implemented as alternative loaders that produce the same
`Trace` model the engine expects.

The rubric weights are also overridable per evaluation suite (in the YAML `weights`
block), making it possible to tune the rubric for different skill domains without
changing any code.

---

## Relevance to Tessl's Mission

Tessl is building infrastructure for evaluating, iterating, and shipping coding agents
reliably.  TraceCaliper is a concrete demonstration of the core eval loop:

- Define what "good" looks like (rubric dimensions + weights)
- Run the agent against a task (trace capture)
- Score the trace deterministically (scoring engine)
- Detect failure modes (detector taxonomy)
- Make a release decision (gate logic)
- Explain the decision to a human (Skill Delta Report)

This project was designed specifically to showcase the engineering judgment and domain
knowledge relevant to a Tessl Research Engineer role: trace schema design, eval harness
architecture, failure-mode taxonomy, rubric calibration, and deterministic output
generation.
