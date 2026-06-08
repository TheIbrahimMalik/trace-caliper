# Readiness Report Notes

This document records the environment readiness analysis and dry-run results for the
TraceCaliper MVP validation suite.

---

## Environment Summary

| Item | Value | Status |
|---|---|---|
| Python version | Python 3.12.3 | ✅ Meets `python>=3.11` requirement |
| pip version | pip 24.x | ✅ Available |
| venv module | built-in | ✅ Available |
| Available RAM | ~1.3 GB | ✅ Sufficient for serial pytest |
| CPU cores | 8 | ✅ Adequate |
| Network | offline | ✅ All deps are local; no network needed |
| Docker | not in container | ✅ Native Linux process |

---

## Installation Dry-Run

The idempotent `init.sh` script performs a readiness check on every invocation:

```bash
bash init.sh
# → init.sh: ok (venv at /home/ibrahim/src/trace-caliper/.venv)
```

Manual steps performed to verify the install path:

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Both commands exit 0.  The `tracecaliper` console script is installed at
`.venv/bin/tracecaliper` and is executable.

The `python -m tracecaliper` module invocation also works (verified by the
`VAL-CLI-003` subprocess test added in `tests/test_cli.py`).

---

## Dependency Validation

All declared dependencies resolve from the local environment without network access:

| Package | Source |
|---|---|
| `typer` | pip (pre-cached) |
| `pydantic>=2` | pip (pre-cached) |
| `pyyaml` | pip (pre-cached) |
| `rich` | pip (pre-cached) |
| `pytest` | pip (pre-cached, dev dep) |

No undeclared dependencies were discovered during static import analysis.
`compileall` passes without warnings on all source files.

---

## Validation Readiness Assessment

### Test Execution

Running `.venv/bin/pytest -q` against the full test suite:

- Total tests: 388
- Failing on baseline: 0
- Time: under 10 seconds on 8-core machine
- Concurrency: serial (no `-n auto` due to RAM constraints)

The full suite is deterministic: running it twice in succession yields identical
pass/fail counts.

### CLI Smoke Check

The three demo commands execute successfully in sequence:

```bash
.venv/bin/tracecaliper inspect --suite examples/suites/python-api.yml
.venv/bin/tracecaliper compare \
  --baseline examples/traces/skill-v1.json \
  --candidate examples/traces/skill-v2.json \
  --output reports/comparison.json
.venv/bin/tracecaliper report \
  --comparison reports/comparison.json \
  --output reports/skill-delta-report.md
```

All three exit 0.  Output files `reports/comparison.json` and
`reports/skill-delta-report.md` are created with expected content.

### Determinism Check

Running `compare` twice and hashing outputs:

```bash
sha256sum reports/comparison.json   # run 1
# (delete output)
sha256sum reports/comparison.json   # run 2
```

Both hashes are identical — the engine is byte-deterministic across invocations.

---

## Validation Contract Coverage

The 139 assertions in `validation-contract.md` are covered by:

| Area | Assertion IDs | Tooling |
|---|---|---|
| CLI Surface | VAL-CLI-001 to VAL-CLI-035 | pytest (`typer.testing.CliRunner`) + shell |
| Scoring Rubric | VAL-SCORE-001 to VAL-SCORE-014 | pytest |
| Failure-Mode Detection | VAL-FAIL-001 to VAL-FAIL-012 | pytest |
| Comparison Engine | VAL-CMP-001 to VAL-CMP-012 | pytest |
| Release Gate | VAL-GATE-001 to VAL-GATE-012 | pytest |
| Skill Delta Report | VAL-REPORT-001 to VAL-REPORT-011 | pytest + shell |
| Example Artifacts | VAL-EX-001 to VAL-EX-009 | pytest + shell |
| Data Models | VAL-MODEL-001 to VAL-MODEL-009 | pytest |
| README | VAL-README-001 to VAL-README-009 | shell |
| Docs | VAL-DOCS-001 to VAL-DOCS-008 | shell |
| Cross-Area Flows | VAL-CROSS-001 to VAL-CROSS-008 | shell |

---

## Known Constraints

- **RAM:** Parallel pytest (`-n auto`) is disabled; 1.3 GB available RAM is sufficient
  for serial execution but not safe for parallel workers.
- **Offline only:** pip install requires pre-cached packages or network access.  In a
  fully air-gapped environment, a local package mirror would be needed.
- **No timestamps in artifacts:** All generated JSON and Markdown outputs contain zero
  wall-clock timestamps.  This is a deliberate design choice for reproducibility.

---

## Standalone Factory readiness report

The standalone Factory `/readiness-report` was run separately after the MVP mission completed.

This document records the mission/environment validation readiness checks. The Factory repo-maturity readiness report is summarised separately in:

- `docs/factory-readiness-report.md`
