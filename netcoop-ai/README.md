# NetCoop AI: Self-Auditing Multi-Agent Network Fault Diagnosis (TrustGuard + ProofTrace)

Tech Zephyr 4.0 / Agentic AI Grand Finale. Specialised agents discover each other, negotiate a protocol,
exchange versioned JSON messages, disagree, verify and produce **one explainable report**, and say
"insufficient evidence" when that is the honest answer. Deterministic, rule-based core: reproducible,
replayable, no API keys, no LLM, no network access needed.

Two things make it more than a pipeline of agents:

* **TrustGuard** does not blindly trust the agents. Before correlation, every claim a specialist makes is checked
  against the telemetry, and unsupported claims are removed one by one.
* **ProofTrace** makes the result checkable by a third party: every diagnosis, and every TrustGuard decision, can be
  independently re-derived and verified.

## Signature feature: TrustGuard (agent trust & integrity)

> **An unreliable agent makes a misleading claim. TrustGuard checks it against the network telemetry, flags it,
> keeps that agent's valid evidence, lets the correlation agent produce a defensible diagnosis, and records the
> whole decision in ProofTrace.**

```bash
python -m netcoop trustguard-demo          # the demo above, end to end, in the terminal
```

TrustGuard (`netcoop/trustguard.py`) is an ordinary protocol participant: `audit_request` -> `audit_result`,
between the specialists and the correlation agent. It checks **every claim** in every `finding_batch`:

| Check | Question | Outcome when it fails |
|---|---|---|
| Evidence consistency | Does the signal exist in the telemetry? Does the reported strength match the strength TrustGuard recomputes itself (±0.05, or a matching 0/1 from binary reporters)? Does each evidence item name the right device and value? | `STRENGTH_MISMATCH`, `SIGNAL_NOT_PRESENT`, `EVIDENCE_*_MISMATCH` -> flagged |
| Vote consistency | Is the vote within the strongest symptom of that cause that the agent can observe (+0.10)? Is a confident vote (>= 0.5) backed by a **cause-specific** indicator (e.g. utilization or queue drops for congestion, not just latency)? Does the agent's own report contradict it? | `VOTE_EVIDENCE_MISMATCH`, `UNSUPPORTED_CERTAINTY`, `SELF_CONTRADICTION` -> flagged |
| Domain authority | Is the hypothesis declared on the agent's validated Agent Card? Is the signal in its own domain? | `OUT_OF_DOMAIN_CLAIM`, `FOREIGN_DOMAIN_SIGNAL` -> flagged |
| Missing evidence | Is the telemetry needed to check the claim missing? | `VOTE_UNVERIFIABLE`, `MISSING_TELEMETRY` -> **unverifiable**, not flagged |
| Provenance | Does the finding come from a logged message about a device that exists? Does the topology scope match the degraded devices? | `UNKNOWN_DEVICE`, `SCOPE_MISMATCH` -> flagged |

**Decisions are per claim.**
* **Trusted** claims pass unchanged.
* **Flagged** votes are removed, and flagged signals or evidence are left out of the coverage calculation.
* **Unverifiable** votes are capped at 0.25, the level honest agents use when they cannot tell causes apart.

So one bad vote never removes the rest of an agent's findings. TrustGuard **never** compares a claim with the leading
hypothesis or with other agents (disagreement is not an offence), and it **never** produces a diagnosis.

**Independence.** TrustGuard does not call any agent's vote code.
* It recomputes every signal strength itself from the normalised metrics (`recompute_strength`, tested against
  hand-computed values).
* It shares only the documented constants: alarm thresholds, warning onsets, and which symptoms each cause can
  explain.
* Its two vote bounds hold for every honest vote on 900 benchmark incidents.

**Measured, not assumed** (`benchmarks/benchmark.md`, `python -m netcoop benchmark`):

| | Result |
|---|---|
| False alarms on honest agents (dev, held-out and stress sets, 900 incidents) | **0 of 85,938 claims** rejected |
| Performance agent lies (0.99 vote for its least-supported cause, evidence kept truthful) | correct answers corrupted **14 -> 0**; wrong diagnoses 6.3 % -> 0.0 % |
| Infrastructure agent lies | corrupted **28 -> 1**; wrong diagnoses 9.0 % -> 0.7 % |
| Connectivity agent lies | corrupted **39 -> 0**; wrong diagnoses 8.3 % -> 0.0 % |
| Misleading vote flagged or capped | 100 % / 94 % / 100 % of incidents |

The ~6 % of infrastructure lies that pass are votes the telemetry actually supports: TrustGuard judges claims
against the evidence, not against the answer. **This is a controlled simulation of one kind of unreliable agent**
(our own `adversarial` fault mode). It does not show that TrustGuard detects every compromised agent.

**Adversarial demo scenario** (`data/scenarios/adversarial_agent.json`):
* **Telemetry:** a failing switch (CPU 99.9 %, 300 interface errors, Critical status, link utilization 40 %).
* **The lie:** its `simulation` block sets the performance agent to `adversarial`, and the agent claims
  `link_congestion = 0.99`.
* **What TrustGuard does:** it flags the vote with `UNSUPPORTED_CERTAINTY` (utilization is 40 %) and
  `SELF_CONTRADICTION` (the agent itself reported utilization strength 0.00). The same agent's 38 other claims stay.
* **Result:** hardware failure at confidence 0.85, identical to an all-honest run. Without TrustGuard the result is 0.80.
* **When the lie would win:** on milder incidents the same lie flips the diagnosis. Benchmark incident #10, a mild
  overload, is wrongly diagnosed as congestion without TrustGuard; `tests/test_trustguard.py` checks this.

**Dashboard and ProofTrace.**
* **Web UI:** a TrustGuard view with summary cards, a before/after diagnosis, a per-agent table, a claim table, and
  expandable flagged claims (original claim vs telemetry, expected vs reported, reason, message ID, influence). It has
  a one-click adversarial demo and a TrustGuard on/off switch.
* **ProofTrace:** records every decision with its source message, original finding, finding SHA-256, telemetry
  references down to input record numbers, timestamp and audit version. `verify_prooftrace` **re-runs the audit**
  from the raw input and the logged agent messages. Altering, removing or forging an audit record, or altering a
  finding after the audit, fails verification. SHA-256 shows integrity, not authorship; nothing is signed.

## The differentiator: ProofTrace

> **A network diagnosis whose evidence, agent contributions, alternative hypotheses and remediation outcome
> can all be independently inspected and verified.**

An LLM can *write* a plausible root-cause paragraph. It cannot hand you a proof that a third party can
re-check. Every NetCoop diagnosis ships with a **ProofTrace** (`netcoop/prooftrace.py`):

| ProofTrace section | What it contains | How it is produced |
|---|---|---|
| **Evidence provenance** | every signal on the blamed device, walked back to the exact input record, field path and raw value (`#25.stats.latency = {"value": 0.79, "unit": "s"}`), the unit conversion, the aggregation (median / latest of a rising trend), the graded threshold comparison and the agent message that reported it | normalizer keeps provenance for every canonical value |
| **Competing hypotheses** | all 7 causes with verdict (selected / rejected / not supported), score, the votes behind it (each a logged message id), supporting, contradicting and missing evidence, symptoms it cannot explain, and *generated* rejection reasons ("explains 62 % of observed symptom strength, hardware_failure explains 100 %") | from the logged `finding_batch` and `diagnosis` messages |
| **Agent contributions** | per agent: card, health, its own top vote, whether it agreed, and a **leave-one-out** re-correlation of the logged findings: *decisive*, *corroborating*, *dissenting (outvoted)* or *redundant* | correlation logic re-run on the real logged findings |
| **What would change the diagnosis** | single-measurement what-ifs that re-run the full agent pipeline (remove a supporting signal, strengthen a rival, fill a missing metric) and say which ones flip the conclusion | full pipeline re-run on modified normalised telemetry |
| **Missing information / abstention** | failed decision gates, and the concrete measurements that would decide between the leading hypotheses | verification gates + expected signals |
| **Remediation check** | applies the fix of each top hypothesis to a telemetry copy and re-diagnoses: "only the selected hypothesis' fix resolves the incident" is *behavioural* evidence for the diagnosis | counterfactual remediation |
| **Integrity + checks** | SHA-256 of every protocol message, a chain digest of the log, and the result of `verify_prooftrace` | see below |

**Independent verification.** `verify_prooftrace(trace, raw_input, message_log)` trusts nothing computed
during the run: it re-normalises the raw input, re-derives every canonical value and signal strength,
locates every cited raw sample in the input, re-hashes every message, checks every cited vote against the
logged message, and recomputes the winning hypothesis' fused score from the cited votes and evidence.
Alter one telemetry value, one vote, or delete one message and it fails (tested; also a live "Tamper" control
in the dashboard).

```bash
python -m netcoop prooftrace data/scenarios/hardware_failure.json --out-dir out
#  -> out/hardware_failure.report.json  .prooftrace.json  .prooftrace.md  .messages.jsonl
python -m netcoop verify-trace out/hardware_failure.prooftrace.json \
       --input data/scenarios/hardware_failure.json --log out/hardware_failure.messages.jsonl
#  53/53 checks passed -> VERIFIED   (including 8 TrustGuard audit checks)
```
ProofTrace verified on **300/300** internal benchmark incidents and **40/40** organizer incidents (clean
and stressed). Pre-generated traces: `examples/prooftrace/`.

## Quick start
Requirements: Python 3.10+ and, for the web UI only, Node.js 18+. Commands are one per line so they work in
bash and in Windows PowerShell.
```bash
python -m venv .venv
# activate: .venv\Scripts\Activate.ps1 (PowerShell)  or  source .venv/bin/activate (bash)
pip install -r requirements.txt
python -m netcoop generate                 # 17 synthetic scenarios -> data/scenarios/
python -m netcoop demo                     # run all scenarios, print a summary table

# Web UI (React + TypeScript + Tailwind): build once, then one command serves UI + API
cd web
npm install
npm run build
cd ..
python -m netcoop serve-api                # open http://127.0.0.1:8000
#   development: `python -m netcoop serve-api` + `npm run dev` inside web/ (http://localhost:5173, proxies /api)


python -m netcoop prooftrace data/scenarios/conflicting_evidence.json --out-dir out   # audit artefacts
python -m netcoop run data/scenarios/hardware_failure.json --simulate-fix --fix-hypothesis link_congestion
python -m netcoop organizer-eval --n 40 --seed 7 --sweep 5    # organizer-generated data (separate report)
python -m netcoop interop-demo             # foreign HTTP agent: success + 6 failure / rejection modes
python -m netcoop trustguard-demo          # adversarial agent -> TrustGuard flags it -> ProofTrace records it
python -m netcoop run data/scenarios/hardware_failure.json --inject-fault performance:adversarial   # any scenario
python -m netcoop benchmark                # 300 internal incidents + held-out set + stress set + ablation
python -m pytest -q                        # 244 tests (incl. 300-case fuzz, tamper tests)
python scripts/package_submission.py       # clean ZIP without .venv / node_modules / caches -> build/
```

## Results (read the caveats)

**None of these numbers is real-world network diagnosis accuracy.** No real campus telemetry was available.
Every evaluation below runs on synthetic data, and three of the four come from our own generator. They
measure whether the system reasons correctly and refuses to over-claim under noise, missing data and faint
faults. They do not measure how often it would be right on a production network.

| # | Evaluation set | Size | Source | Used during development? | What it can show |
|---|---|---|---|---|---|
| 1 | Development set (seed 1) | 300 incidents | our generator, standard ranges | **yes**, thresholds were inspected on it | upper bound; expect optimism |
| 2 | Held-out set (seed 3) | 300 incidents | our generator, same ranges, new draws | no, run once at the end | over-fitting to particular incidents (not to the generator) |
| 3 | Stress set (seed 4) | 300 incidents | our generator, ranges **outside** development | no, added afterwards and never tuned on | behaviour on fainter, noisier, sparser data |
| 4 | Organizer set (seed 7) | 40 incidents (+5-seed sweep) | organizers' notebook generator | no | schema compatibility and no over-claiming on independent data |

**Methodology (sets 1-3).**
* Each incident is one of 10 scenario types (9 fault types plus `normal`, which is drawn twice as often) on the same 7-device campus topology.
* Random parameters per incident: fault severity, Gaussian sensor noise, and metric dropout.
  * Standard ranges: severity 0.55-1.25x, noise 3-20 %, dropout 0-30 %.
  * Stress ranges: severity 0.35-0.6x, noise 20-35 %, dropout 15-45 %.
* A prediction is correct only if both the root-cause type and the faulty device(s) match.
* Abstaining ("insufficient evidence") counts as **wrong** in accuracy. *Selective accuracy* covers only the incidents where the system committed.
* Per-scenario sizes are listed in `benchmarks/benchmark.md` (smallest: 18 incidents).
* Reproduce with `python -m netcoop benchmark`, which runs all three sets in ~20 s.

### 1-3. Internally generated data (`benchmarks/benchmark.md`)

| | Dev, before graded signals | **Dev (seed 1)** | Seed 2 (inspected, not tuned) | **Held-out (seed 3)** | **Stress (seed 4)** |
|---|---|---|---|---|---|
| Accuracy | 88.7 % | **94.7 %** | 94.3 % (was 89.7 %) | **93.0 %** | **71.0 %** |
| Accuracy when it commits | 99.3 % | 100.0 % | 99.6 % (was 98.2 %) | 98.2 % | 98.6 % |
| Abstention | 10.7 % | 5.3 % | 5.3 % (was 8.7 %) | 5.3 % | 28.0 % |
| Confident (>= 0.65) and wrong | 0.7 % | **0.0 %** | 0.0 % (was 1.7 %) | 0.0 % | 0.3 % |
| Committed to a wrong cause/device | - | 0.0 % | - | - | 1.0 % |
| `device_overload` / `hardware_failure` | 54 % / 61 % | **74 % / 78 %** | 64 % / 84 % (was 54 % / 61 %) | - | 0 % / 0 % (abstains) |
| Expected calibration error | 0.189 | 0.206 | 0.192 | 0.195 | 0.194 |

*Seed 1 was used for development. Seed 2 was used to inspect the remaining failures, and nothing was changed
after looking. Seed 3 was never looked at before the final run. The stress set was added during submission
polishing and reported as it came out.*

**Reading the stress set.** With faint faults the system mostly **abstains** rather than guessing:
* Accuracy drops to 71 %, but only 1 % of incidents receive a wrong committed diagnosis.
* Device overload, hardware failure and congestion at 35-60 % severity rarely pass the decision gates.
* This is the intended trade-off. A wrong root cause is costlier to an operator than "insufficient evidence, measure X on device Y".
* It also shows the 93-95 % figures depend on faults being reasonably pronounced.

**What changed (item 1).** The failures came from rigid thresholds:
* CPU at 74-89 % counted as *absent* (threshold 90 %), so the infrastructure agent cast no vote at all. The two confident errors were hardware failures with CPU at 89 %.
* Every signal now has a documented **warning onset** (standard operational levels, e.g. CPU 70 %, RSSI -67 dBm; `schemas/signal_thresholds.json`) and a **graded strength** between onset and alarm threshold.
* Votes, coverage and verification use strengths. Binary "present" still means "past the alarm threshold".
* The performance agent no longer proposes Wi-Fi faults for wired switches.
* Weights were not re-tuned.

Remaining misses are mild overloads (CPU 66-80 %). In **62.5 %** of abstentions the leading (uncommitted)
hypothesis was already correct, which is the intended conservative behaviour.

**Per class: abstention, not confusion.** On the development set no fault was diagnosed as a different cause.
Precision is 100 % for every cause, and `device_overload` / `hardware_failure` are never mistaken for each other.
Their lower recall (74 % / 78 %) comes entirely from abstentions on faint cases:
* overloads at about 0.7x severity have CPU around 74 %, barely past the warning onset;
* mild hardware failures still show real congestion signals (99.5 % utilization, queue drops), so the runner-up stays close.

We did not change thresholds to turn those abstentions into commitments, because that would only tune to our own
generator. `tests/test_discrimination.py` pins down the borderline and overlapping cases instead: CPU plus Critical
plus errors gives hardware failure, CPU plus memory on a working device gives overload, Critical alone or CPU at
74 % gives an abstention. The per-class table is in `benchmarks/benchmark.md`.

**Ablation:** all agents reach 94.7 %; the best single agent reaches 56.7 % (infrastructure only). Removing infrastructure
drops accuracy to 50.0 %; removing connectivity drops it to 66.3 %.

**What the confidence number means.** Confidence is an **evidence score**, not a probability:
* It combines fused agent votes, verification against raw data, and explicit penalties for ambiguity, conflicts, missing data, unverifiable signals, failed agents and inconsistent telemetry (formula below).
* Its job is to decide between *diagnosed* (>= 0.65), *tentative* (0.45-0.65) and *insufficient evidence* (< 0.45).
* On our data it is **under-confident**: committed answers at stated 0.57-0.90 were right ~98-100 % of the time (ECE ~0.2).
* We deliberately did not fit a calibration map to our own synthetic data, because that would make the numbers look better without making them more true.
* Calibration should be fitted on real labelled incidents, so "0.80" should not be read as "80 % chance".

### 4. Organizer-generated data (`benchmarks/organizer/organizer_eval.md`)
The organizers supplied `data/organizer/mock-data-builder-netScoopAI.ipynb`. `netcoop/organizer.py` loads the
notebook's own `generate_telemetry()` (parsed with `ast`, only imports and function definitions executed;
fault types `normal` / `latency_spike` / `hardware_failure` discovered from the code), seeds it, groups its
single-record output into 40 incidents (2-5 devices x 3-5 samples, one faulty device) and diagnoses them.
The organizer schema needed **no field mapping**; the incident assembly is the only adaptation and is
documented. The 40 generated incidents are saved in `data/organizer/incidents/`. Nothing was tuned on them.

| Organizer data (40 incidents, seed 7) | Clean | Stressed (20 % metrics dropped, stale sample, junk value) |
|---|---|---|
| Accuracy | 100 % | 100 % |
| False diagnoses | 0 % | 0 % |
| Abstention | 32.5 % (= the `latency_spike` incidents) | 32.5 % |
| Faulty device detected | 100 % | 100 % |
| ProofTrace verified | 40/40 | 40/40 |

Seeds 1-5 (40 each): 97.5-100 %, 0 false diagnoses; the single miss is a `latency_spike` whose random
utilization reached ~85 %, reported as a *tentative* congestion (counted as wrong). Over 6 seeds x 50 incidents
with stress, one stressed hardware failure was tentatively called congestion.
**How to read it:** `latency_spike` is a *symptom*, not a cause, so we count it correct only when the
device is flagged and no root cause is committed. The organizer profiles are far apart, so this mainly
shows schema compatibility and no over-claiming; it says little about borderline cases.

## What it does (mapped to the problem statement)
| Requirement | Implementation |
|---|---|
| Multiple collaborating agents | performance, infrastructure, connectivity (local or **foreign HTTP**), correlation, reporting |
| Agent interoperability | versioned envelope, per-type payload validation, Agent Cards validated at handshake, **format negotiation** with a foreign agent, strict reply validation, exported JSON Schemas, **TrustGuard**: every claim audited against the telemetry and the sender's card before it is used |
| Orchestration | discovery -> fan-out to the three specialists (called **one after another in a fixed order**, so the message log and its digests are reproducible) -> **TrustGuard audit** -> fusion -> challenge round -> verification -> report, retry + graceful degradation (TrustGuard down: run continues unaudited and says so) |
| Fault diagnosis | 7 root causes, graded signals, topology-aware root vs downstream, multi-fault, trends |
| Unified report | JSON + Markdown + **ProofTrace** |
| Validation / error handling | NaN, junk, units, schema versions, stale / contradictory / unstable / inconsistent telemetry, agent crashes, timeouts, malformed remote replies, **misleading or out-of-authority agent claims** (TrustGuard) |
| Optional: dashboard | **Web UI** (React/TypeScript/Tailwind, `web/`) on a stdlib JSON API (`netcoop/api.py`): interactive isometric topology (zoom/pan, click a device for telemetry, health and a live what-if), evidence trace, competing hypotheses, full ProofTrace view (hypothesis board, evidence matrix, provenance drill-down to raw records and cited messages, leave-one-out, sensitivity), server-side tamper-and-verify, counterfactual remediation, agent message sequence diagram, benchmarks. TrustGuard view. Every number comes from a live engine run |
| Optional: HITL | approve / reject recommended actions |
| Optional: remediation | counterfactual: before/after device health, expected-improvement check, `resolved / partially_resolved / unresolved` |
| Optional: persistence | JSONL message log; `replay` checks determinism; digests in ProofTrace |
| Optional: MCP / LLM | not implemented (by choice) |

## Architecture
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/PROTOCOL.md](docs/PROTOCOL.md).
```
 raw telemetry --> normalizer (+provenance, quality flags) --> ORCHESTRATOR --handshake/negotiation--> agent cards
                                                                  |--> performance / infrastructure / connectivity (local or HTTP)
                                                                  |        finding_batch: graded signals + votes + evidence
                                                                  |--> TrustGuard: audit every claim vs telemetry -> audited batches
                                                                  |--> correlation: fuse, resolve conflicts, challenge round
                                                                  |--> correlation: verify against raw data, decision gates
                                                                  `--> reporting: report (+ abstention / hedge)
 message log ---------------------------------------------------> ProofTrace builder (audit, what-if, remediation check)
                                                                  `--> verify_prooftrace(trace, raw, log): independent re-check
```

## How evidence is correlated
1. **Graded signals.** `strength = (value - onset) / (threshold - onset)` clipped to [0, 1]; missing metric = unknown, never zero.
2. **Votes.** Each specialist votes (0-1) on hypotheses it can observe, weighted by signal strength.
3. **Fusion.** `score = noisyOR(votes x authority) x (0.4 + 0.6 x coverage)`; authority 1.0 for the observing domain, 0.7 otherwise; coverage = strength-weighted share of observed symptoms the cause explains.
4. **Topology.** Degraded devices under a degraded parent are downstream; shared-parent and silent-device alternatives are listed.
5. **Conflicts.** An agent whose favourite lost is recorded with the reason.
6. **Challenge round.** Top two within 0.15 -> specialists report graded strengths of the expected signals -> re-score.
7. **Verification.** Expected signals are re-derived from raw normalised data: present / elevated / absent / unknown.

## Confidence method and decision gates
```
confidence = fused x verification_factor - ambiguity - conflict - data_quality - unverifiable - failed_agent - consistency
verification_factor = 0.6 + 0.4 x (verified + sum(partial strengths)) / decided      (0.8 if nothing decidable)
consistency  = 0.05 per telemetry-consistency flag touching the blamed device's expected metrics (max 0.15)
```
`>= 0.65 diagnosed` · `0.45-0.65 tentative` · `< 0.45 insufficient_evidence`. Every report lists the six
**decision gates** (evidence strength, verification, separation, completeness, consistency, agent availability)
and which failed. An abstention says why and which measurement on which device would decide it.

## Robustness
Aliases, units, schema versions 0/1/2, NaN / non-numeric / out-of-range values, junk records, bad JSON.
New: **stale** devices (all samples > 30 min older than the batch) become *silent*, not trusted;
**contradictory** status (Healthy with >= 2 alarms, Critical with none); **unstable** metrics straddling their
threshold across samples; **inconsistent** metrics (throughput > bandwidth); **conflicting duplicate** samples.
Flags appear in data quality, ProofTrace and the confidence penalty. 300-case fuzz test: never crashes,
ProofTrace builds on every corrupted input.

## Interoperability (`python -m netcoop interop-demo`, `examples/interop_demo.md`)
The foreign "WirelessOps analyzer" is a separate HTTP service with its own format family (`wlo-1`), field
names, fraction units and cause vocabulary (including a cause NetCoop has no hypothesis for). The adapter
discovers it (`GET /about`), validates its descriptor, negotiates a common format, builds the Agent Card from
what it advertises, validates every reply item and records the SHA-256 of each raw reply.

| Foreign agent behaviour | Result |
|---|---|
| compatible | diagnosed weak_wifi 0.81; leave-one-out: remote findings are **decisive** |
| only speaks `wlo-2` | rejected at handshake: "no common format", run continues degraded |
| invalid reply items | 4 items dropped with reasons, diagnosis unaffected |
| 503 then OK | recovered on retry |
| garbage / too slow / down | contained; agent marked failed; Wi-Fi cannot be diagnosed without it (honest abstention) |

## Known limitations
* No real campus data. All four evaluations are synthetic, three of them from our own generator; the held-out set shares the
  development set's distribution, and the organizer generator only has 3 easily separable profiles.
* All internal sets use one 7-device topology; they say nothing about larger or differently shaped networks.
* With faint faults (stress set) the system abstains often (28 %); it rarely guesses wrong, but it also says less.
* Thresholds, onsets and weights are hand-set from domain practice, not learned.
* Confidence is under-confident on our data and not calibrated on real incidents.
* Remediation is a model of what a fix can change, on a telemetry copy. It never touches a device.
* What-if and leave-one-out analyses are single-factor; interactions between two changes are not explored.
* The foreign HTTP agent is our own mock of a third-party service (separate process and data model), not a vendor product.
* Specialists are called sequentially, not concurrently. Each takes milliseconds, and a fixed order keeps the message log
  and its SHA-256 chain reproducible; a remote agent's latency therefore adds directly to run time (bounded by its timeout).
* TrustGuard's bounds are rules derived from the signal definitions, not a learned model. It catches claims the telemetry
  contradicts; a lie the telemetry happens to support passes (by design it judges evidence, not truth). Challenge-round
  answers are validated by schema and graded from the same telemetry but are not separately audited. The adversarial
  agent is our own simulation.
* No MCP server, no LLM layer.

## Layout
```
netcoop/   protocol signals normalizer generator agents bus orchestrator trustguard prooftrace remediation remote
           organizer benchmark schemas api cli
web/ (React UI)   scripts/package_submission.py   docs/   schemas/   data/scenarios/   data/organizer/   examples/   benchmarks/   tests/
```
