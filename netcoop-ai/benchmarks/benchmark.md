# NetCoop benchmark (300 randomised incidents, seed 1)

Each incident has random fault severity (0.55-1.25x), sensor noise (3-20 %) and metric dropout (0-30 %).

| Metric | Value |
|---|---|
| Accuracy (abstaining counts as wrong) | 94.7% |
| Selective accuracy (when the system commits) | 100.0% |
| Abstention rate (insufficient evidence) | 5.3% |
| Confident-and-wrong rate (confidence >= 0.65) | 0.0% |
| Expected calibration error | 0.206 |
| Committed to a wrong cause/device (any confidence) | 0.0% |
| When abstaining, leading hypothesis was right | 62.5% |
| ProofTrace independently verified | 300/300 |

Data: **internally generated** (our own `netcoop/generator.py`). Organizer-generated data is evaluated separately in `benchmarks/organizer/`.

## Held-out incident set (seed 3, not used during development)

| Metric | Value |
|---|---|
| Accuracy | 93.0% |
| Selective accuracy | 98.2% |
| Abstention rate | 5.3% |
| Confident-and-wrong rate | 0.0% |
| Expected calibration error | 0.195 |

Same generator and parameter ranges as above, different random draws: this guards against over-fitting to particular incidents, **not** against a different data distribution.

## Stress set (seed 4, conditions outside the development range)

Fault severity 0.35-0.6x, sensor noise 20%-35%, metric dropout 15%-45%. Nothing was tuned on this set; lower numbers are expected and reported unchanged.

| Metric | Value |
|---|---|
| Accuracy | 71.0% |
| Selective accuracy | 98.6% |
| Abstention rate | 28.0% |
| Confident-and-wrong rate | 0.3% |
| Committed to a wrong cause/device | 1.0% |
| Expected calibration error | 0.194 |

| Scenario | n | Accuracy | Abstained |
|---|---|---|---|
| conflicting_evidence | 24 | 100% | 0 |
| device_overload | 19 | 0% | 19 |
| dhcp_failure | 29 | 100% | 0 |
| dns_failure | 28 | 100% | 0 |
| hardware_failure | 18 | 0% | 15 |
| interface_fault | 29 | 100% | 0 |
| link_congestion | 35 | 20% | 28 |
| normal | 68 | 98% | 1 |
| trend_interface_errors | 30 | 70% | 9 |
| weak_wifi | 20 | 40% | 12 |

## TrustGuard

**False alarms on honest agents** (no fault injected). Every claim of every specialist is audited; a rejected honest claim would be a false alarm.

| Incident set | Incidents | Claims checked | Claims not trusted | Incidents with any flag |
|---|---|---|---|---|
| dev (seed 1) | 300 | 29046 | 0 | 0 |
| held-out (seed 3) | 300 | 28883 | 0 | 0 |
| stress (seed 4) | 300 | 28009 | 0 | 0 |

**Adversarial robustness** (dev set, 300 incidents). The named agent runs in the controlled `adversarial` mode: on the most degraded device it votes 0.99 for the hypothesis its own evidence supports least; its signals and evidence stay truthful. Same incidents with and without TrustGuard.

| Adversarial agent | Accuracy without -> with | Wrong diagnoses without -> with | Correct answers corrupted without -> with | Misleading vote flagged or capped |
|---|---|---|---|---|
| performance_agent | 90.3% -> 94.7% | 6.3% -> 0.0% | 14 -> 0 | 100.0% |
| infrastructure_agent | 85.3% -> 94.3% | 9.0% -> 0.7% | 28 -> 1 | 94.0% |
| connectivity_agent | 81.7% -> 94.7% | 8.3% -> 0.0% | 39 -> 0 | 100.0% |

A misleading vote that the telemetry does support (e.g. a strong symptom of the claimed cause is really present) is not flagged: TrustGuard checks claims against evidence, not against the truth label. This is a controlled simulation of one kind of unreliable agent, not proof of detecting every compromised agent.

## Calibration

| Confidence bin | n | Mean confidence | Actual accuracy |
|---|---|---|---|
| 0.45-0.65 | 30 | 0.57 | 1.00 |
| 0.65-0.80 | 104 | 0.76 | 1.00 |
| 0.80-0.90 | 92 | 0.84 | 1.00 |
| 0.90-1.00 | 58 | 0.90 | 1.00 |

## Per class (true root cause)

Recall = share of the cause's incidents diagnosed correctly; precision = share of committed predictions of that cause that were right; *confused with* lists wrong committed causes (abstentions are counted separately).

| Cause | n | Recall | Precision | Abstained | Confused with |
|---|---|---|---|---|---|
| device_overload | 39 | 74% | 100% | 10 | none |
| dhcp_failure | 29 | 100% | 100% | 0 | none |
| dns_failure | 20 | 100% | 100% | 0 | none |
| hardware_failure | 23 | 78% | 100% | 5 | none |
| healthy | 58 | 100% | 100% | 0 | none |
| interface_fault | 78 | 100% | 100% | 0 | none |
| link_congestion | 28 | 96% | 100% | 1 | none |
| weak_wifi | 25 | 100% | 100% | 0 | none |

## Per scenario

| Scenario | n | Accuracy | Abstained |
|---|---|---|---|
| conflicting_evidence | 24 | 100% | 0 |
| device_overload | 39 | 74% | 10 |
| dhcp_failure | 29 | 100% | 0 |
| dns_failure | 20 | 100% | 0 |
| hardware_failure | 23 | 78% | 5 |
| interface_fault | 32 | 100% | 0 |
| link_congestion | 28 | 96% | 1 |
| normal | 58 | 100% | 0 |
| trend_interface_errors | 22 | 100% | 0 |
| weak_wifi | 25 | 100% | 0 |

## Ablation: does the multi-agent design matter?

| Configuration | Accuracy | Selective acc. | Abstain | Confident-wrong |
|---|---|---|---|---|
| all 3 specialists + correlation | 94.7% | 100.0% | 5.3% | 0.0% |
| without performance_agent | 90.0% | 100.0% | 10.0% | 0.0% |
| without infrastructure_agent | 50.0% | 84.3% | 40.7% | 0.0% |
| without connectivity_agent | 66.3% | 100.0% | 33.7% | 0.0% |
| performance_agent only | 23.0% | 81.2% | 71.7% | 0.0% |
| infrastructure_agent only | 56.7% | 100.0% | 43.3% | 0.0% |
| connectivity_agent only | 43.7% | 100.0% | 56.3% | 0.0% |
