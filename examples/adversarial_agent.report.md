# Incident INC-ADVERSARIAL_AGENT: DIAGNOSED

**Suspected root cause:** Likely hardware failure on DEPT_SW_01  
**Confidence:** 0.85 (high)  
**Affected devices:** DEPT_SW_01, LECTURE_AP_01

**ProofTrace:** 50/50 independent checks passed (`python -m netcoop prooftrace` for the full trace)

## Supporting evidence

| Device | Metric | Value | Interpretation |
|---|---|---|---|
| DEPT_SW_01 | jitter_ms | 60.82 | High jitter |
| DEPT_SW_01 | latency_ms | 433.8 | High network latency |
| DEPT_SW_01 | packet_loss_pct | 9.27 | Packet loss above tolerance |
| DEPT_SW_01 | status | Critical | Device reports Critical status |
| DEPT_SW_01 | cpu_utilization_pct | 99.0 | Device CPU saturated |
| DEPT_SW_01 | interface_errors | 302.0 | Elevated interface errors |
| DEPT_SW_01 | queue_drops | 40.0 | Elevated egress queue drops: elevated, 25% of the way from warning onset (20) to alarm |

## Alternative explanations

- device_overload (score 0.53)
- interface_fault (score 0.49)

## Recommended actions

- Check device health (fans, PSU, ASIC/line card logs) and plan a replacement
- Fail over traffic to a redundant path/device if available
- Raise a hardware RMA after confirming with the vendor diagnostics

## Limitations

- Root cause requires further verification on the device
- TrustGuard excluded 1 claim(s) contradicted by the telemetry (from performance_agent); see trustguard.flagged

## TrustGuard audit

106 claims checked against the telemetry: 105 accepted, 1 flagged, 0 unverifiable.

- **TG-030** performance_agent vote `link_congestion` = 0.99 on DEPT_SW_01: UNSUPPORTED_CERTAINTY, SELF_CONTRADICTION. performance_agent votes link_congestion=0.99 on DEPT_SW_01; strongest observable symptom high_jitter=1.00; cause-specific indicators high_utilization=0.00; its own report gives high_utilization=0.00

Without TrustGuard: diagnosed hardware_failure (0.80); with TrustGuard: diagnosed hardware_failure (0.85). Diagnosis changed: no.

## Confidence breakdown

```json
{
  "fused_score": 0.85,
  "verification_factor": 1.0,
  "ambiguity_penalty": 0.0,
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

