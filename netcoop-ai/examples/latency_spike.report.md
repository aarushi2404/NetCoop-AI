# Incident INC-LATENCY_SPIKE: INSUFFICIENT EVIDENCE

**Suspected root cause:** Insufficient evidence for a reliable root-cause diagnosis  
**Confidence:** 0.00 (low)  
**Affected devices:** HOSTEL_CORE_SW_01

**ProofTrace:** 30/30 independent checks passed (`python -m netcoop prooftrace` for the full trace)

## Why the system does not commit

Leading hypothesis device_overload is not supported strongly enough. Most useful next measurement: packet_loss_pct on HOSTEL_CORE_SW_01.

- evidence strength: fused agent score for device_overload is 0.10 (need >= 0.65)
- verification against raw data: 1 of 2 expected signals fully present, 1 contradicted (need expected signals present)
- separation from runner-up: lead over the next hypothesis is 0.01 (need >= 0.15)

| Measure | On device | Status | Would decide |
|---|---|---|---|
| packet_loss_pct | HOSTEL_CORE_SW_01 | only elevated (20% of alarm level): re-sample over a longer window | interface_fault |

## Supporting evidence

| Device | Metric | Value | Interpretation |
|---|---|---|---|
| HOSTEL_CORE_SW_01 | jitter_ms | 53.77 | High jitter |
| HOSTEL_CORE_SW_01 | latency_ms | 263.43 | High network latency |
| HOSTEL_CORE_SW_01 | packet_loss_pct | 0.6 | Packet loss above tolerance: elevated, 20% of the way from warning onset (0.5) to alarm |

## Challenge round

Top hypotheses were close, so the correlation agent queried the specialist agents for graded signal strength on HOSTEL_CORE_SW_01. Margin 0.04 -> 0.01 (winner changed).

## What would raise confidence

- Explain why 'high_cpu' was not observed although expected
- Distinguish device_overload from interface_fault: check high_cpu, high_latency, interface_errors, packet_loss

## Recommended actions

- Collect additional telemetry (interface counters, queue stats, wireless and service metrics) for the affected devices
- Re-run the diagnosis once more data is available

## Limitations

- Evidence is not strong enough to claim a definitive root cause
- Root cause requires further verification on the device
- Expected signals not observed: high_cpu

## TrustGuard audit

92 claims checked against the telemetry: 92 accepted, 0 flagged, 0 unverifiable.


Without TrustGuard: insufficient_evidence device_overload (0.00); with TrustGuard: insufficient_evidence device_overload (0.00). Diagnosis changed: no.

## Confidence breakdown

```json
{
  "fused_score": 0.105,
  "verification_factor": 0.8,
  "ambiguity_penalty": 0.14,
  "conflict_penalty": 0.0,
  "data_quality_penalty": 0.0,
  "unverifiable_penalty": 0.0,
  "failed_agent_penalty": 0.0,
  "consistency_penalty": 0.0,
  "confidence_cap": 0.97
}
```

## Data quality

- Completeness: 100%
- Records accepted/rejected: 35/0
- Issues: 0 warning/error, 0 info

