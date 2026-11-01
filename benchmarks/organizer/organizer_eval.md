# Evaluation on organizer-generated data

Generator: `data/organizer/mock-data-builder-netScoopAI.ipynb` -> `generate_telemetry()` (fault types discovered from the notebook: hardware_failure, latency_spike, normal). 40 incidents, seed 7. **This data was not produced by our generator and was not used to tune NetCoop.**

Adaptations: records grouped into incidents of 2-5 devices x 3-5 samples; device_id made consistent per device (generator's random id kept as generator_device_id); one faulty device per incident, the rest generated with fault_type='normal'; seeded random and a deterministic clock injected for reproducibility; no topology given (the notebook has none).

Ground truth mapping: `normal` -> healthy, `hardware_failure` -> hardware_failure on the faulty device, `latency_spike` -> symptom only: correct = faulty device detected and *no* root cause committed.

## Clean incidents

| Metric | Value |
|---|---|
| Accuracy | 100.0% |
| False diagnoses (committed to a wrong cause/device, or a fault on a healthy network) | 0.0% |
| Abstention rate | 32.5% |
| Faulty device detected (non-normal incidents) | 100.0% |
| False alarms on normal incidents | 0.0% |
| ProofTrace independently verified | 40/40 |

| Organizer label | n | Accuracy | Outcomes | Status |
|---|---|---|---|---|
| hardware_failure | 14 | 100% | correct 14 | diagnosed 14 |
| latency_spike | 13 | 100% | correct 13 | insufficient_evidence 13 |
| normal | 13 | 100% | correct 13 | healthy 13 |

Calibration on committed diagnoses (ECE 0.230): 0.65-0.80: n=14, conf 0.77, acc 1.00

## Stressed incidents (20 % metrics dropped, stale sample, junk value)

| Metric | Value |
|---|---|
| Accuracy | 100.0% |
| False diagnoses (committed to a wrong cause/device, or a fault on a healthy network) | 0.0% |
| Abstention rate | 32.5% |
| Faulty device detected (non-normal incidents) | 100.0% |
| False alarms on normal incidents | 0.0% |
| ProofTrace independently verified | 40/40 |

| Organizer label | n | Accuracy | Outcomes | Status |
|---|---|---|---|---|
| hardware_failure | 14 | 100% | correct 14 | diagnosed 14 |
| latency_spike | 13 | 100% | correct 13 | insufficient_evidence 13 |
| normal | 13 | 100% | correct 13 | healthy 13 |

Calibration on committed diagnoses (ECE 0.230): 0.65-0.80: n=14, conf 0.77, acc 1.00

## Stability across independent seeds (clean incidents)

| Seed | Accuracy | False diagnoses | Abstention | Detection | Outcomes | ProofTrace verified |
|---|---|---|---|---|---|---|
| 1 | 97.5% | 0.0% | 30.0% | 100.0% | correct 39, hedged 1 | 40/40 |
| 2 | 100.0% | 0.0% | 32.5% | 100.0% | correct 40 | 40/40 |
| 3 | 100.0% | 0.0% | 32.5% | 100.0% | correct 40 | 40/40 |
| 4 | 100.0% | 0.0% | 32.5% | 100.0% | correct 40 | 40/40 |
| 5 | 100.0% | 0.0% | 32.5% | 100.0% | correct 40 | 40/40 |

## How to read this

The organizer generator's profiles are far apart (hardware failure: CPU 99.9 %, latency 500-1000 ms, Critical status; latency_spike: no cause-specific signal at all), so high accuracy here mainly shows that NetCoop handles an external schema and does not over-claim a root cause for a bare latency symptom. It says little about hard borderline cases; those are covered by the internal benchmark, which varies fault severity down to 0.55x. Small n: one error moves accuracy by 2.5 points.

