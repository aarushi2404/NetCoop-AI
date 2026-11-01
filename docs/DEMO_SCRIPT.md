# Demo script (about 5 minutes)

Setup once: `pip install -r requirements.txt`, then `python -m netcoop generate`, `python -m netcoop benchmark` (dev, held-out and stress sets), `python -m netcoop organizer-eval --sweep 5`, `python -m netcoop interop-demo`
Build the web UI once (in `web/`: `npm install`, then `npm run build`), run `python -m netcoop serve-api` in one terminal and open
http://127.0.0.1:8000; keep a second terminal open. Ctrl+K (or the search icon) picks an incident; the settings button
injects agent faults (including *adversarial*). The right-hand panel on the Investigation view has the
Remediation and ProofTrace (tamper and re-verify) tabs.

**One-line pitch:** "Anyone can prompt an LLM for a plausible root cause. We hand you a diagnosis whose
evidence, agent contributions, rejected alternatives and remediation outcome you can verify yourself."

**Opening: TrustGuard (about 75 s), in the web UI's TrustGuard view.**

| Time | Show | Say |
|---|---|---|
| 0:00 | **TrustGuard** view: **Run adversarial-agent demo** | "A switch is failing: CPU 99.9 %, 300 interface errors, Critical. We made the performance agent lie: it claims congestion with 0.99 certainty. Its evidence stays truthful; only the vote is misleading." |
| 0:15 | Summary cards (the bell shows the flag as an alert) | "Before correlation, TrustGuard re-derived every signal from the telemetry and checked all 106 claims. One flagged, 105 accepted, including 38 from the same agent." |
| 0:30 | The flagged claim (expanded in the Agent audit table) | "Why: a confident congestion vote needs a congestion indicator. Utilization is 40 %, strength 0.00, and the agent's own report says the same. Here is the raw telemetry, the message ID, and the effect: removed before correlation." |
| 0:45 | Before/after panel | "Without the audit: hardware failure at 0.80. With it: 0.85, the same as an all-honest run. On a milder incident the same lie flips the diagnosis to congestion; the benchmark shows it corrupts 14 to 39 correct answers out of 300, and with TrustGuard 0 to 1. Zero false alarms on 85,938 honest claims." |
| 1:00 | Investigation view, right panel -> ProofTrace -> *Alter a TrustGuard record* | "Every audit decision is in ProofTrace, and the verifier re-runs the audit from the raw input. Edit one record and verification fails." |

**Then the ProofTrace walkthrough below (timings shift by about 75 s; trim the organizer or interop segment if needed).**

| Time | Show | Say |
|---|---|---|
| 0:00 | Investigation view, `hardware_failure` (Ctrl+K), header and right panel | "Five agents diagnose: likely hardware failure on DEPT_SW_01, 0.80. The green bar is ProofTrace: 53 independent checks passed, 8 of them on the TrustGuard audit, and the remediation test agrees." |
| 0:20 | **ProofTrace** view: hypothesis board + evidence matrix | "All seven causes, not just the winner. Congestion was proposed by the performance agent and rejected: it explains 62 % of the symptom strength, hardware failure 100 %. Red cells are expected signals that are absent, '?' is what we never measured." |
| 0:50 | Evidence provenance: pick `high_cpu` | "Click any piece of evidence: input record #25, field `metrics.cpu_utilization_pct`, raw value, median of five samples, onset 70, alarm 90, strength 1.0, reported by the infrastructure agent, with the message id you can open. Every step is checkable." |
| 1:15 | Agent contributions + What would change | "Leave-one-out on the logged findings: without the infrastructure agent we would wrongly say congestion, so it is decisive. The performance agent dissented and was outvoted. And these three single measurements would flip the diagnosis: that is exactly what a technician should double-check." |
| 1:45 | Right panel -> ProofTrace -> *Change a vote* | "The verifier trusts nothing from the run. Change one vote in the log: digest, chain and cited-vote checks fail. Same for altering one telemetry value." |
| 2:05 | Terminal: `python -m netcoop prooftrace data/scenarios/hardware_failure.json --out-dir out` then the printed `verify-trace` command | "Four files you can take away and verify on your own machine: 53/53 VERIFIED." |
| 2:25 | Right panel -> **Remediation**: choose the congestion fix, Apply | "Counterfactual remediation: apply the *wrong* fix to a copy of the telemetry and re-diagnose. UNRESOLVED: CPU, interface errors and Critical status remain. The correct fix resolves it. Only the selected hypothesis' fix works, which is behavioural evidence for the diagnosis." Set efficacy 0.4 -> "a half-working fix is also reported as unresolved." |
| 2:55 | Scenario `latency_spike` (Ctrl+K), ProofTrace view: missing information and gates | "When evidence is weak we abstain, and say which gates failed and which measurement on which device would decide it." |
| 3:15 | Ctrl+K -> **Organizer data**, pick an `ORG-7-...` incident | "This is the organizers' own generator notebook, loaded and called directly, not our data. 40 incidents: no false diagnoses, latency spikes correctly left without a root cause, ProofTrace verified on all 40." |
| 3:40 | Terminal: `python -m netcoop interop-demo` | "A foreign HTTP agent with its own format. We discover it, negotiate a format, validate every reply item. A version-2-only agent is rejected at handshake with the reason; garbage, timeouts and 503s are contained. When it works, its findings are decisive for the Wi-Fi diagnosis." |
| 4:10 | **Benchmarks** view | "Internal data: 94.7 % accuracy, up from 88.7 % after replacing rigid thresholds with graded signals; zero confident errors; 93.0 % on a held-out seed we never looked at. On a harder stress set it drops to 71 %, almost all of it honest abstention, with 1 % wrong commitments. None of this is real-world accuracy. Organizer data is reported separately. Remove the infrastructure agent and accuracy halves." |
| 4:40 | Terminal: `python -m pytest -q` | "244 tests, including tamper detection, 300-case fuzzing, every interop failure mode, and proof that an agent sending invalid findings cannot change the diagnosis." |

## Likely judge questions

* **"Isn't ProofTrace just a nicer explanation?"** No: it is regenerated from the message log, every number is re-derivable, and `verify-trace` fails if the trace, the log or the input is altered. What-if and leave-one-out re-run the real logic.
* **"Is the confidence calibrated?"** It is an evidence score that drives the diagnosed / tentative / abstain decision, not a probability. Under-confident on our data (stated 0.57-0.90, actual ~1.0, ECE 0.21). We prefer that direction; a calibration map should be fitted on real labelled incidents, not on our own synthetic data.
* **"Is 94.7 % real-world accuracy?"** No. Our generator measures robustness to noise, dropout and mild faults on one 7-device topology. The held-out seed has the same distribution; the stress set (71 %, mostly abstentions) shows what happens when faults are faint. The organizer data is independent but its three profiles are easy to separate.
* **"Isn't TrustGuard just punishing agents that disagree?"** No. It never sees the leading hypothesis or other agents' votes. It only checks each claim against the telemetry and the agent's own card. In `conflicting_evidence` the agents disagree and nothing is flagged. Missing data gives *unverifiable*, never *flagged*.
* **"Does it catch every compromised agent?"** No. It catches claims the telemetry contradicts. A lie that the data happens to support passes (about 6 % of the infrastructure-agent lies in the benchmark). The adversarial mode is our own controlled simulation.
* **"Is TrustGuard tuned to the benchmark?"** Its bounds come from the signal definitions, with one fixed tolerance each. They were checked on honest runs for false alarms (0 of 85,938) and never fitted to make the adversarial numbers look good.
* **"Do the agents run in parallel?"** No, sequentially in a fixed order. They are independent, so they could; we keep the order fixed so the message log and its hash chain are reproducible.
* **"Did you overfit the threshold change?"** Onsets are standard warning levels, weights unchanged, and the gain holds on seed 2 (89.7 -> 94.3 %) and on held-out seed 3 (93.0 %).
* **"Why rules and not an LLM?"** Deterministic, replayable and verifiable. An LLM could narrate the ProofTrace, but it must not be the source of the diagnosis.
* **"Where does it fail?"** Mild overloads (CPU 66-80 %) are abstained on; most of the time the leading hypothesis is right but the gates hold. A two-cause device (`conflicting_evidence`) is only tentative, and the remediation check says no single fix resolves it.
