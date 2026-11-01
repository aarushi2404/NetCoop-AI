# Incident INC-CONFLICTING_EVIDENCE: TENTATIVE

**Suspected root cause:** Possible Ethernet/interface fault (errors and link instability) on DEPT_SW_01  
**Confidence:** 0.61 (medium)  
**Affected devices:** DEPT_SW_01

**ProofTrace:** 42/42 independent checks passed (`python -m netcoop prooftrace` for the full trace)

## Why the system does not commit

Leading hypothesis interface_fault is not supported strongly enough. No missing metric would decide it; the pattern matches no known fault.

- confidence below the commitment threshold

## Supporting evidence

| Device | Metric | Value | Interpretation |
|---|---|---|---|
| DEPT_SW_01 | jitter_ms | 38.81 | High jitter |
| DEPT_SW_01 | latency_ms | 184.52 | High network latency |
| DEPT_SW_01 | link_utilization_pct | 87.99 | High link utilization |
| DEPT_SW_01 | packet_loss_pct | 4.01 | Packet loss above tolerance |
| DEPT_SW_01 | interface_errors | 399.0 | Elevated interface errors |
| DEPT_SW_01 | link_flaps | 5.0 | Unstable link (flapping) |

## Agent conflicts and resolution

- **performance_agent** favoured `link_congestion`: link_congestion (0.46, explains 67% of observed signals) was outranked by interface_fault (0.66, explains 83%) after authority weighting and signal-coverage scoring

## Challenge round

Top hypotheses were close, so the correlation agent queried the specialist agents for graded signal strength on DEPT_SW_01. Margin 0.10 -> 0.20.

## Alternative explanations

- link_congestion (score 0.46)

## What would raise confidence

- Distinguish interface_fault from link_congestion: check interface_errors, packet_loss, high_utilization, queue_drops, high_latency

## Recommended actions

- Check cabling, SFP/transceiver and port for the affected interface
- Review interface error counters (CRC, FCS) and link flap logs
- Swap the cable/port and re-measure; replace the module if errors persist

## Limitations

- Evidence is not strong enough to claim a definitive root cause
- Root cause requires further verification on the device

## TrustGuard audit

95 claims checked against the telemetry: 95 accepted, 0 flagged, 0 unverifiable.


Without TrustGuard: tentative interface_fault (0.61); with TrustGuard: tentative interface_fault (0.61). Diagnosis changed: no.

## Confidence breakdown

```json
{
  "fused_score": 0.657,
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

