# ProofTrace INC-ADVERSARIAL_AGENT

**Conclusion:** Likely hardware failure on DEPT_SW_01 (status `diagnosed`, confidence 0.85)  
**Independent verification:** 50/50 checks passed  
**Log integrity:** 26 messages, chain sha256 `740b92307c179de6...`

## Competing hypotheses

| Hypothesis | Verdict | Score | Votes | Support | Contradicting | Missing |
|---|---|---|---|---|---|---|
| hardware_failure | selected | 0.85 | infrastructure 0.85 | E1, E2, E3, E4, E5, E6, E7 | 0 | - |
| device_overload | rejected | 0.53 | performance 0.20, infrastructure 0.60 | E2, E3, E4, E6, E7 | 0 | - |
| interface_fault | rejected | 0.49 | performance 0.25, infrastructure 0.55 | E3, E4, E5, E6 | 0 | - |
| link_congestion | rejected | 0.10 | infrastructure 0.14 | E3, E4, E6, E7 | 1 | - |
| weak_wifi | not supported | 0.00 |  | E3, E4, E6 | 0 | wifi_rssi_dbm, retransmission_pct |
| dns_failure | not supported | 0.00 |  | - | 2 | dns_failure_pct |
| dhcp_failure | not supported | 0.00 |  | - | 2 | dhcp_failure_pct |

### Why the alternatives were rejected

- **device_overload**: fused score 0.53 vs 0.85 for hardware_failure; explains 68% of the observed symptom strength, hardware_failure explains 100%
- **interface_fault**: fused score 0.49 vs 0.85 for hardware_failure; explains 64% of the observed symptom strength, hardware_failure explains 100%
- **link_congestion**: fused score 0.10 vs 0.85 for hardware_failure; explains 52% of the observed symptom strength, hardware_failure explains 100%; expected high_utilization but link_utilization_pct = 40.22 is below the warning onset

## Evidence provenance

| Id | Device | Signal | Value | Strength | From raw | Reported by |
|---|---|---|---|---|---|---|
| E1 | DEPT_SW_01 | device_critical | Critical | 1.00 | latest known status: #25.status=Critical, #26.status=Critical, #27.status=Critical... | infrastructure (1ae09ceccbf4) |
| E2 | DEPT_SW_01 | high_cpu | 99.0 | 1.00 | median of 5 sample(s): #25.metrics.cpu_utilization_pct=100.0, #26.metrics.cpu_utilization_pct=99.0, #27.metrics.cpu_utilization_pct=100.0... | infrastructure (1ae09ceccbf4) |
| E3 | DEPT_SW_01 | high_jitter | 60.82 | 1.00 | median of 5 sample(s): #25.metrics.jitter_ms=59.05, #26.metrics.jitter_ms=57.49, #27.metrics.jitter_ms=62.45... | performance (1ae09ceccbf4) |
| E4 | DEPT_SW_01 | high_latency | 433.8 | 1.00 | median of 5 sample(s): #25.metrics.latency_ms=435.97, #26.metrics.latency_ms=433.8, #27.metrics.latency_ms=429.72... | performance (1ae09ceccbf4) |
| E5 | DEPT_SW_01 | interface_errors | 302.0 | 1.00 | median of 5 sample(s): #25.metrics.interface_errors=308.0, #26.metrics.interface_errors=302.0, #27.metrics.interface_errors=299.0... | infrastructure (1ae09ceccbf4) |
| E6 | DEPT_SW_01 | packet_loss | 9.27 | 1.00 | median of 5 sample(s): #25.metrics.packet_loss_pct=8.88, #26.metrics.packet_loss_pct=9.03, #27.metrics.packet_loss_pct=9.44... | performance (1ae09ceccbf4) |
| E7 | DEPT_SW_01 | queue_drops | 40.0 | 0.25 | median of 5 sample(s): #25.metrics.queue_drops=40.0, #26.metrics.queue_drops=41.0, #27.metrics.queue_drops=38.0... | infrastructure (1ae09ceccbf4) |

## Agent contributions (leave-one-out re-correlation of logged findings)

| Agent | Transport | Health | Top vote on root | Without it | Contribution |
|---|---|---|---|---|---|
| performance_agent | in-process | ok | interface_fault 0.25 | diagnosed / hardware_failure 0.85 | dissenting (outvoted) |
| infrastructure_agent | in-process | ok | hardware_failure 0.85 | insufficient_evidence / interface_fault 0.06 | decisive |
| connectivity_agent | in-process | ok | - | diagnosed / hardware_failure 0.85 | redundant |
| correlation_agent | in-process | ok | - | - | - |
| reporting_agent | in-process | ok | - | - | - |
| trustguard | in-process | ok | - | - | - |

## What would change the diagnosis

What-if engine reproduces the conclusion: yes

- **FLIPS**: cpu_utilization_pct on DEPT_SW_01: 99.0 -> 56.0 (below warning onset) -> tentative interface_fault (0.51)
- **FLIPS**: interface_errors on DEPT_SW_01: 302.0 -> 8.0 (below warning onset) -> tentative device_overload (0.58)
- **FLIPS**: status on DEPT_SW_01: Critical -> Warning (status not Critical) -> tentative device_overload (0.47)

## TrustGuard audit

106 claims checked against the telemetry: 105 accepted, 1 flagged, 0 unverifiable.

- **TG-030** performance_agent vote `link_congestion` = 0.99 on DEPT_SW_01: UNSUPPORTED_CERTAINTY, SELF_CONTRADICTION. performance_agent votes link_congestion=0.99 on DEPT_SW_01; strongest observable symptom high_jitter=1.00; cause-specific indicators high_utilization=0.00; its own report gives high_utilization=0.00

Without TrustGuard: diagnosed hardware_failure (0.80); with TrustGuard: diagnosed hardware_failure (0.85). Diagnosis changed: no.

Audit message `1ae09ceccbf4`; SHA-256 digests show that the audit and the findings were not altered after the run; they do not authenticate who wrote a message (no signatures).

