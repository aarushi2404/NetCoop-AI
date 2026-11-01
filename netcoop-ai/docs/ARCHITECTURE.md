# NetCoop architecture

```
                 +--------------------------------------------------------------------------+
 raw telemetry   |  normalizer.py                                                            |
 (any schema) -->|  aliases, units, versions, NaN/junk, median/trend aggregation             |
                 |  + provenance: device -> metric -> [record #, field path, raw, value]     |
                 |  + quality flags: stale / status_contradiction / unstable / inconsistent  |
                 +----------------------------------+---------------------------------------+
                                                    | canonical devices{metrics,status,role,parent,quality}
                 +----------------------------------v---------------------------------------+
                 |  orchestrator.py  (every hop = JSON envelope, re-validated on the bus)    |
                 |   0 handshake: capability_request -> Agent Card (pydantic-validated);     |
                 |     foreign agents: GET /about, descriptor validation, format negotiation |
                 |   1 analyze_request -> performance, infrastructure, connectivity          |
                 |     (called one after another in a fixed order, not concurrently)         |
                 |   1b audit_request -> trustguard: every claim checked against telemetry;  |
                 |     audit_result carries the audited batches (claim-by-claim filtered)    |
                 |     (connectivity may be RemoteConnectivityAgent -> HTTP wlo-1 service)   |
                 |   2 correlate_request (audited batches) -> correlation_agent              |
                 |     challenge_request -> specialists if top-2 within 0.15                 |
                 |   3 verify_request -> correlation_agent (raw re-check, decision gates)     |
                 |   4 report_request -> reporting_agent (report, abstention / hedge)        |
                 |   retry once, then degrade; incompatible agents excluded with reason      |
                 +----------------------------------+---------------------------------------+
                                                    | report + bus.log (every message)
                 +----------------------------------v---------------------------------------+
                 |  prooftrace.py  (auditor, not an agent: reads the log, never votes)       |
                 |   evidence provenance, all-hypothesis board, rejection reasons,           |
                 |   leave-one-out per agent, what-if sensitivity (full pipeline re-runs),   |
                 |   remediation check (remediation.compare_fixes), SHA-256 digests,         |
                 |   TrustGuard records (+ re-run of the audit in verify_prooftrace)         |
                 |   verify_prooftrace(trace, raw, log) -> re-derives every claim            |
                 +--------------------------------------------------------------------------+
```

## Modules

| Module | Role |
|---|---|
| `protocol.py` | Envelope, Finding (votes, graded `signal_strength`), Evidence (with `strength`), AgentCard (with optional `negotiation`), payload requirements |
| `signals.py` | thresholds, warning **onsets**, `graded()` strength, `derive_signals` (binary), `derive_strengths` (graded) |
| `normalizer.py` | heterogeneous input -> canonical devices, provenance and quality flags |
| `agents.py` | 3 specialists (graded votes), correlation (fusion, challenge, verification gates), reporting (abstention/hedge) |
| `bus.py` | in-process bus; JSON round-trip + validation on every hop; full log |
| `orchestrator.py` | handshake (card validation, negotiation), fan-out, retry/degrade, challenge round; `run_normalized` for what-if |
| `remote.py` | foreign WirelessOps HTTP service (6 behaviour modes) + adapter (discovery, negotiation, reply validation) + `interop_demo` |
| `trustguard.py` | TrustGuard audit: independent strength recomputation, per-claim decisions (trusted / flagged / unverifiable), claim-by-claim filtering, `TrustGuardAgent` on the bus |
| `prooftrace.py` | ProofTrace builder, independent verifier (incl. re-running the TrustGuard audit), Markdown renderer |
| `remediation.py` | counterfactual fix model, device health, expected-improvement check, `compare_fixes` |
| `organizer.py` | loads the organizer notebook generator, builds incidents, scores, reports separately |
| `benchmark.py` | internal benchmark, held-out set, calibration, ablation |
| `api.py` | stateless stdlib JSON API (`/api/catalog, diagnose, whatif, remediate, verify, benchmarks`) that also serves the built web UI |
| `web/` | React + TypeScript + Tailwind UI (Vite). Renders only what the API returns; no diagnostic logic in the browser |

## Design decisions

* **ProofTrace is an auditor, not an agent.** It only reads the message log and the telemetry; it cannot
  influence a diagnosis, so it cannot "explain" a result into being. Its what-if and leave-one-out analyses
  re-run the real correlation logic / full pipeline rather than describing what would probably happen.
* **Verification is separate from building.** `verify_prooftrace` takes three files (trace, raw input, log)
  and recomputes everything from scratch, so a judge can run it on artefacts produced elsewhere.
* **Graded, not learned.** Onsets are documented domain warning levels. We did not fit weights to the
  benchmark; seed 3 was held out entirely.
* **Fix models are physical.** A fix only restores the metrics it can affect, and only relieves downstream
  symptoms if it removed a real abnormality (target metric strength >= 0.5). A Critical device stays Critical
  unless the fix replaces it. This is what lets a wrong diagnosis be caught as `unresolved`.
* **Foreign agents are first-class but untrusted.** Discovery and format negotiation happen before work;
  every reply item is validated; unknown vocabulary is ignored with a note; the raw reply hash is recorded.
* **Sequential fan-out, on purpose.** The three specialists are independent (none sees another's output), so they
  could run concurrently. We call them in a fixed order instead: each local call takes milliseconds, and a
  deterministic order makes the message log, its SHA-256 chain digest and `replay` reproducible byte for byte.
  The cost is that a slow remote agent adds its latency (bounded by its timeout) to the run.
* **TrustGuard: schema-valid is not the same as true.** The bus rejects malformed findings; TrustGuard catches
  well-formed findings the telemetry does not support (a 0.99 congestion vote at 40 % utilization). It is a bus agent,
  so its decisions are logged, hashed and replayable. Correlation receives only the audited batches, and ProofTrace
  cites the audited copy (`audit_result`) with a link to the original `finding_batch`. Its bounds are derived from the
  signal definitions, never fitted, and TrustGuard never sees the leading hypothesis, so disagreement cannot be
  punished. If TrustGuard fails, the run continues unaudited and the report says so.
* **Invalid findings cannot leak in.** A `finding_batch` whose findings break the schema (unknown hypothesis,
  vote or strength outside [0, 1], missing fields, unknown domain, unsupported protocol version) is rejected at
  the bus; the sender is marked failed and the result is identical to a run without that agent
  (`tests/test_diagnostic_integrity.py`). Findings about devices absent from the telemetry are ignored.
* **Organizer data is never mixed with internal data.** Separate module, separate report, separate web UI
  section, separate data directory.
