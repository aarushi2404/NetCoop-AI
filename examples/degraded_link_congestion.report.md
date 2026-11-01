# Incident INC-LINK_CONGESTION: TENTATIVE

**Suspected root cause:** Possible link congestion causing egress queue drops and elevated latency on HOSTEL_CORE_SW_01  
**Confidence:** 0.59 (low)  
**Affected devices:** HOSTEL_CORE_SW_01, HOSTEL_AP_01, HOSTEL_AP_02, HOSTEL_AP_03

**ProofTrace:** 33/33 independent checks passed (`python -m netcoop prooftrace` for the full trace)

## Why the system does not commit

Leading hypothesis link_congestion is not supported strongly enough. No missing metric would decide it; the pattern matches no known fault.

- agent availability: infrastructure_agent (need 0 failed)

## Supporting evidence

| Device | Metric | Value | Interpretation |
|---|---|---|---|
| HOSTEL_CORE_SW_01 | jitter_ms | 44.79 | High jitter |
| HOSTEL_CORE_SW_01 | latency_ms | 275.87 | High network latency |
| HOSTEL_CORE_SW_01 | link_utilization_pct | 93.87 | High link utilization |
| HOSTEL_CORE_SW_01 | packet_loss_pct | 2.51 | Packet loss above tolerance |

## What would raise confidence

- Restore infrastructure_agent so its evidence can be included

## Recommended actions

- Inspect utilization of the affected link and its upstream uplink
- Review QoS / egress queue configuration and traffic distribution
- Identify top talkers; consider rate-limiting or adding capacity

## Limitations

- Evidence is not strong enough to claim a definitive root cause
- Root cause requires further verification on the device
- infrastructure_agent was unavailable; its evidence is missing and confidence is capped

## TrustGuard audit

68 claims checked against the telemetry: 68 accepted, 0 flagged, 0 unverifiable.


Without TrustGuard: tentative link_congestion (0.59); with TrustGuard: tentative link_congestion (0.59). Diagnosis changed: no.

## Confidence breakdown

```json
{
  "fused_score": 0.69,
  "verification_factor": 1.0,
  "ambiguity_penalty": 0.0,
  "conflict_penalty": 0.0,
  "data_quality_penalty": 0.0,
  "unverifiable_penalty": 0.0,
  "failed_agent_penalty": 0.1,
  "consistency_penalty": 0.0,
  "confidence_cap": 0.75
}
```

## Data quality

- Completeness: 100%
- Records accepted/rejected: 35/0
- Issues: 0 warning/error, 0 info

