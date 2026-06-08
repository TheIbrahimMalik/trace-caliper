# Eval Designer Skill

## Purpose

Use this skill when designing or reviewing eval suites, trace schemas, scoring rubrics, failure-mode taxonomies, or Skill Delta Reports for TraceCaliper.

TraceCaliper is a deterministic CLI for comparing coding-agent skill traces and deciding whether a candidate skill change should PASS, HOLD, or require INVESTIGATE.

## Principles

1. Prefer deterministic scoring over subjective judgement.
2. Keep the rubric explainable.
3. Treat security regressions as release-blocking.
4. Separate aggregate score improvement from release readiness.
5. Make failure modes actionable.
6. Clearly label simulated traces as simulated.
7. Avoid adding live LLM or network dependencies to the MVP.

## Rubric dimensions

Default dimensions:

- `tests_passed`
- `task_completion`
- `security`
- `over_editing`
- `repo_conventions`
- `instruction_following`
- `reviewability`

Tests, task completion, and security should carry the most weight.

## Failure modes

Use readable, decision-oriented failure modes such as:

- `OVER_EDITING`
- `TEST_REGRESSION`
- `INSTRUCTION_DRIFT`
- `SECURITY_FLAG`
- `CONVENTION_VIOLATION`
- `INCOMPLETE_TASK`
- `LOW_REVIEWABILITY`

## Report guidance

A good Skill Delta Report should include:

- simulated-traces disclaimer;
- gate decision;
- rationale;
- aggregate delta;
- per-dimension scores;
- introduced/resolved/persistent failure modes;
- rubric explanation;
- suggested next action.

## Constraints

Do not expand the MVP into a live agent runner, hosted dashboard, or LLM-based evaluator. Those are roadmap items.
