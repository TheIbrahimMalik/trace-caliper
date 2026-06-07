# Code Review Notes

This document captures concrete code review observations from the TraceCaliper MVP.
It covers both observations surfaced by the Factory Review flow and additional
observations made during implementation.

---

## Summary

The TraceCaliper codebase is clean, type-annotated, and well-tested.  The primary
findings were two non-blocking issues surfaced during the post-milestone Factory Review,
both of which were addressed in the `readme-and-docs` feature.

---

## Finding 1: Missing Subprocess-Level CLI Test (Non-blocking)

**File:** `tests/test_cli.py`
**Observation:** The existing CLI tests used `typer.testing.CliRunner` exclusively, which
imports the CLI module directly without spawning a real subprocess.  This means a broken
`__main__.py` (e.g., a missing `if __name__ == "__main__": app()` line) would not be
caught by the test suite, because CliRunner bypasses the module entry point.

**Fix Applied:** Added a subprocess-based test `test_module_entrypoint_subprocess` in
`tests/test_cli.py` that invokes `[sys.executable, '-m', 'tracecaliper', '--help']` via
`subprocess.run` and asserts:
- Exit code is 0
- Stdout contains the strings `inspect`, `compare`, `report`

This test exercises the full `python -m tracecaliper` path and would catch `__main__.py`
wiring regressions that CliRunner-only tests miss.

---

## Finding 2: Absolute Host Path Leak in Report Footer (Non-blocking)

**File:** `src/tracecaliper/report.py`
**Function:** `render_markdown`
**Observation:** The `comparison_path` parameter was embedded in the report footer
verbatim:

```python
comp_basename = comparison_path if comparison_path else "comparison.json"
```

If a caller passed an absolute path (e.g., `/home/ibrahim/src/trace-caliper/reports/comparison.json`),
the full absolute path would appear in the generated Markdown report.  This violates the
"no absolute host paths in generated artifacts" invariant documented in the architecture.

**Fix Applied:** Normalized via `Path(comparison_path).name`:

```python
from pathlib import Path
comp_basename = Path(comparison_path).name if comparison_path else "comparison.json"
```

The `.name` property extracts only the filename component (e.g., `comparison.json`),
discarding any directory prefix.  The fix is backward-compatible — passing just
`"comparison.json"` already produces `"comparison.json"`.

---

## General Code Quality Observations

### Positive Observations

**Type annotations throughout.** Every public function has full parameter and return
type hints.  Pydantic models provide runtime validation that catches schema errors at
the boundary rather than deep in the engine.

**Pure engine functions.** The scoring, failure-mode detection, comparison, and gate
modules contain only pure functions — no I/O, no mutation of inputs.  This makes them
trivially testable and deterministic.

**Sorted iteration everywhere.** The codebase consistently uses `sorted()` on dimension
names and failure-mode codes before iterating, ensuring byte-identical output across
Python runs regardless of dict insertion order.

**Error handling in CLI.** The CLI correctly catches `FileNotFoundError`,
`json.JSONDecodeError`, `yaml.YAMLError`, `ValidationError`, and `OSError` at the
boundary, emitting human-readable messages to stderr with non-zero exit codes.  No raw
Python tracebacks are exposed to users.

**CliRunner test coverage.** The test suite covers all three CLI commands across happy
paths and error paths using `typer.testing.CliRunner`, validating exit codes, stdout
content, and output file structure.

### Minor Observations

**`test_compare.py` and `test_scorer.py` are empty stubs.** These files exist as
empty stubs but contain no tests.  The intended coverage is provided by
`test_comparison.py` and `test_scoring.py` respectively.  The stubs could be removed
or kept for future expansion — they do not cause test failures.

**`Suite.skills` accepts empty list in `report` command.** When the `report` command
reconstructs a `Suite` from the comparison bundle's embedded metadata, it passes
`skills=[]` because the comparison JSON does not store skill file paths.  This is
intentional (the report command does not need to resolve skill files), but the empty
list could be confusing to a reader of the CLI code.

**Determinism relies on `sort_keys=True` in `json.dumps`.** The `compare` command uses
`json.dumps(bundle, indent=2, sort_keys=True)` to ensure byte-identical output.  This is
correct, but it means that the `TraceScore.dimensions` list order (already sorted by
dimension name) is doubly sorted — once by the model and once by `sort_keys`.  The double
sort is harmless but worth noting.

---

## Verification

Both findings were fixed and verified by re-running the full test suite:

```bash
.venv/bin/pytest -q
# all tests pass
```

The subprocess-based test `test_module_entrypoint_subprocess` was confirmed to:
- Pass when `__main__.py` is correctly wired
- Fail when `__main__.py` is emptied (verified manually then reverted)
