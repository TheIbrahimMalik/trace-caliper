# Factory Readiness Report

This document summarises the standalone Factory `/readiness-report` run for TraceCaliper.

The full report is stored in Factory and is not included in this public repository. This file records the main findings, selected actions, and customer-success lessons.

## Report metadata

- Command: `/readiness-report`
- Repository: `trace-caliper`
- Factory UI result: 17% total criteria pass
- Full report: stored in Factory app, not included in this repo

## Strengths

Factory recognised several strengths:

- Clear README with install and demo commands.
- Single-command local setup and demo flow.
- Unit tests and CLI/integration tests.
- Runnable test suite.
- Test naming conventions are clear.
- Evidence of agentic development through Factory/Droid commits and `.factory/skills/`.

## Main gaps

The report identified several repo-readiness gaps:

- `AGENTS.md` was empty.
- `.factory/skills/eval-designer/SKILL.md` was empty.
- No formatter/linter/type-check configuration.
- No pre-commit hooks.
- No dependency lockfile.
- No GitHub Actions CI.
- `.gitignore` was missing common local-secret and IDE entries.
- No issue/PR templates, CODEOWNERS, or dependency-update automation.

## Actions selected

Given the application deadline, I prioritised high-signal, low-risk fixes:

- Populate `AGENTS.md` so future coding agents can understand the repo.
- Populate `.factory/skills/eval-designer/SKILL.md` so the Factory skill surface is meaningful.
- Improve `.gitignore` for local secrets, IDE files, caches, and build artifacts.

## Actions deferred

I intentionally deferred larger maturity improvements:

- Strict mypy enforcement.
- Ruff/Black/pre-commit setup.
- Dependency lockfile.
- GitHub Actions CI.
- CODEOWNERS.
- Issue and PR templates.
- Dependabot/Renovate.

These are useful next steps, but not necessary to prove the TraceCaliper MVP before the application deadline.

## Customer-success insight

The readiness report is useful as an onboarding diagnostic. It separates “the project works locally” from “the repo is mature enough for autonomous agents to contribute safely.”

For a Factory customer, I would use this report to build an enablement plan: first improve agent instructions and setup clarity, then add CI/security automation, then move toward deeper autonomous development workflows.

## Product feedback

The report is valuable, but some checks need project-type context. For a small offline CLI MVP, missing deployment frequency, feature flags, telemetry, or production observability is less important than missing `AGENTS.md`, clear setup instructions, or tests.
