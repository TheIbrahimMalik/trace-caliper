# Factory Security Review

This document summarises the standalone Factory `/security-review` run for TraceCaliper.

It is separate from `docs/security-review-notes.md`, which records the project's security posture and threat-model reasoning.

## 2026-06-06 — `/security-review`

### Command used

`/security-review`

### Review mode

Full-project audit on `main`.

### Scope reviewed

Factory reviewed:

- Production source under `src/tracecaliper/`
- CLI surface: `inspect`, `compare`, `report`
- YAML and JSON loaders
- Pydantic models
- Scoring and failure-mode detection logic
- Comparison, gate, and report generation logic
- `pyproject.toml`
- Example suite and trace fixtures

### Threat-model coverage

Factory checked the repo against:

- STRIDE categories
- OWASP Top 10
- OWASP LLM Top 10
- Deserialization risks
- Hardcoded secrets
- ReDoS
- Command injection
- SQL injection
- Path injection
- Supply-chain concerns

### Result

No security issues found.

### Notable observations

- TraceCaliper is an offline local CLI.
- There is no auth, network, database, shell execution, SQL, HTML rendering, telemetry, LLM integration, or agent-tool integration.
- YAML parsing uses `yaml.safe_load`.
- JSON parsing uses Python stdlib `json`.
- Pydantic models use strict schema validation with forbidden extra fields.
- Secret-like strings such as `AKIA`, `ghp_`, and `sk-` appear only as detector regex patterns, not as real credentials.
- Regexes were not flagged for ReDoS.
- Dependencies are well-established packages from PyPI.
- Example traces are fixture data and contain no real secrets.

### Follow-up

No code changes were required from the standalone security review.

### Customer-success insight

Security review is a useful trust-building step for AI-agent adoption. Even for a small offline CLI, it helps distinguish real risk from demonstration artifacts such as simulated `SECURITY_FLAG` examples.

For a Factory customer, I would position this as part of a post-build quality gate: first validate the feature works, then run readiness checks, then run security review before wider team adoption.
