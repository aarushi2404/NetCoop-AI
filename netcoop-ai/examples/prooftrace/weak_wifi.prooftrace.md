# ProofTrace INC-WEAK_WIFI

**Conclusion:** Likely weak Wi-Fi signal causing retransmissions and packet loss on HOSTEL_AP_02 (status `diagnosed`, confidence 0.81)  
**Independent verification:** 40/40 checks passed  
**Log integrity:** 26 messages, chain sha256 `7b3bf508d4ab3e4b...`

## Competing hypotheses

| Hypothesis | Verdict | Score | Votes | Support | Contradicting | Missing |
|---|---|---|---|---|---|---|
| weak_wifi | selected | 0.81 | performance 0.25, connectivity 0.78 | E1, E2, E3, E4, E5 | 0 | - |
| interface_fault | rejected | 0.13 | performance 0.25 | E1, E2, E3 | 1 | - |
| device_overload | rejected | 0.10 | performance 0.20 | E1, E2, E3 | 1 | - |
| link_congestion | not supported | 0.00 |  | E1, E2, E3 | 2 | - |
| hardware_failure | not supported | 0.00 |  | E1, E2, E3 | 3 | - |
| dns_failure | not supported | 0.00 |  | - | 2 | - |
| dhcp_failure | not supported | 0.00 |  | - | 2 | - |

### Why the alternatives were rejected

- **interface_fault**: fused score 0.13 vs 0.81 for weak_wifi; explains 58% of the observed symptom strength, weak_wifi explains 100%; expected interface_errors but interface_errors = 0.0 is below the warning onset; only voted for by agents that cannot observe this cause directly (weight 0.7)
- **device_overload**: fused score 0.10 vs 0.81 for weak_wifi; explains 58% of the observed symptom strength, weak_wifi explains 100%; expected high_cpu but cpu_utilization_pct = 21.89 is below the warning onset; only voted for by agents that cannot observe this cause directly (weight 0.7)

## Evidence provenance

| Id | Device | Signal | Value | Strength | From raw | Reported by |
|---|---|---|---|---|---|---|
| E1 | HOSTEL_AP_02 | high_jitter | 45.6 | 1.00 | median of 5 sample(s): #15.metrics.jitter_ms=46.87, #16.metrics.jitter_ms=47.14, #17.metrics.jitter_ms=43.41... | performance (b9fe5e807a65) |
| E2 | HOSTEL_AP_02 | high_latency | 89.26 | 0.79 | median of 5 sample(s): #15.metrics.latency_ms=89.26, #16.metrics.latency_ms=92.15, #17.metrics.latency_ms=85.8... | performance (b9fe5e807a65) |
| E3 | HOSTEL_AP_02 | packet_loss | 3.07 | 1.00 | median of 5 sample(s): #15.metrics.packet_loss_pct=3.15, #16.metrics.packet_loss_pct=3.11, #17.metrics.packet_loss_pct=3.04... | performance (b9fe5e807a65) |
| E4 | HOSTEL_AP_02 | retransmissions | 21.79 | 1.00 | median of 5 sample(s): #15.metrics.retransmission_pct=21.79, #16.metrics.retransmission_pct=22.67, #17.metrics.retransmission_pct=21.74... | connectivity (b9fe5e807a65) |
| E5 | HOSTEL_AP_02 | weak_signal | -80.27 | 1.00 | median of 5 sample(s): #15.metrics.wifi_rssi_dbm=-81.52, #16.metrics.wifi_rssi_dbm=-81.36, #17.metrics.wifi_rssi_dbm=-80.27... | connectivity (b9fe5e807a65) |

## Agent contributions (leave-one-out re-correlation of logged findings)

| Agent | Transport | Health | Top vote on root | Without it | Contribution |
|---|---|---|---|---|---|
| performance_agent | in-process | ok | interface_fault 0.25 | diagnosed / weak_wifi 0.78 | dissenting (outvoted) |
| infrastructure_agent | in-process | ok | - | diagnosed / weak_wifi 0.81 | redundant |
| connectivity_agent | in-process | ok | weak_wifi 0.78 | insufficient_evidence / interface_fault 0.00 | decisive |
| correlation_agent | in-process | ok | - | - | - |
| reporting_agent | in-process | ok | - | - | - |
| trustguard | in-process | ok | - | - | - |

## What would change the diagnosis

What-if engine reproduces the conclusion: yes

- holds: wifi_rssi_dbm on HOSTEL_AP_02: -80.27 -> -61 (below warning onset) -> tentative weak_wifi (0.47)
- holds: retransmission_pct on HOSTEL_AP_02: 21.79 -> 6.4 (below warning onset) -> tentative weak_wifi (0.50)
- holds: interface_errors on HOSTEL_AP_02: 0.0 -> 50 (at alarm level) -> diagnosed weak_wifi (0.68)
- holds: cpu_utilization_pct on HOSTEL_AP_02: 21.89 -> 90 (at alarm level) -> diagnosed weak_wifi (0.68)
- holds: latency_ms on HOSTEL_AP_02: 89.26 -> 100 (at alarm level) -> diagnosed weak_wifi (0.81)

## TrustGuard audit

96 claims checked against the telemetry: 96 accepted, 0 flagged, 0 unverifiable.


Without TrustGuard: diagnosed weak_wifi (0.81); with TrustGuard: diagnosed weak_wifi (0.81). Diagnosis changed: no.

Audit message `b9fe5e807a65`; SHA-256 digests show that the audit and the findings were not altered after the run; they do not authenticate who wrote a message (no signatures).

