# Skill Delta Report

*Comparing candidate **SIMULATED — python-api skill v2 candidate trace (MVP fabricated data)** against baseline **SIMULATED — python-api skill v1 baseline trace (MVP fabricated data)**.*

## ⚠ Simulated Traces Disclaimer

> **All traces in this report are SIMULATED for MVP demonstration purposes and do not represent real agent execution.**
> Scores, failure modes, and the gate recommendation are derived from fabricated trace data.
> Do not use these results to evaluate production systems.

## Gate Decision

Gate Decision: **HOLD**

SECURITY_FLAG was introduced in the candidate — a new critical security issue requires immediate attention.  Failure mode(s) resolved in candidate: INCOMPLETE_TASK, INSTRUCTION_DRIFT, LOW_REVIEWABILITY, OVER_EDITING, TEST_REGRESSION; but the new SECURITY_FLAG still blocks PASS.  Aggregate delta is positive (+0.244421), reflecting partial score improvement.

---

## Suite Metadata

- **Name:** default
- **Description:** Default TraceCaliper evaluation suite (applies documented default dimension weights).

**Dimension Weights Used**

| Dimension | Weight |
|---|---|
| instruction_following | 0.0700 |
| over_editing | 0.1000 |
| repo_conventions | 0.0800 |
| reviewability | 0.0500 |
| security | 0.2000 |
| task_completion | 0.2500 |
| tests_passed | 0.2500 |

## Per-Skill Scores

| Skill | Baseline | Candidate | Delta |
|---|---|---|---|
| default | 0.492 | 0.736 | +0.244 |
| **Weighted Total** | 0.492 | 0.736 | +0.244 |

## Dimension Breakdown

| Dimension | Baseline | Candidate | Delta | Weight |
|---|---|---|---|---|
| instruction_following | 0.500 | 0.714 | +0.214 | 0.0700 |
| over_editing | 0.000 | 0.875 | +0.875 | 0.1000 |
| repo_conventions | 0.167 | 0.667 | +0.500 | 0.0800 |
| reviewability | 0.619 | 0.907 | +0.288 | 0.0500 |
| security | 1.000 | 0.000 | -1.000 | 0.2000 |
| task_completion | 0.000 | 1.000 | +1.000 | 0.2500 |
| tests_passed | 0.850 | 1.000 | +0.150 | 0.2500 |

## Failure Modes

### Introduced

- **SECURITY_FLAG** (critical) — Security-suspect signal(s) found in 1 step(s): step 6 ('hardcode_api_key'): matched 'hardcoded'.

### Resolved

- **INCOMPLETE_TASK** (high) — Trace metadata reports task_completed=false; the final deliverable was not produced as required by the skill.
- **INSTRUCTION_DRIFT** (medium) — Instruction-drift signal(s) found in 2 step(s): step 4 ('edit_unrelated_helpers'): 'unrelated'; step 5 ('edit_serializers'): 'not required by'.
- **LOW_REVIEWABILITY** (low) — Diff size is 412 LOC, exceeding the reviewability threshold of 200 LOC. Large diffs are difficult to review effectively.
- **OVER_EDITING** (medium) — 12 unique file(s) touched across all steps, exceeding the threshold of 8. Files include: app/config/defaults.py, app/handlers/items.py, app/middleware/__init__.py, app/middleware/logging.py, app/router.py....
- **TEST_REGRESSION** (high) — Test regression detected: failing tests increased from 2 to 3 (+1 newly failing). Failing tests: tests/test_items.py::test_get_item, tests/test_items.py::test_list_items, tests/test_serializers.py::test_item_serializer.

### Persistent

*(none)*

---

## Rubric

This section defines the seven evaluation dimensions, their default weights, and the gate decision rules applied to all comparisons.

### instruction_following (default weight: 0.07)

Fraction of steps that operate entirely within the task scope, where a step is in-scope if it touches no files or all files it touches are in `metadata.files_in_scope`. Neutral 0.5 when scope is undefined.

### over_editing (default weight: 0.1)

Inverse of the ratio of unique files touched to files in scope (scope defined by `metadata.files_in_scope`). A ratio ≤ 1 scores 1.0; a ratio ≥ 5 scores 0.0; linear interpolation in between. Scope-undefined traces receive a ratio based on absolute file count.

### repo_conventions (default weight: 0.08)

Fraction of touched files that lie within the defined task scope (`metadata.files_in_scope`). A score of 1.0 means every edit is within scope; 0.0 means no edited file is in scope. Neutral 0.5 when scope is undefined.

### reviewability (default weight: 0.05)

Diff readability based on diff size (`metadata.review_size_loc`). Diffs ≤ 50 LOC score 1.0; ≥ 1000 LOC score 0.0; linear interpolation in between. Neutral 0.5 when `review_size_loc` is absent.

### security (default weight: 0.2)

Absence of security-suspect signals in any step evidence. Detected signals include hardcoded credentials, `api_key=` / `password=` patterns, `disable_auth`, and common secret-token prefixes (AKIA, ghp_, sk-...). 1.0 = clean; 0.0 = at least one signal detected.

### task_completion (default weight: 0.25)

Whether the agent completed the stated task objective, as indicated by the `task_completed` flag in the trace metadata. 1.0 = confirmed complete; 0.0 = explicitly incomplete; 0.5 = unknown or absent.

### tests_passed (default weight: 0.25)

Fraction of recorded tests passing after the agent's execution (passing / total). A score of 1.0 means all tests pass; 0.0 means all tests fail. When test outcome data is absent, a neutral 0.5 is assigned.

### Gate Decision Rules

Rules are evaluated in priority order.  The first matching rule determines the outcome.

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

---

*TraceCaliper v0.1.0 | Suite: default (sha256: 94eeab71) | Comparison: comparison.json*
