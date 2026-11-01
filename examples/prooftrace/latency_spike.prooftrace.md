# ProofTrace INC-LATENCY_SPIKE

**Conclusion:** Insufficient evidence for a reliable root-cause diagnosis (status `insufficient_evidence`, confidence 0.00)  
**Independent verification:** 30/30 checks passed  
**Log integrity:** 32 messages, chain sha256 `4a9a2ef7d88c73e6...`

## Competing hypotheses

| Hypothesis | Verdict | Score | Votes | Support | Contradicting | Missing |
|---|---|---|---|---|---|---|
| device_overload | leading (not committed) | 0.10 | performance 0.20 | E1, E2, E3 | 1 | - |
| interface_fault | rejected | 0.10 | performance 0.25 | E1, E2, E3 | 1 | - |
| link_congestion | not supported | 0.00 |  | E1, E2, E3 | 2 | - |
| weak_wifi | not supported | 0.00 |  | E1, E2, E3 | 0 | wifi_rssi_dbm, retransmission_pct |
| hardware_failure | not supported | 0.00 |  | E1, E2, E3 | 3 | - |
| dns_failure | not supported | 0.00 |  | - | 1 | dns_failure_pct |
| dhcp_failure | not supported | 0.00 |  | - | 1 | dhcp_failure_pct |

### Why the alternatives were rejected

- **interface_fault**: fused score 0.10 vs 0.10 for device_overload; expected interface_errors but interface_errors = 0.0 is below the warning onset; only voted for by agents that cannot observe this cause directly (weight 0.7)

## Evidence provenance

| Id | Device | Signal | Value | Strength | From raw | Reported by |
|---|---|---|---|---|---|---|
| E1 | HOSTEL_CORE_SW_01 | high_jitter | 53.77 | 1.00 | median of 5 sample(s): #5.metrics.jitter_ms=53.77, #6.metrics.jitter_ms=52.35, #7.metrics.jitter_ms=54.58... | performance (0c27b619b0cf) |
| E2 | HOSTEL_CORE_SW_01 | high_latency | 263.43 | 1.00 | median of 5 sample(s): #5.metrics.latency_ms=251.27, #6.metrics.latency_ms=263.43, #7.metrics.latency_ms=252.5... | performance (0c27b619b0cf) |
| E3 | HOSTEL_CORE_SW_01 | packet_loss | 0.6 | 0.20 | median of 5 sample(s): #5.metrics.packet_loss_pct=0.59, #6.metrics.packet_loss_pct=0.6, #7.metrics.packet_loss_pct=0.6... | performance (0c27b619b0cf) |

## Agent contributions (leave-one-out re-correlation of logged findings)

| Agent | Transport | Health | Top vote on root | Without it | Contribution |
|---|---|---|---|---|---|
| performance_agent | in-process | ok | interface_fault 0.25 | insufficient_evidence / None 0.10 | decisive |
| infrastructure_agent | in-process | ok | - | insufficient_evidence / interface_fault 0.00 | decisive |
| connectivity_agent | in-process | ok | - | insufficient_evidence / interface_fault 0.00 | decisive |
| correlation_agent | in-process | ok | - | - | - |
| reporting_agent | in-process | ok | - | - | - |
| trustguard | in-process | ok | - | - | - |

## What would change the diagnosis

What-if engine reproduces the conclusion: yes

- **FLIPS**: latency_ms on HOSTEL_CORE_SW_01: 263.43 -> 40.0 (below warning onset) -> insufficient_evidence interface_fault (0.00)
- **FLIPS**: interface_errors on HOSTEL_CORE_SW_01: 0.0 -> 50 (at alarm level) -> tentative interface_fault (0.53)
- **FLIPS**: packet_loss_pct on HOSTEL_CORE_SW_01: 0.6 -> 1.0 (at alarm level) -> insufficient_evidence interface_fault (0.00)

## Missing information

- packet_loss_pct on HOSTEL_CORE_SW_01: decides interface_fault

## TrustGuard audit

92 claims checked against the telemetry: 92 accepted, 0 flagged, 0 unverifiable.


Without TrustGuard: insufficient_evidence device_overload (0.00); with TrustGuard: insufficient_evidence device_overload (0.00). Diagnosis changed: no.

Audit message `0c27b619b0cf`; SHA-256 digests show that the audit and the findings were not altered after the run; they do not authenticate who wrote a message (no signatures).

