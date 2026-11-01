# ProofTrace INC-CONFLICTING_EVIDENCE

**Conclusion:** Possible Ethernet/interface fault (errors and link instability) on DEPT_SW_01 (status `tentative`, confidence 0.61)  
**Independent verification:** 42/42 checks passed  
**Log integrity:** 32 messages, chain sha256 `9d7759ce1f22eae3...`

## Competing hypotheses

| Hypothesis | Verdict | Score | Votes | Support | Contradicting | Missing |
|---|---|---|---|---|---|---|
| interface_fault | selected | 0.66 | infrastructure 0.73 | E1, E2, E4, E5, E6 | 0 | - |
| link_congestion | rejected | 0.46 | performance 0.69 | E1, E2, E3, E6 | 1 | - |
| weak_wifi | not supported | 0.00 |  | E1, E2, E6 | 0 | wifi_rssi_dbm, retransmission_pct |
| device_overload | not supported | 0.00 |  | E1, E2, E6 | 1 | - |
| hardware_failure | not supported | 0.00 |  | E1, E2, E3, E4, E5, E6 | 2 | - |
| dns_failure | not supported | 0.00 |  | - | 3 | dns_failure_pct |
| dhcp_failure | not supported | 0.00 |  | - | 3 | dhcp_failure_pct |

### Why the alternatives were rejected

- **link_congestion**: fused score 0.46 vs 0.66 for interface_fault; explains 67% of the observed symptom strength, interface_fault explains 83%; expected queue_drops but queue_drops = 10.0 is below the warning onset

## Evidence provenance

| Id | Device | Signal | Value | Strength | From raw | Reported by |
|---|---|---|---|---|---|---|
| E1 | DEPT_SW_01 | high_jitter | 38.81 | 1.00 | median of 5 sample(s): #25.metrics.jitter_ms=38.81, #26.metrics.jitter_ms=41.72, #27.metrics.jitter_ms=38.1... | performance (9007d547d341) |
| E2 | DEPT_SW_01 | high_latency | 184.52 | 1.00 | median of 5 sample(s): #25.metrics.latency_ms=186.21, #26.metrics.latency_ms=187.58, #27.metrics.latency_ms=184.52... | performance (9007d547d341) |
| E3 | DEPT_SW_01 | high_utilization | 87.99 | 1.00 | median of 5 sample(s): #25.metrics.link_utilization_pct=87.99, #26.metrics.link_utilization_pct=86.85, #27.metrics.link_utilization_pct=88.83... | performance (9007d547d341) |
| E4 | DEPT_SW_01 | interface_errors | 399.0 | 1.00 | median of 5 sample(s): #25.metrics.interface_errors=406.0, #26.metrics.interface_errors=399.0, #27.metrics.interface_errors=393.0... | infrastructure (9007d547d341) |
| E5 | DEPT_SW_01 | link_flaps | 5.0 | 1.00 | median of 5 sample(s): #25.metrics.link_flaps=5.0, #26.metrics.link_flaps=5.0, #27.metrics.link_flaps=5.0... | infrastructure (9007d547d341) |
| E6 | DEPT_SW_01 | packet_loss | 4.01 | 1.00 | median of 5 sample(s): #25.metrics.packet_loss_pct=3.96, #26.metrics.packet_loss_pct=4.13, #27.metrics.packet_loss_pct=4.17... | performance (9007d547d341) |

## Agent contributions (leave-one-out re-correlation of logged findings)

| Agent | Transport | Health | Top vote on root | Without it | Contribution |
|---|---|---|---|---|---|
| performance_agent | in-process | ok | link_congestion 0.69 | diagnosed / interface_fault 0.73 | dissenting (outvoted) |
| infrastructure_agent | in-process | ok | interface_fault 0.73 | tentative / link_congestion 0.60 | decisive |
| connectivity_agent | in-process | ok | - | tentative / interface_fault 0.56 | corroborating |
| correlation_agent | in-process | ok | - | - | - |
| reporting_agent | in-process | ok | - | - | - |
| trustguard | in-process | ok | - | - | - |

## What would change the diagnosis

What-if engine reproduces the conclusion: yes

- **FLIPS**: interface_errors on DEPT_SW_01: 399.0 -> 8.0 (below warning onset) -> tentative link_congestion (0.53)
- **FLIPS**: packet_loss_pct on DEPT_SW_01: 4.01 -> 0.4 (below warning onset) -> insufficient_evidence interface_fault (0.25)
- **FLIPS**: queue_drops on DEPT_SW_01: 10.0 -> 100 (at alarm level) -> tentative link_congestion (0.62)

## Missing information

- wifi_rssi_dbm on DEPT_SW_01: decides weak_wifi
- retransmission_pct on DEPT_SW_01: decides weak_wifi

## TrustGuard audit

95 claims checked against the telemetry: 95 accepted, 0 flagged, 0 unverifiable.


Without TrustGuard: tentative interface_fault (0.61); with TrustGuard: tentative interface_fault (0.61). Diagnosis changed: no.

Audit message `9007d547d341`; SHA-256 digests show that the audit and the findings were not altered after the run; they do not authenticate who wrote a message (no signatures).

