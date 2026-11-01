# ProofTrace INC-HARDWARE_FAILURE

**Conclusion:** Likely hardware failure on DEPT_SW_01 (status `diagnosed`, confidence 0.80)  
**Independent verification:** 53/53 checks passed  
**Log integrity:** 26 messages, chain sha256 `6150f8a4ccc0adb6...`

## Competing hypotheses

| Hypothesis | Verdict | Score | Votes | Support | Contradicting | Missing |
|---|---|---|---|---|---|---|
| hardware_failure | selected | 0.85 | infrastructure 0.85 | E1, E2, E3, E4, E5, E6, E7, E8 | 0 | - |
| link_congestion | rejected | 0.67 | performance 0.69, infrastructure 0.55 | E3, E4, E5, E7, E8 | 0 | - |
| device_overload | rejected | 0.47 | infrastructure 0.60 | E2, E3, E4, E7, E8 | 0 | - |
| interface_fault | rejected | 0.39 | infrastructure 0.55 | E3, E4, E6, E7 | 0 | - |
| weak_wifi | not supported | 0.00 |  | E3, E4, E7 | 0 | wifi_rssi_dbm, retransmission_pct |
| dns_failure | not supported | 0.00 |  | - | 3 | dns_failure_pct |
| dhcp_failure | not supported | 0.00 |  | - | 3 | dhcp_failure_pct |

### Why the alternatives were rejected

- **link_congestion**: fused score 0.67 vs 0.85 for hardware_failure; explains 62% of the observed symptom strength, hardware_failure explains 100%
- **device_overload**: fused score 0.47 vs 0.85 for hardware_failure; explains 62% of the observed symptom strength, hardware_failure explains 100%
- **interface_fault**: fused score 0.39 vs 0.85 for hardware_failure; explains 50% of the observed symptom strength, hardware_failure explains 100%

## Evidence provenance

| Id | Device | Signal | Value | Strength | From raw | Reported by |
|---|---|---|---|---|---|---|
| E1 | DEPT_SW_01 | device_critical | Critical | 1.00 | latest known status: #25.status=Critical, #26.status=Critical, #27.status=Critical... | infrastructure (c8068959c3bf) |
| E2 | DEPT_SW_01 | high_cpu | 100.0 | 1.00 | median of 5 sample(s): #25.metrics.cpu_utilization_pct=100.0, #26.metrics.cpu_utilization_pct=95.96, #27.metrics.cpu_utilization_pct=97.31... | infrastructure (c8068959c3bf) |
| E3 | DEPT_SW_01 | high_jitter | 116.26 | 1.00 | median of 5 sample(s): #25.metrics.jitter_ms=115.06, #26.metrics.jitter_ms=114.42, #27.metrics.jitter_ms=121.0... | performance (c8068959c3bf) |
| E4 | DEPT_SW_01 | high_latency | 792.05 | 1.00 | median of 5 sample(s): #25.metrics.latency_ms=818.3, #26.metrics.latency_ms=764.16, #27.metrics.latency_ms=774.44... | performance (c8068959c3bf) |
| E5 | DEPT_SW_01 | high_utilization | 99.55 | 1.00 | median of 5 sample(s): #25.metrics.link_utilization_pct=99.55, #26.metrics.link_utilization_pct=100.0, #27.metrics.link_utilization_pct=94.86... | performance (c8068959c3bf) |
| E6 | DEPT_SW_01 | interface_errors | 296.0 | 1.00 | median of 5 sample(s): #25.metrics.interface_errors=302.0, #26.metrics.interface_errors=290.0, #27.metrics.interface_errors=296.0... | infrastructure (c8068959c3bf) |
| E7 | DEPT_SW_01 | packet_loss | 22.21 | 1.00 | median of 5 sample(s): #25.metrics.packet_loss_pct=21.7, #26.metrics.packet_loss_pct=23.03, #27.metrics.packet_loss_pct=22.46... | performance (c8068959c3bf) |
| E8 | DEPT_SW_01 | queue_drops | 9006.0 | 1.00 | median of 5 sample(s): #25.metrics.queue_drops=9198.0, #26.metrics.queue_drops=8862.0, #27.metrics.queue_drops=9006.0... | infrastructure (c8068959c3bf) |

## Agent contributions (leave-one-out re-correlation of logged findings)

| Agent | Transport | Health | Top vote on root | Without it | Contribution |
|---|---|---|---|---|---|
| performance_agent | in-process | ok | link_congestion 0.69 | diagnosed / hardware_failure 0.85 | dissenting (outvoted) |
| infrastructure_agent | in-process | ok | hardware_failure 0.85 | diagnosed / link_congestion 0.69 | decisive |
| connectivity_agent | in-process | ok | - | diagnosed / hardware_failure 0.80 | redundant |
| correlation_agent | in-process | ok | - | - | - |
| reporting_agent | in-process | ok | - | - | - |
| trustguard | in-process | ok | - | - | - |

## What would change the diagnosis

What-if engine reproduces the conclusion: yes

- **FLIPS**: cpu_utilization_pct on DEPT_SW_01: 100.0 -> 56.0 (below warning onset) -> diagnosed link_congestion (0.71)
- **FLIPS**: interface_errors on DEPT_SW_01: 296.0 -> 8.0 (below warning onset) -> diagnosed link_congestion (0.66)
- **FLIPS**: status on DEPT_SW_01: Critical -> Warning (status not Critical) -> diagnosed link_congestion (0.66)

## TrustGuard audit

105 claims checked against the telemetry: 105 accepted, 0 flagged, 0 unverifiable.


Without TrustGuard: diagnosed hardware_failure (0.80); with TrustGuard: diagnosed hardware_failure (0.80). Diagnosis changed: no.

Audit message `c8068959c3bf`; SHA-256 digests show that the audit and the findings were not altered after the run; they do not authenticate who wrote a message (no signatures).

