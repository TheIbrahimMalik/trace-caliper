# Python API Skill — v2

## Description

Iterated version of the `python-api` skill. Given the same task as v1, this
skill adds structured Pydantic input validation, an in-memory response cache
for read-only endpoints, and a hard requirement that the project's test suite
runs green before the skill finishes. Edits are scoped to the minimum set of
files required to satisfy the task.

## Inputs

- A short natural-language task description for the new endpoint.
- The current project layout (read-only).
- The project's existing test command (assumed: `pytest -q`).

## Outputs

- A new route handler function with a typed request model.
- An entry in the application's URL router.
- A small caching wrapper for safely-cacheable GETs.
- A passing `pytest -q` run.

## Steps

1. Read the task description and identify the request/response contract.
2. Define a Pydantic input model for the new endpoint.
3. Add the handler, delegating validation to the input model.
4. Wire the handler into the router with the expected path and method.
5. Add an in-memory cache for the read path (bounded LRU).
6. Run `pytest -q`; iterate until every test passes.

## Caveats

- The in-memory cache is process-local and resets on restart; this is
  acceptable for the demo scenario but should be replaced with a real cache
  in production.
- Configuration values are read from environment variables in production; the
  example skill keeps a placeholder constant in source for didactic purposes.
- The skill assumes the test command is fast enough to run inside the agent
  loop; long-running suites need a different strategy.
