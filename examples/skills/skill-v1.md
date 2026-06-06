# Python API Skill — v1

## Description

Baseline version of the `python-api` skill. Given a task that asks for a small
Python REST endpoint, this skill drafts a Flask-style handler, edits the
application configuration, and updates the public router. It is intentionally
"first-pass": it does not add structured input validation, it does not cache
responses, and it does not always finish by running the project's test suite.

## Inputs

- A short natural-language task description for the new endpoint.
- The current project layout (read-only).

## Outputs

- A new route handler function.
- An entry in the application's URL router.
- A best-effort note in the task tracker.

## Steps

1. Read the task description.
2. Locate the most plausible router file.
3. Add a new handler function.
4. Wire the handler into the router.
5. Tweak adjacent helpers when the structure feels awkward.
6. Stop once the handler returns a non-error response by inspection.

## Known Limitations

- No structured input validation; relies on raw request payload access.
- No response caching, even for clearly cacheable read endpoints.
- Edits often spill into unrelated modules ("while I'm here" refactors).
- The final step does not run `pytest`; task completion is asserted by reading
  the handler, not by executing tests.
