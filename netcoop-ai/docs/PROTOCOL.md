# NetCoop Agent Protocol v1.0

All agents communicate through JSON **envelopes**. The bus serialises every message to JSON and
re-validates it (pydantic) on each hop, so a malformed or incompatible message is rejected at the
boundary and answered with an `error` envelope. Transport is pluggable (in-process bus here; the same
JSON could travel over REST or a queue).

## Envelope

| Field | Type | Meaning |
|---|---|---|
| `protocol` | `"netcoop"` | Constant marker |
| `schema_version` | string | Protocol version. Supported: `1.0`. Others are rejected |
| `message_id` | string | Unique id of this message |
| `correlation_id` | string | Incident id; identical for all messages of one diagnosis |
| `sender`, `recipient` | string | Agent names (`performance_agent`, ... , `orchestrator`) |
| `msg_type` | enum | `capability_request/response`, `analyze_request`, `finding_batch`, `challenge_request/response`, `correlate_request`, `diagnosis`, `verify_request`, `verification_result`, `report_request`, `report`, `error` |
| `timestamp` | ISO-8601 UTC | Creation time |
| `payload` | object | Type-specific body (below) |

## Payload conformance

Each `msg_type` has required payload fields (machine-readable in `schemas/payload_requirements.json`).
A message missing them is rejected at the envelope. Every element of `finding_batch.findings` must
itself validate as a `Finding`, so a third-party agent cannot inject malformed evidence.

| msg_type | required payload fields |
|---|---|
| `capability_request` | none |
| `capability_response` | `agent`, `protocol_versions`, `accepts`, `produces` (+ rest of the Agent Card) |
| `analyze_request` | `devices` (+ `topology`) |
| `finding_batch` | `agent`, `domain`, `findings` (+ `scope` from connectivity) |
| `challenge_request` | `device_id`, `signals`, `devices` |
| `challenge_response` | `agent`, `answers` |
| `correlate_request` | `devices`, `batches` (+ `failed_agents`, `completeness`, `challenge`) |
| `diagnosis` | `status` |
| `verify_request` | `diagnosis`, `devices` |
| `verification_result` | `status`, `confidence` |
| `report_request` | `meta` |
| `report` | `status`, `suspected_root_cause` |
| `error` | `error` |

## Discovery and version handshake (Agent Cards)

Before any work, the orchestrator sends `capability_request` to every agent. The reply is an
**Agent Card** (`schemas/agent_card.schema.json`, examples in `schemas/agent_cards/`):

| Field | Meaning |
|---|---|
| `agent`, `description`, `domain`, `version` | identity |
| `protocol_versions` | protocol versions the agent can speak |
| `accepts` / `produces` | message types in / out |
| `hypotheses`, `signals` | what it can vote on / observe |
| `transport` | `in-process` or `http` |
| `negotiation` | (foreign agents only) remote descriptor, chosen format, mapped hypotheses, unmapped causes, status, reason |

Every card is validated against the AgentCard schema at handshake; an invalid card makes the agent
`incompatible` with the validation errors as the reason.

An agent that shares no protocol version with the orchestrator, or does not accept the message type it
is needed for, is marked `incompatible` and excluded. The run continues in degraded mode and the report
states it. Discovery is answered even by an agent whose work handler is faulty.

## Challenge round (negotiation)

If the two best hypotheses are within 0.15 of each other the correlation agent is not allowed to just
pick one. The orchestrator sends `challenge_request` to the specialists asking for the **graded strength**
of the signals each hypothesis expects: `(value - onset) / (threshold - onset)` clipped to [0,1] (onsets in
`schemas/signal_thresholds.json`), plus `present|elevated|absent|unknown`.
The correlation agent re-scores with `score x (0.5 + 0.5 x mean strength)`, and the report records margin
before/after.

## Foreign agents over HTTP: discovery, negotiation, validation

`netcoop/remote.py` contains a standalone HTTP agent ("WirelessOps analyzer") with its own format family
`wlo-N` (`rssi`, `retry_rate` as a fraction, `dns_fail_ratio`; causes `WEAK_WIRELESS` / `DNS_OUTAGE` /
`DHCP_OUTAGE` / `CO_CHANNEL_INTERFERENCE`) and the adapter `RemoteConnectivityAgent`.

1. **Discovery.** On `capability_request` the adapter calls `GET /about` and validates the descriptor
   (`name`, `formats[]`, `causes[]`).
2. **Negotiation.** Adapter formats `("wlo-1",)` are intersected with the remote's `formats`. No common
   format, or no cause that maps to a NetCoop hypothesis -> the card advertises no protocol version and
   carries `negotiation.status = "incompatible"` with the reason; the orchestrator excludes the agent at
   handshake (`agent_health: incompatible`) and the run continues degraded.
3. **Translation.** canonical -> `POST /analyze {"format": "wlo-1", "hosts": [...]}`; the remote answers 415
   for a format it does not speak.
4. **Reply validation.** A reply without a `results` list is rejected as a whole (agent fails, retry,
   degrade). Individual items are validated: non-object results, unrequested hosts, strengths outside [0,1],
   unknown tags and causes without a NetCoop hypothesis are dropped and listed in
   `finding_batch.remote_validation.problems`.
5. **Provenance.** The `finding_batch` records `remote`, `remote_format` and `remote_response_sha256`
   (hash of the exact bytes the remote sent), so ProofTrace can cite what the foreign agent said.

Failure modes (all demonstrated by `python -m netcoop interop-demo`, server `--mode`): `ok`, `incompatible`,
`malformed`, `partial`, `slow` (timeout), `flaky` (503 then OK), service down.

## ProofTrace (audit artefact, not a protocol message)

`report.prooftrace` (or `python -m netcoop prooftrace`) contains: `conclusion`, `integrity` (per-message
SHA-256 over canonical JSON with sorted keys, plus a chain digest), `evidence[]` (with `raw_samples` =
`{record_index, path, raw, value, timestamp}` and `observed_by` = `{agent, message_id, finding_id}`),
`hypotheses[]`, `agents[]` (with `leave_one_out`), `sensitivity`, `missing_information`,
`remediation_check`, `decision_gates` and `checks`. `verify_prooftrace(trace, raw, log)` re-derives all of it.

## Validation tooling

```
python -m netcoop schemas --out schemas      # JSON Schemas, agent cards, thresholds, metric catalogue
python -m netcoop validate logs/run.jsonl    # validate any message or message log against the protocol
python -m netcoop replay   logs/run.jsonl    # re-feed every request to fresh agents; replies must be identical
```

## Message flow

```
orchestrator -> performance_agent     analyze_request      {devices, topology}
orchestrator <- performance_agent     finding_batch        {agent, domain, findings[]}
orchestrator -> infrastructure_agent  analyze_request   ... likewise for connectivity_agent
                                                              (+ "scope" in its finding_batch)
orchestrator -> trustguard            audit_request        {devices, batches[{message_id, payload}], cards}
orchestrator <- trustguard            audit_result         {audit{summary, records[], flagged[], unverifiable[], agents},
                                                              audited_batches[]}
orchestrator -> correlation_agent     correlate_request    {devices, batches[] (= audited_batches), failed_agents[], completeness}
orchestrator <- correlation_agent     diagnosis            {status, hypothesis, ranking[], root_cause_devices[], ...}
orchestrator -> correlation_agent     verify_request       {diagnosis, devices}
orchestrator <- correlation_agent     verification_result  {status, confidence, verified[], partial{}, contradicted[],
                                                             unverifiable[], quality_flags[], gates[], breakdown{}}
orchestrator -> reporting_agent       report_request       {diagnosis, verification, meta}
orchestrator <- reporting_agent       report               final JSON report
```
The three `analyze_request`s are sent one after another in a fixed order (not concurrently), which keeps
the log and its digests reproducible.

Any failing step produces an `error` envelope on the bus; the orchestrator retries once, then degrades:
the agent is marked `failed` (or `incompatible` at handshake), listed in the report's limitations, and the
confidence is penalised. A reply that violates the protocol counts as a failure: a `finding_batch` with an
unknown hypothesis, a vote or strength outside [0, 1], a missing required field, an unknown domain or an
unsupported `schema_version` is rejected at the bus, so none of its findings reach the correlation agent.
Findings about a `device_id` absent from the telemetry are ignored by correlation.

### TrustGuard audit (`audit_request` / `audit_result`, audit version 1.0)

Each record in `audit.records` is one claim:

```json
{"record_id": "TG-030", "kind": "vote", "agent": "performance_agent", "device_id": "DEPT_SW_01",
 "finding_id": "performance_agent:DEPT_SW_01", "message_id": "<finding_batch id>", "subject": "link_congestion",
 "reported": 0.99, "expected": {"ceiling": 1.0, "specific_support": 0.0, "ceiling_tolerance": 0.1, "authority": true},
 "decision": "flagged", "reason_codes": ["UNSUPPORTED_CERTAINTY", "SELF_CONTRADICTION"],
 "explanation": "...", "telemetry_refs": [{"signal": "high_utilization", "metric": "link_utilization_pct",
 "value": 40.2, "strength": 0.0}], "finding_sha256": "<sha256 of the finding as sent>"}
```

* `kind` is one of `vote | signal | evidence | scope | finding`.
* `decision` is one of `trusted | flagged | unverifiable`.
* Reason codes are listed in `netcoop/trustguard.py` (`FLAG_CODES`, `UNVERIFIABLE_CODES`).

`audited_batches` are the input batches filtered claim by claim:
* flagged votes are removed;
* unverifiable votes are capped at 0.25;
* flagged or unverifiable signals and evidence are dropped;
* a flagged scope moves to `scope_rejected`.

Each finding gains a `trustguard` note listing what changed. The audit is deterministic: the same telemetry and
findings always give the same records. The message timestamp is the audit time.

## Canonical telemetry (what agents receive in `devices`)

`devices` maps `device_id` -> `{metrics, status, samples, role, parent, completeness, trends, quality}`.
`quality` lists consistency flags `{code, metric, message}` with codes `status_contradiction`,
`unstable_metric`, `inconsistent_metrics`, `conflicting_duplicates`. Devices whose samples are all stale are
removed and reported as silent.
A metric that is missing is **absent from `metrics`** (never zero). Units are fixed:

| Metric | Unit | Valid range |
|---|---|---|
| `latency_ms`, `jitter_ms` | milliseconds | 0 .. 600000 |
| `packet_loss_pct`, `link_utilization_pct`, `cpu_utilization_pct`, `memory_utilization_pct`, `retransmission_pct`, `dns_failure_pct`, `dhcp_failure_pct` | percent (0-100) | 0 .. 100 |
| `throughput_mbps`, `bandwidth_mbps` | megabits/second | >= 0 |
| `queue_drops`, `interface_errors`, `link_flaps` | count per sampling interval | >= 0 |
| `wifi_rssi_dbm` | dBm | -120 .. 0 |
| `status` | `Healthy` / `Warning` / `Critical` / `Unknown` | |

## Finding (inside `finding_batch.findings[]`)

| Field | Meaning |
|---|---|
| `finding_id`, `agent`, `domain`, `device_id` | identity (`domain` is `performance`, `infrastructure` or `connectivity`) |
| `votes` | `{hypothesis: support in [0,1]}`; hypotheses: `link_congestion`, `interface_fault`, `weak_wifi`, `device_overload`, `hardware_failure`, `dns_failure`, `dhcp_failure` |
| `signals_present` | thresholded symptoms observed (see `signals.py`) |
| `signals_unknown` | symptoms that could not be evaluated because the metric is missing |
| `signal_strength` | `{signal: graded strength in [0,1]}` for every *measured* signal (0 = at or below onset, 1 = past alarm threshold). Optional: agents that omit it are treated as binary |
| `evidence[]` | `{metric, value, device_id, unit, threshold, strength, interpretation}` |
| `notes` | free text |

The connectivity agent adds `scope`: `{degraded[], root_candidates[], downstream{child: root}, shared_parent{parent: [children]}, silent_devices[], topology_available}`.

## Input interoperability (normalizer)

External telemetry may use other field names, units, layouts and schema versions. `normalizer.py`
maps them to the canonical form and records every conversion as an `info` issue:

| Seen in input | Handled as |
|---|---|
| `latency_s`, `jitter_s`, `rtt` | seconds -> ms (x1000) |
| `loss_fraction`, `util_fraction`, `cpu_fraction` | fraction -> percent (x100) |
| `throughput_gbps` / `_kbps` | -> Mbps |
| `{"value": 0.28, "unit": "s"}`, `"94%"` | explicit units honoured |
| `devId`, `node`, `host`, `deviceId` | -> `device_id` |
| flat vs nested (`metrics` / `stats` / `telemetry`) | both accepted |
| `state: ok/degraded/down` | -> Healthy/Warning/Critical |
| `schema_version` 0.x / 1.x / 2.x or none | accepted; any other major is rejected with a clear error |
| NaN, strings, out-of-range, negative counts, unknown units | metric dropped + warning |
| record without device id, non-object records | record rejected + error |
| several samples per device | median per metric |
