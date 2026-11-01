# Interoperability demo (weak_wifi incident, foreign HTTP connectivity agent)

| Foreign agent behaviour | Negotiation | Agent health | Diagnosis | Confidence | Remote contribution | Reply items rejected | ProofTrace |
|---|---|---|---|---|---|---|---|
| compatible service | compatible wlo-1 | ok | diagnosed weak_wifi | 0.81 | decisive | 0 | verified |
| only speaks wlo-2 (no common format) | incompatible  | incompatible | insufficient_evidence  | 0.00 | - | 0 | verified |
| returns non-JSON garbage | compatible wlo-1 | failed | insufficient_evidence  | 0.00 | - | 0 | verified |
| some reply items invalid | compatible wlo-1 | ok | diagnosed weak_wifi | 0.81 | decisive | 4 | verified |
| first call 503, then ok | compatible wlo-1 | recovered | diagnosed weak_wifi | 0.81 | decisive | 0 | verified |
| too slow (5 s > 1 s timeout) | compatible wlo-1 | failed | insufficient_evidence  | 0.00 | - | 0 | verified |
| service down | unreachable  | failed | insufficient_evidence  | 0.00 | - | 0 | verified |

Errors reported by the orchestrator:

- only speaks wlo-2 (no common format): format negotiation failed: no common format: remote speaks ['wlo-2'], adapter speaks ['wlo-1']
- returns non-JSON garbage: remote agent returned malformed JSON
- too slow (5 s > 1 s timeout): remote agent unreachable or timed out at http://127.0.0.1:64923: timed out
- service down: remote agent unreachable or timed out at http://127.0.0.1:9: <urlopen error [WinError 10061] No connection could be made because the target machine actively refused it>
