# Incident INC-HARDWARE_FAILURE: DIAGNOSED

**Suspected root cause:** Likely hardware failure on DEPT_SW_01  
**Confidence:** 0.80 (high)  
**Affected devices:** DEPT_SW_01, LECTURE_AP_01

**ProofTrace:** 53/53 independent checks passed (`python -m netcoop prooftrace` for the full trace)

## Supporting evidence

| Device | Metric | Value | Interpretation |
|---|---|---|---|
| DEPT_SW_01 | jitter_ms | 116.26 | High jitter |
| DEPT_SW_01 | latency_ms | 792.05 | High network latency |
| DEPT_SW_01 | link_utilization_pct | 99.55 | High link utilization |
| DEPT_SW_01 | packet_loss_pct | 22.21 | Packet loss above tolerance |
| DEPT_SW_01 | status | Critical | Device reports Critical status |
| DEPT_SW_01 | cpu_utilization_pct | 100.0 | Device CPU saturated |
| DEPT_SW_01 | interface_errors | 296.0 | Elevated interface errors |
| DEPT_SW_01 | queue_drops | 9006.0 | Elevated egress queue drops |

## Agent conflicts and resolution

- **performance_agent** favoured `link_congestion`: link_congestion (0.67, explains 62% of observed signals) was outranked by hardware_failure (0.85, explains 100%) after authority weighting and signal-coverage scoring

## Alternative explanations

- link_congestion (score 0.67)
- device_overload (score 0.47)
- interface_fault (score 0.39)

## What would raise confidence

- Distinguish hardware_failure from link_congestion: check high_cpu, interface_errors, device_critical, high_utilization, queue_drops, high_latency

## Recommended actions

- Check device health (fans, PSU, ASIC/line card logs) and plan a replacement
- Fail over traffic to a redundant path/device if available
- Raise a hardware RMA after confirming with the vendor diagnostics

## Limitations

- Root cause requires further verification on the device

## TrustGuard audit

105 claims checked against the telemetry: 105 accepted, 0 flagged, 0 unverifiable.


Without TrustGuard: diagnosed hardware_failure (0.80); with TrustGuard: diagnosed hardware_failure (0.80). Diagnosis changed: no.

## Confidence breakdown

```json
{
  "fused_score": 0.85,
  "verification_factor": 1.0,
  "ambiguity_penalty": 0.0,
  "conflict_penalty": 0.05,
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

