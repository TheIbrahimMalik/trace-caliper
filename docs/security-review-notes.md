# Security Review Notes

This document records the security analysis of the TraceCaliper MVP, applying STRIDE
threat modeling, OWASP Top 10, and supply-chain analysis.

---

## Security Posture Summary

**TraceCaliper is deliberately offline and operates with no external network access.**
There are no API keys, no LLM integrations, no telemetry, no authentication surfaces,
and no user-supplied code execution paths.  The attack surface is minimal: file system
reads of YAML/JSON inputs and writes of JSON/Markdown outputs.

---

## 1. Offline / No-Network Guarantee

The tool makes **zero network calls** at runtime.  This is enforced by:

- No `requests`, `httpx`, `aiohttp`, `urllib.request`, or `socket` usage anywhere in
  `src/tracecaliper/`.
- Static import analysis via `compileall` passes with no network-related imports.
- All runtime dependencies (`typer`, `pydantic`, `pyyaml`, `rich`) are pure-Python or
  pre-compiled; none establish outbound connections during normal use.

This posture eliminates an entire class of SSRF, data exfiltration, and dependency
confusion attacks at the network level.

---

## 2. No LLM Calls

TraceCaliper uses **no language model** at any point in the pipeline.  Scoring,
failure-mode detection, comparison, and gate decisions are all purely deterministic
rule-based computations on the input trace data.

This eliminates:

- Prompt injection attacks (no prompt surface exists).
- LLM output unpredictability and non-determinism.
- Data leakage to external LLM APIs.
- Cost amplification through LLM API abuse.

The OWASP LLM Top 10 is therefore not applicable to this codebase.

---

## 3. No Telemetry

No usage metrics, error reports, or diagnostic payloads are transmitted anywhere.
The tool has no home-call mechanism.  Users can verify this by inspecting
`src/tracecaliper/` for any `requests`, `socket`, or `http` imports — none will be found.

---

## 4. Secret and Key Handling

TraceCaliper does **not** handle, store, or transmit any secrets or API keys.

The `SECURITY_FLAG` failure-mode detector actively looks for secret-like patterns in
trace step evidence:

- Common credential patterns: `api_key=`, `password=`, `secret=`
- Secret token prefixes: `AKIA` (AWS), `ghp_` (GitHub PAT), `sk-` (OpenAI)
- Auth-disabling patterns: `disable_auth`, `auth_disabled`, `no_auth`

When these patterns are found in a trace, the detector emits a `SECURITY_FLAG`
failure mode, which forces the gate to `HOLD` or `INVESTIGATE`.  The example traces
bundled with the project contain no real secrets — the patterns detected are
deliberately fabricated for demonstration purposes.

---

## 5. Input Validation

All user-supplied inputs go through Pydantic validation before being processed:

- Suite YAML files are validated against the `Suite` model (required fields, weight
  constraints, no negative weights).
- Trace JSON files are validated against the `Trace` model (required fields,
  monotonic step indices, `simulated: true` flag).
- Comparison JSON files are validated against the `Comparison` + `GateDecision`
  models before rendering.

Malformed inputs trigger a non-zero exit with a human-readable error — no raw
tracebacks, no internal path leakage.

---

## 6. Output Security

### No Host Paths in Generated Artifacts

The Skill Delta Report renderer normalizes the `comparison_path` argument via
`Path(comparison_path).name` before embedding it in the footer, ensuring that absolute
host paths (e.g., `/home/username/src/...`) cannot leak into generated Markdown files.

### Deterministic Outputs

All generated artifacts (`comparison.json`, `skill-delta-report.md`) are
byte-deterministic.  They contain no wall-clock timestamps, no random identifiers, and no
host-specific metadata beyond the basename of the input file.

---

## 7. Dependency Supply Chain

The declared runtime dependencies are minimal and well-established:

| Package | Version | Risk Level |
|---|---|---|
| `typer` | >=0.9 | Low — CLI framework, no network |
| `pydantic` | >=2 | Low — data validation, no network |
| `pyyaml` | any | Low — YAML parsing only |
| `rich` | any | Low — terminal rendering only |

No transitive dependencies introduce network, crypto, or execution risks.

---

## 8. File System Considerations

TraceCaliper only reads files explicitly specified by the user via CLI arguments.  It
writes output files to paths also explicitly specified.  The `--output` parent directory
is created with `mkdir(parents=True, exist_ok=True)` — this is safe and consistent with
how tools like `mkdir -p` operate.

There are no directory traversal risks because:
- Input paths are passed directly to `Path(user_input).read_text()` — no dynamic
  path construction.
- Output paths are passed directly to `Path(user_input).write_text()` — no
  concatenation with untrusted input.

---

## 9. Threat Summary (STRIDE)

| Threat | Applicable? | Mitigation |
|---|---|---|
| Spoofing | No | No auth surface |
| Tampering | Low | File integrity is user-controlled |
| Repudiation | No | No audit log needed |
| Information Disclosure | No | Offline; no external data transmission |
| Denial of Service | Low | No service; CLI exits after processing |
| Elevation of Privilege | No | No privileged operations |

---

## Conclusion

TraceCaliper presents a minimal, well-bounded security profile.  The offline/no-network
posture, absence of LLM calls and telemetry, strong input validation via Pydantic, and
no-secrets architecture make it suitable for use in security-conscious environments.  The
primary remaining risk is the standard supply-chain risk inherent to any Python package
using PyPI dependencies — mitigated by the minimal, well-known dependency set.
