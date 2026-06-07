# Eval Methodology

This document defines TraceCaliper's evaluation methodology: the 7-dimension rubric,
scorer heuristics and thresholds, failure-mode detectors, and release-gate logic.

---

## Overview

TraceCaliper evaluates coding-agent skill traces using a deterministic, fully offline
pipeline:

1. **Load** a trace (JSON) against the `Trace` Pydantic schema.
2. **Score** the trace across 7 rubric dimensions, each producing a `DimensionScore` ∈ [0.0, 1.0].
3. **Detect** failure modes using heuristic detectors, producing a set of `FailureMode` objects.
4. **Compare** baseline and candidate trace scores and failure-mode sets, producing a `Comparison`.
5. **Decide** the release gate outcome: **PASS**, **HOLD**, or **INVESTIGATE**.
6. **Report** the results as a polished Skill Delta Report Markdown document.

---

## Rubric Dimensions and Default Weights

The rubric covers 7 dimensions.  Default weights sum to 1.0.

### `tests_passed` (default weight: 0.25)

Fraction of recorded tests passing after the agent's execution:

```
score = passing_tests / total_tests
```

If `total_tests == 0` or the test outcome data is absent, a neutral score of **0.5** is
assigned.  This dimension has the highest default weight because functional correctness
is the primary evaluation goal.

### `task_completion` (default weight: 0.25)

Binary dimension based on the `task_completed` flag in trace metadata:

- `true` → score 1.0
- `false` → score 0.0
- absent / unknown → score 0.5 (neutral)

Shares the top weight with `tests_passed` because a high-scoring but incomplete task
is not shippable.

### `security` (default weight: 0.20)

Binary dimension based on the presence of security-suspect signals in any step evidence:

- Regex matches: `api_key=`, `password=`, `credential`, `disable_auth`,
  `AKIA[A-Z0-9]{16}` (AWS key), `ghp_[A-Za-z0-9]{36}` (GitHub PAT), `sk-[A-Za-z0-9]{10,}` (OpenAI)
- 1.0 if no matches; 0.0 if any match found

The `SECURITY_FLAG` failure-mode detector uses the same regex.  A `SECURITY_FLAG`
in the failure-mode set always blocks **PASS** at the gate level, regardless of the
aggregate weighted score.

### `over_editing` (default weight: 0.10)

Inverse of the ratio of files touched to files in scope:

```
ratio = files_touched / files_in_scope
score = max(0.0, 1.0 - (ratio - 1.0) / (_OVER_EDIT_MAX_RATIO - 1.0))
```

Thresholds:
- ratio ≤ 1.0 → score 1.0 (only edited in-scope files)
- ratio ≥ 5.0 (`_OVER_EDIT_MAX_RATIO`) → score 0.0
- Linear interpolation between 1.0 and 5.0

When `files_in_scope` is undefined, a raw file count is used with a default scope of 1.

### `repo_conventions` (default weight: 0.08)

Fraction of touched files that lie within the defined task scope:

```
score = in_scope_files / total_touched_files
```

- 1.0 if all edits are in-scope
- 0.0 if no edits are in-scope
- 0.5 if scope is undefined (neutral)

This dimension captures whether the agent respects the project's file-organization
conventions.

### `instruction_following` (default weight: 0.07)

Fraction of steps that operate entirely within task scope:

```
score = in_scope_steps / total_steps
```

A step is "in scope" if it touches no files or all files it touches are in
`metadata.files_in_scope`.  Neutral 0.5 when scope is undefined.

### `reviewability` (default weight: 0.05)

Diff readability based on diff size in lines of code (LOC):

```
score = max(0.0, 1.0 - (loc - _REVIEWABILITY_MIN_LOC) / (_REVIEWABILITY_MAX_LOC - _REVIEWABILITY_MIN_LOC))
```

Thresholds:
- `loc ≤ 50` (`_REVIEWABILITY_MIN_LOC`) → score 1.0
- `loc ≥ 1000` (`_REVIEWABILITY_MAX_LOC`) → score 0.0
- Linear interpolation between 50 and 1000 LOC

Neutral 0.5 when `review_size_loc` is absent from trace metadata.

---

## Weighted Total

The `weighted_total` is the dot product of dimension scores and resolved weights:

```
weighted_total = Σ (dimension_score[d] × weight[d])  for d in 7 dimensions
```

Weights are **not auto-normalized**.  If suite weights sum to a value other than 1.0,
the `weighted_total` range changes accordingly.

---

## Failure-Mode Taxonomy

Seven failure-mode codes are defined.  Detectors are pure, deterministic heuristics.

| Code | Trigger | Severity |
|---|---|---|
| `OVER_EDITING` | files-touched / scope ratio ≥ 3.0 | medium |
| `TEST_REGRESSION` | `tests_failed > 0` in trace metadata | high |
| `INSTRUCTION_DRIFT` | out-of-scope step fraction > 0.3 | medium |
| `SECURITY_FLAG` | security regex matches in any step evidence | critical |
| `CONVENTION_VIOLATION` | in-scope fraction < 0.5 | medium |
| `INCOMPLETE_TASK` | `task_completed == false` in metadata | high |
| `LOW_REVIEWABILITY` | `review_size_loc ≥ 1000` | low |

All detectors:
- Return `[]` (empty list) for clean traces — no exceptions raised
- Do not mutate the input trace
- Return results in sorted order by failure-mode `code`

---

## Release Gate Logic

Rules are evaluated in priority order.  The first matching rule determines the outcome.

### PASS

Conditions (first matching):
- Identical traces: zero aggregate delta AND no introduced/resolved/persistent failures
- Pure improvement: `introduced == ∅`, `resolved ≠ ∅`, `aggregate_delta ≥ 0`, no `SECURITY_FLAG` anywhere
- Default positive: `aggregate_delta ≥ 0`, `introduced == ∅`, no `SECURITY_FLAG`

### HOLD

Conditions (first matching):
- `SECURITY_FLAG` in `introduced` (new security issue — never ship)
- Pure regression: `introduced ≠ ∅`, `resolved == ∅`, no `SECURITY_FLAG`
- Score regression: `aggregate_delta < 0`, `introduced == ∅`, `resolved == ∅`

### INVESTIGATE

Conditions (first matching):
- `SECURITY_FLAG` in `persistent` (existing unresolved security issue)
- Mixed signals: `introduced ≠ ∅` AND `resolved ≠ ∅`, no `SECURITY_FLAG` in introduced

### Rationale

Every `GateDecision` carries a non-empty `rationale` list.  Each entry is a human-readable
string that cites at least one concrete signal: a failure-mode code, the sign/value of the
aggregate delta, or a dimension name.  The rationale is deterministic — identical inputs
always produce identical rationale strings.

---

## Determinism Guarantees

The entire eval pipeline is byte-deterministic:

- **Sorted dimension iteration:** All loops over dimension names use `sorted(DIMENSION_NAMES)`.
- **Sorted failure-mode codes:** Detectors sort their output by `code`; set diffs are
  sorted before serialization.
- **Stable JSON serialization:** `json.dumps(..., sort_keys=True)` is used for all
  output files.
- **No timestamps in artifacts:** `comparison.json` and `skill-delta-report.md` contain
  no wall-clock timestamps, epoch times, or UUIDs.
- **No random seeds:** No `random`, `uuid`, or non-deterministic standard library calls.

Running `compare` or `report` twice on identical inputs always produces byte-identical
output.  This is verified by the `VAL-CLI-017` and `VAL-REPORT-009` assertions in the
validation contract.
