"""The five NetCoop agents. Each agent only talks in protocol envelopes.

 performance_agent     latency, jitter, loss, utilization         -> votes on hypotheses
 infrastructure_agent  queue drops, iface errors, flaps, CPU/mem  -> votes on hypotheses
 connectivity_agent    topology scope, Wi-Fi, DNS/DHCP           -> votes + scope analysis
 correlation_agent     fuses votes, resolves conflicts, verifies  -> diagnosis + confidence
 reporting_agent       builds the unified report
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .protocol import (CORE_METRICS, SUPPORTED_PROTOCOL_VERSIONS, AgentCard, Envelope, Finding,
                       make_envelope)
from .signals import (DOMAIN_SIGNALS, THRESHOLDS, derive_signals, derive_strengths, evidence_for,
                      is_degraded, signal_strength)

CONFIDENCE_DIAGNOSED = 0.65
CONFIDENCE_TENTATIVE = 0.45


def noisy_or(weights: list[float]) -> float:
    p = 1.0
    for w in weights:
        p *= 1.0 - w
    return round(1.0 - p, 4)


class BaseAgent:
    name = "base_agent"

    def __init__(self, fault: str | None = None):
        # fault injection for resilience demos: None | "transient" | "permanent" | "adversarial"
        # ("adversarial": the agent answers, but with one deliberately misleading vote; see AnalysisAgent)
        self.fault = fault
        self._calls = 0

    description = ""
    accepts: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    domain: str | None = None
    hypotheses: tuple[str, ...] = ()

    def card(self) -> dict:
        sigs = list(DOMAIN_SIGNALS.get(self.domain or "", ()))
        return AgentCard(agent=self.name, description=self.description, domain=self.domain,
                         protocol_versions=list(SUPPORTED_PROTOCOL_VERSIONS),
                         accepts=["capability_request", *self.accepts], produces=["capability_response", *self.produces],
                         hypotheses=list(self.hypotheses), signals=sigs).model_dump()

    def handle(self, env: Envelope) -> Envelope:
        if env.msg_type == "capability_request":   # discovery is answered even by a degraded agent
            return self._reply(env, "capability_response", self.card() | {"agent": self.name})
        self._calls += 1
        if self.fault == "permanent" or (self.fault == "transient" and self._calls == 1):
            raise RuntimeError(f"{self.name}: injected {self.fault} fault")
        return self._handle(env)

    def _handle(self, env: Envelope) -> Envelope:  # pragma: no cover
        raise NotImplementedError

    def _reply(self, env: Envelope, msg_type: str, payload: dict) -> Envelope:
        return make_envelope(self.name, env.sender, msg_type, payload, env.correlation_id)


# --------------------------------------------------------------------------- analysis agents
def is_wireless(dev: dict) -> bool:
    """Only a device that is (or reports like) an access point can have a Wi-Fi fault."""
    return dev.get("role") == "access_point" or any(
        m in dev.get("metrics", {}) for m in ("wifi_rssi_dbm", "retransmission_pct"))


class AnalysisAgent(BaseAgent):
    domain = ""

    def votes(self, st: dict[str, float], dev: dict) -> dict[str, float]:
        """`st` = graded strength (0-1) of every known signal in this agent's domain."""
        raise NotImplementedError

    def extra(self, devices: dict, topology: dict) -> dict:
        return {}

    def _handle(self, env: Envelope) -> Envelope:
        if env.msg_type == "challenge_request":
            return self._challenge(env)
        if env.msg_type != "analyze_request":
            raise ValueError(f"{self.name} cannot handle '{env.msg_type}'")
        devices = env.payload["devices"]
        findings = []
        for did, dev in devices.items():
            present, unknown = derive_signals(dev["metrics"], dev["status"], self.domain)
            st = derive_strengths(dev["metrics"], dev["status"], self.domain)
            notes = []
            if len(unknown) == len(DOMAIN_SIGNALS[self.domain]):
                notes.append(f"no {self.domain} metrics available for this device")
            elif unknown:
                notes.append("unverifiable signals (metric missing): " + ", ".join(sorted(unknown)))
            f = Finding(
                finding_id=f"{self.name}:{did}", agent=self.name, domain=self.domain,  # type: ignore[arg-type]
                device_id=did, votes={h: round(v, 4) for h, v in self.votes(st, dev).items() if v > 0},
                signals_present=sorted(present), signals_unknown=sorted(unknown), signal_strength=st,
                evidence=[evidence_for(s, did, dev["metrics"], dev["status"]) for s in sorted(st) if st[s] > 0],
                notes=notes)
            findings.append(f.model_dump())
        if self.fault == "adversarial":
            self._mislead(findings, devices)
        payload = {"agent": self.name, "domain": self.domain, "findings": findings,
                   **self.extra(devices, env.payload.get("topology", {}))}
        return self._reply(env, "finding_batch", payload)


    ADVERSARIAL_VOTE = 0.99

    def _mislead(self, findings: list[dict], devices: dict) -> None:
        """Controlled adversarial mode (tests and demos only). On the most degraded device, claim near
        certainty for the declared hypothesis this agent's own evidence supports least. Signals, strengths
        and evidence stay exactly as computed: only the vote lies. Generic: no scenario names involved."""
        def load(did: str) -> float:
            return sum(derive_strengths(devices[did]["metrics"], devices[did]["status"]).values())

        target = max(sorted(f["device_id"] for f in findings), key=load, default=None)
        f = next((x for x in findings if x["device_id"] == target), None)
        if f is None or not self.hypotheses:
            return
        h = min(self.hypotheses, key=lambda x: f["votes"].get(x, 0.0))
        f["votes"][h] = self.ADVERSARIAL_VOTE

    def _challenge(self, env: Envelope) -> Envelope:
        """Answer a targeted follow-up: graded strength of specific signals on one device."""
        dev = env.payload["devices"][env.payload["device_id"]]
        answers = {}
        for sig in env.payload["signals"]:
            if sig not in DOMAIN_SIGNALS[self.domain]:
                continue
            answers[sig] = signal_strength(sig, dev["metrics"], dev["status"])
        return self._reply(env, "challenge_response",
                           {"agent": self.name, "domain": self.domain,
                            "device_id": env.payload["device_id"], "answers": answers})


class PerformanceAgent(AnalysisAgent):
    name, domain = "performance_agent", "performance"
    description = "Analyses latency, jitter, packet loss and link utilization; votes on congestion."
    accepts, produces = ("analyze_request", "challenge_request"), ("finding_batch", "challenge_response")
    hypotheses = ("link_congestion", "interface_fault", "weak_wifi", "device_overload")

    def votes(self, st, dev):
        v: dict[str, float] = {}
        g = lambda k: st.get(k, 0.0)  # noqa: E731
        util = g("high_utilization")
        if util > 0:   # utilization is the necessary condition; the rest only adds support
            v["link_congestion"] = util * noisy_or([.55, .15 * g("high_latency"), .10 * g("high_jitter"),
                                                    .10 * g("packet_loss")])
        if util < 0.5 and any(x >= 1 for x in st.values()):
            # degraded but link not saturated: performance data alone cannot discriminate
            v.update(interface_fault=.25, device_overload=.20)
            if is_wireless(dev):
                v["weak_wifi"] = .25
        return v


class InfrastructureAgent(AnalysisAgent):
    name, domain = "infrastructure_agent", "infrastructure"
    description = "Analyses queue drops, interface errors, link flaps, CPU/memory and device status."
    accepts, produces = ("analyze_request", "challenge_request"), ("finding_batch", "challenge_response")
    hypotheses = ("link_congestion", "interface_fault", "device_overload", "hardware_failure")

    def votes(self, st, dev):
        v: dict[str, float] = {}
        g = lambda k: st.get(k, 0.0)  # noqa: E731
        qd, ie, lf = g("queue_drops"), g("interface_errors"), g("link_flaps")
        cpu, mem, dc = g("high_cpu"), g("high_memory"), g("device_critical")
        if qd > 0:   # drops are congestion-like unless errors / CPU explain them
            v["link_congestion"] = qd * noisy_or([.55, .15 * (1 - max(ie, cpu))])
        if ie > 0 or lf > 0:
            v["interface_fault"] = noisy_or([.55 * ie, .40 * lf])
        if cpu > 0 or mem > 0:
            v["device_overload"] = noisy_or([.6 * cpu, .3 * mem])
        hits = cpu + ie + dc    # graded: CPU at 89 % is 0.95 of a hit, not 0
        if hits >= 1.5:
            v["hardware_failure"] = max(0.0, min(.85, .5 + .35 * (hits - 2)))
        return v


class ConnectivityAgent(AnalysisAgent):
    name, domain = "connectivity_agent", "connectivity"
    description = "Wi-Fi quality, DNS/DHCP service health and topology-aware scope analysis."
    accepts, produces = ("analyze_request", "challenge_request"), ("finding_batch", "challenge_response")
    hypotheses = ("weak_wifi", "dns_failure", "dhcp_failure")

    def votes(self, st, dev):
        v: dict[str, float] = {}
        g = lambda k: st.get(k, 0.0)  # noqa: E731
        if g("weak_signal") > 0 or g("retransmissions") > 0:
            v["weak_wifi"] = noisy_or([.55 * g("weak_signal"), .50 * g("retransmissions")])
        if g("dns_failures") > 0:
            v["dns_failure"] = .85 * g("dns_failures")
        if g("dhcp_failures") > 0:
            v["dhcp_failure"] = .85 * g("dhcp_failures")
        return v

    def extra(self, devices: dict, topology: dict) -> dict:
        """Topology-aware scope analysis: which degraded devices are roots vs downstream."""
        degraded = {d for d, dev in devices.items() if is_degraded(dev)}
        parent = {d: dev.get("parent") for d, dev in devices.items()}
        roots, downstream = [], {}
        for d in sorted(degraded):
            top, seen = d, {d}
            while parent.get(top) in degraded and parent[top] not in seen:
                top = parent[top]
                seen.add(top)
            (roots.append(d) if top == d else downstream.__setitem__(d, top))
        shared: dict[str, list[str]] = defaultdict(list)
        for r in roots:
            if parent.get(r):
                shared[parent[r]].append(r)
        topo_ids = {d["id"] for d in topology.get("devices", [])}
        silent = sorted(topo_ids - set(devices))
        return {"scope": {
            "degraded": sorted(degraded), "root_candidates": roots, "downstream": downstream,
            "shared_parent": {p: kids for p, kids in shared.items() if len(kids) >= 2},
            "silent_devices": silent, "topology_available": bool(topo_ids),
        }}


# --------------------------------------------------------------------------- correlation
AUTHORITY = {  # which domains can directly observe the cause
    "link_congestion": {"performance", "infrastructure"},
    "interface_fault": {"infrastructure"},
    "weak_wifi": {"connectivity"},
    "device_overload": {"infrastructure"},
    "hardware_failure": {"infrastructure"},
    "dns_failure": {"connectivity"},
    "dhcp_failure": {"connectivity"},
}
SIGNATURE = {  # every symptom this cause can plausibly explain
    "link_congestion": {"high_utilization", "queue_drops", "high_latency", "high_jitter", "packet_loss"},
    "interface_fault": {"interface_errors", "link_flaps", "packet_loss", "high_jitter", "high_latency"},
    "weak_wifi": {"weak_signal", "retransmissions", "packet_loss", "high_jitter", "high_latency"},
    "device_overload": {"high_cpu", "high_memory", "high_latency", "packet_loss", "queue_drops", "high_jitter"},
    "hardware_failure": {"high_cpu", "interface_errors", "device_critical", "packet_loss", "queue_drops",
                         "high_latency", "high_utilization", "link_flaps", "high_jitter"},
    "dns_failure": {"dns_failures"},
    "dhcp_failure": {"dhcp_failures"},
}
EXPECTED = {  # signals that MUST be seen if the hypothesis is true (verification step)
    "link_congestion": ["high_utilization", "queue_drops", "high_latency"],
    "interface_fault": ["interface_errors", "packet_loss"],
    "weak_wifi": ["weak_signal", "retransmissions"],
    "device_overload": ["high_cpu", "high_latency"],
    "hardware_failure": ["high_cpu", "interface_errors", "device_critical"],
    "dns_failure": ["dns_failures"],
    "dhcp_failure": ["dhcp_failures"],
}
MUST_BE_ABSENT = {  # service-level faults should not coincide with network-level degradation
    "dns_failure": {"packet_loss", "high_latency", "high_utilization"},
    "dhcp_failure": {"packet_loss", "high_latency", "high_utilization"},
}
NON_AUTHORITY_WEIGHT = 0.7   # a vote from an agent outside the hypothesis' domain counts less
COVERAGE_FLOOR = 0.4         # score = base * (FLOOR + (1-FLOOR) * coverage)
AMBIGUITY_MARGIN = 0.15


class CorrelationAgent(BaseAgent):
    name = "correlation_agent"
    description = "Fuses specialist votes, resolves conflicts, runs the challenge re-score, verifies and scores confidence."
    accepts, produces = ("correlate_request", "verify_request"), ("diagnosis", "verification_result")

    def _handle(self, env: Envelope) -> Envelope:
        if env.msg_type == "correlate_request":
            return self._reply(env, "diagnosis", self.correlate(env.payload))
        if env.msg_type == "verify_request":
            return self._reply(env, "verification_result", self.verify(env.payload))
        raise ValueError(f"{self.name} cannot handle '{env.msg_type}'")

    # -- step 1: fuse agent votes
    def _score_device(self, did: str, by_domain: dict[str, dict[str, dict]]) -> dict[str, Any]:
        votes_by_h: dict[str, list[tuple[str, float]]] = defaultdict(list)
        present: set[str] = set()
        strength: dict[str, float] = {}
        evidence: list[dict] = []
        for domain, fmap in by_domain.items():
            f = fmap.get(did)
            if not f:
                continue
            present |= set(f["signals_present"])
            # graded strengths; agents that only report binary signals count them as 1.0
            for sig, val in (f.get("signal_strength") or {s: 1.0 for s in f["signals_present"]}).items():
                strength[sig] = max(strength.get(sig, 0.0), val)
            evidence += f["evidence"]
            for h, v in f["votes"].items():
                votes_by_h[h].append((domain, v))
        observed = {s: v for s, v in strength.items() if v > 0}
        unknown = sorted({u for fmap in by_domain.values() if fmap.get(did)
                          for u in fmap[did]["signals_unknown"]} - set(strength))
        total = sum(observed.values())
        ranking = []
        for h, vs in votes_by_h.items():
            eff = [v * (1.0 if d in AUTHORITY[h] else NON_AUTHORITY_WEIGHT) for d, v in vs]
            base = noisy_or(eff)
            # coverage = strength-weighted share of observed symptoms this cause can explain
            cov = sum(v for s, v in observed.items() if s in SIGNATURE[h]) / total if total else 0.0
            score = base * (COVERAGE_FLOOR + (1 - COVERAGE_FLOOR) * cov)
            if h in MUST_BE_ABSENT and present & MUST_BE_ABSENT[h]:
                score *= 0.5
            ranking.append({"hypothesis": h, "score": round(score, 3), "base_vote": base,
                            "coverage": round(cov, 3), "voters": sorted({d for d, _ in vs})})
        ranking.sort(key=lambda r: -r["score"])
        return {"device_id": did, "ranking": ranking, "present": sorted(present), "evidence": evidence,
                "strength": strength, "unknown": unknown}

    def correlate(self, p: dict) -> dict:
        devices, batches = p["devices"], p["batches"]
        by_domain = {b["domain"]: {f["device_id"]: f for f in b["findings"]} for b in batches}
        scope = next((b["scope"] for b in batches if "scope" in b), None)
        failed = p.get("failed_agents", [])
        if scope is None:  # connectivity agent unavailable: fall back to a flat, topology-free scope
            degraded = sorted(d for d, dev in devices.items() if is_degraded(dev))
            scope = {"degraded": degraded, "root_candidates": degraded, "downstream": {},
                     "shared_parent": {}, "silent_devices": [], "topology_available": False}
        else:  # the scope comes from another agent: only devices present in the telemetry may be blamed
            scope = {**scope, "degraded": [d for d in scope["degraded"] if d in devices],
                     "root_candidates": [d for d in scope["root_candidates"] if d in devices],
                     "downstream": {d: r for d, r in scope.get("downstream", {}).items() if d in devices}}
        base ={"failed_agents": failed, "scope": scope,
                "completeness": p.get("completeness", 0.0)}
        if not scope["degraded"]:
            return {**base, "status": "healthy", "hypothesis": None, "ranking": [],
                    "root_cause_devices": [], "affected_devices": [], "evidence": [],
                    "conflicts": [], "alternatives": [], "top_score": 0.0, "margin": 1.0}

        scored = {d: self._score_device(d, by_domain) for d in scope["root_candidates"]}
        best = max(scored.values(), key=lambda s: (s["ranking"][0]["score"] if s["ranking"] else 0,
                                                   len(s["present"])))
        ranking = best["ranking"]
        challenge_info = None
        ch = p.get("challenge")
        if ch and ranking and ch["device_id"] == best["device_id"]:
            before = round(ranking[0]["score"] - (ranking[1]["score"] if len(ranking) > 1 else 0), 3)
            for r in ranking:
                strengths = [ch["answers"][sig]["strength"] for sig in EXPECTED[r["hypothesis"]]
                             if sig in ch["answers"] and ch["answers"][sig]["strength"] is not None]
                if strengths:
                    r["graded_support"] = round(sum(strengths) / len(strengths), 3)
                    r["score"] = round(r["score"] * (0.5 + 0.5 * r["graded_support"]), 3)
            ranking.sort(key=lambda r: -r["score"])
            after = round(ranking[0]["score"] - (ranking[1]["score"] if len(ranking) > 1 else 0), 3)
            challenge_info = {"triggered": True, "device_id": best["device_id"], "margin_before": before,
                              "margin_after": after, "answers": ch["answers"],
                              "winner_changed": ranking[0]["hypothesis"] != ch["leader_before"]}
        if not ranking:
            return {**base, "status": "no_hypothesis", "hypothesis": None, "ranking": [],
                    "root_cause_devices": [best["device_id"]],
                    "affected_devices": scope["degraded"], "evidence": best["evidence"][:8],
                    "conflicts": [], "alternatives": [], "top_score": 0.0, "margin": 0.0,
                    "present": best["present"], "signal_strength": best["strength"],
                    "unknown_signals": best["unknown"]}
        top = ranking[0]
        runner = ranking[1]["score"] if len(ranking) > 1 else 0.0
        root_devs = [best["device_id"]] + [
            d for d, s in scored.items()
            if d != best["device_id"] and s["ranking"] and s["ranking"][0]["hypothesis"] == top["hypothesis"]]
        other_roots = {d: {"hypothesis": s["ranking"][0]["hypothesis"], "score": s["ranking"][0]["score"]}
                       for d, s in scored.items() if d not in root_devs and s["ranking"]
                       and s["ranking"][0]["score"] >= 0.4}

        # conflicts: agents whose own strongest hypothesis differs from the fused winner
        conflicts = []
        for domain, fmap in by_domain.items():
            f = fmap.get(best["device_id"])
            if not f or not f["votes"]:
                continue
            h, v = max(f["votes"].items(), key=lambda kv: kv[1])
            if v >= 0.5 and h != top["hypothesis"]:
                rival = next((r for r in ranking if r["hypothesis"] == h), None)
                conflicts.append({
                    "agent": f["agent"], "agent_hypothesis": h, "agent_vote": v,
                    "resolved_to": top["hypothesis"],
                    "resolution": (
                        f"{h} ({rival['score'] if rival else 0:.2f}, explains "
                        f"{(rival['coverage'] if rival else 0):.0%} of observed signals) was outranked by "
                        f"{top['hypothesis']} ({top['score']:.2f}, explains {top['coverage']:.0%}) after "
                        "authority weighting and signal-coverage scoring")})

        evidence, seen = [], set()
        for d in root_devs:
            for e in scored[d]["evidence"]:
                k = (e["metric"], e["device_id"])
                if k not in seen:
                    seen.add(k)
                    evidence.append(e)
        alternatives = [f"{r['hypothesis']} (score {r['score']:.2f})" for r in ranking[1:4] if r["score"] >= .25]
        for parent, kids in scope["shared_parent"].items():
            alternatives.append(f"Shared upstream dependency of {', '.join(kids)}: {parent} or its uplink")
        if scope["silent_devices"]:
            alternatives.append("Possible outage of device(s) with no telemetry: "
                                + ", ".join(scope["silent_devices"]))
        affected = root_devs + [d for d in scope["degraded"] if d not in root_devs]
        return {**base, "status": "candidate", "hypothesis": top["hypothesis"], "ranking": ranking[:4],
                "ranking_all": ranking,
                "top_score": top["score"], "margin": round(top["score"] - runner, 3),
                "root_cause_devices": root_devs, "other_root_candidates": other_roots,
                "affected_devices": affected, "downstream": scope["downstream"],
                "evidence": evidence[:12], "conflicts": conflicts, "alternatives": alternatives,
                "present": best["present"], "signal_strength": best["strength"],
                "unknown_signals": best["unknown"], "challenge": challenge_info}

    # -- step 2: independent verification against the raw normalised data, then confidence
    def verify(self, p: dict) -> dict:
        diag, devices = p["diagnosis"], p["devices"]
        if diag["status"] == "healthy":
            conf = 0.9 if diag["completeness"] >= 0.8 else 0.7
            return {"status": "healthy", "confidence": conf, "verified": [], "contradicted": [],
                    "unverifiable": [], "breakdown": {"completeness": diag["completeness"]}}
        if diag["status"] == "no_hypothesis":
            return {"status": "insufficient_evidence", "confidence": 0.1, "verified": [],
                    "contradicted": [], "unverifiable": [], "partial": {}, "quality_flags": [],
                    "gates": [{"gate": "evidence strength", "value": 0.0, "need": ">= 0.65", "passed": False,
                               "explanation": "degradation detected but no agent produced a hypothesis: the "
                                              "observed symptoms match no known fault signature"}],
                    "breakdown": {"reason": "degradation detected but no agent produced a hypothesis"}}
        h, dev = diag["hypothesis"], devices[diag["root_cause_devices"][0]]
        present, unknown = derive_signals(dev["metrics"], dev["status"])
        st = derive_strengths(dev["metrics"], dev["status"])
        expected = EXPECTED[h]
        verified = [s for s in expected if st.get(s) == 1.0]
        partial = {s: st[s] for s in expected if 0 < st.get(s, 0) < 1}
        unverifiable = [s for s in expected if s in unknown]
        contradicted = [s for s in expected if st.get(s) == 0.0]
        contradicted += [f"unexpected:{s}" for s in sorted(MUST_BE_ABSENT.get(h, set()) & present)]
        decided = len(verified) + len(partial) + len(contradicted)
        support = (len(verified) + sum(partial.values())) / decided if decided else None
        factor = 0.6 + 0.4 * support if decided else 0.8

        # telemetry that contradicts itself on the device we blame is discounted, not trusted blindly
        exp_metrics = {THRESHOLDS[s][0] for s in expected if s in THRESHOLDS}
        q_flags = [q for q in dev.get("quality", [])
                   if q["metric"] is None or q["metric"] in exp_metrics or q["code"] == "conflicting_duplicates"]
        quality_pen = min(0.15, 0.05 * len(q_flags))
        margin_pen = max(0.0, AMBIGUITY_MARGIN - diag["margin"])
        conflict_pen = min(0.10, 0.05 * len(diag["conflicts"]))
        data_pen = 0.2 * (1 - diag["completeness"])
        unverifiable_pen = min(0.15, 0.05 * len(unverifiable))
        agent_pen = 0.10 * len(diag["failed_agents"])
        conf = (diag["top_score"] * factor - margin_pen - conflict_pen - data_pen - unverifiable_pen - agent_pen
                - quality_pen)
        cap = 0.75 if diag["failed_agents"] else 0.97
        conf = round(max(0.0, min(cap, conf)), 2)
        status = ("diagnosed" if conf >= CONFIDENCE_DIAGNOSED
                  else "tentative" if conf >= CONFIDENCE_TENTATIVE else "insufficient_evidence")
        gates = [
            {"gate": "evidence strength", "value": diag["top_score"], "need": ">= 0.65",
             "passed": diag["top_score"] >= CONFIDENCE_DIAGNOSED,
             "explanation": f"fused agent score for {h} is {diag['top_score']:.2f}"},
            {"gate": "verification against raw data", "value": round(support, 2) if support is not None else None,
             "need": "expected signals present", "passed": bool(decided) and not contradicted and not partial,
             "explanation": (f"{len(verified)} of {len(expected)} expected signals fully present"
                             + (f", {len(partial)} only elevated" if partial else "")
                             + (f", {len(contradicted)} contradicted" if contradicted else "")
                             + (f", {len(unverifiable)} not measured" if unverifiable else ""))},
            {"gate": "separation from runner-up", "value": diag["margin"], "need": f">= {AMBIGUITY_MARGIN}",
             "passed": diag["margin"] >= AMBIGUITY_MARGIN,
             "explanation": f"lead over the next hypothesis is {diag['margin']:.2f}"},
            {"gate": "telemetry completeness", "value": diag["completeness"], "need": ">= 0.8",
             "passed": diag["completeness"] >= 0.8,
             "explanation": f"{diag['completeness']:.0%} of core metrics present"},
            {"gate": "telemetry consistency", "value": len(q_flags), "need": "0 flags", "passed": not q_flags,
             "explanation": "; ".join(q["message"] for q in q_flags) or "no inconsistencies on the blamed device"},
            {"gate": "agent availability", "value": len(diag["failed_agents"]), "need": "0 failed",
             "passed": not diag["failed_agents"],
             "explanation": ", ".join(diag["failed_agents"]) or "all agents answered"},
        ]
        return {"status": status, "confidence": conf, "verified": verified, "partial": partial,
                "contradicted": contradicted, "unverifiable": unverifiable, "quality_flags": q_flags,
                "gates": gates,
                "breakdown": {"fused_score": diag["top_score"], "verification_factor": round(factor, 2),
                              "ambiguity_penalty": round(margin_pen, 2),
                              "conflict_penalty": round(conflict_pen, 2),
                              "data_quality_penalty": round(data_pen, 2),
                              "unverifiable_penalty": round(unverifiable_pen, 2),
                              "failed_agent_penalty": round(agent_pen, 2),
                              "consistency_penalty": round(quality_pen, 2), "confidence_cap": cap}}


# --------------------------------------------------------------------------- reporting
CAUSE_TEXT = {
    "link_congestion": "link congestion causing egress queue drops and elevated latency",
    "interface_fault": "Ethernet/interface fault (errors and link instability)",
    "weak_wifi": "weak Wi-Fi signal causing retransmissions and packet loss",
    "device_overload": "device CPU/memory overload",
    "hardware_failure": "hardware failure",
    "dns_failure": "DNS service failure (network path itself looks healthy)",
    "dhcp_failure": "DHCP service failure (network path itself looks healthy)",
}
ACTIONS = {
    "link_congestion": ["Inspect utilization of the affected link and its upstream uplink",
                        "Review QoS / egress queue configuration and traffic distribution",
                        "Identify top talkers; consider rate-limiting or adding capacity"],
    "interface_fault": ["Check cabling, SFP/transceiver and port for the affected interface",
                        "Review interface error counters (CRC, FCS) and link flap logs",
                        "Swap the cable/port and re-measure; replace the module if errors persist"],
    "weak_wifi": ["Check AP placement, channel plan and transmit power for the affected AP",
                  "Survey RSSI and interference near affected clients",
                  "Consider adding or relocating an access point"],
    "device_overload": ["Check running processes / control-plane load on the device",
                        "Review recent configuration or traffic changes",
                        "Plan capacity upgrade or traffic offload"],
    "hardware_failure": ["Check device health (fans, PSU, ASIC/line card logs) and plan a replacement",
                         "Fail over traffic to a redundant path/device if available",
                         "Raise a hardware RMA after confirming with the vendor diagnostics"],
    "dns_failure": ["Test resolver reachability and response from the affected segment",
                    "Check DNS server health, forwarders and recent changes",
                    "Temporarily point clients at a secondary resolver"],
    "dhcp_failure": ["Check DHCP server/relay (ip helper) reachability from the segment",
                     "Verify lease pool exhaustion and scope configuration",
                     "Check for rogue DHCP servers on the VLAN"],
}


def confidence_category(c: float) -> str:
    return "high" if c >= 0.8 else "medium" if c >= 0.6 else "low"


class ReportingAgent(BaseAgent):
    name = "reporting_agent"
    description = "Builds the unified diagnostic report (JSON + Markdown)."
    accepts, produces = ("report_request",), ("report",)

    def _handle(self, env: Envelope) -> Envelope:
        if env.msg_type != "report_request":
            raise ValueError(f"{self.name} cannot handle '{env.msg_type}'")
        p = env.payload
        diag, ver, meta = p.get("diagnosis"), p.get("verification"), p["meta"]
        incident = p.get("incident_id") or env.correlation_id
        base = {"incident_id": incident, "report_version": "1.0"}
        data_quality = {"completeness": meta.get("completeness", 0.0), **meta.get("stats", {}),
                        "issues": meta.get("issues", [])}
        health = meta.get("agent_health", {})

        if diag is None:  # pipeline could not run (bad input / all agents failed)
            rep = {**base, "status": "error", "suspected_root_cause": f"No diagnosis possible: {p['reason']}",
                   "confidence": 0.0, "confidence_category": "low", "affected_devices": [],
                   "supporting_evidence": [], "alternative_causes": [],
                   "recommended_actions": ["Fix or re-export the telemetry input and re-run",
                                           "See data_quality.issues for details"],
                   "evidence_sources": [], "limitations": [p["reason"]]}
        elif diag["status"] == "healthy":
            rep = {**base, "status": "healthy",
                   "suspected_root_cause": "No fault detected; all monitored metrics are within expected ranges",
                   "confidence": ver["confidence"], "confidence_category": confidence_category(ver["confidence"]),
                   "affected_devices": [], "supporting_evidence": [], "alternative_causes": [],
                   "recommended_actions": ["No action required; continue monitoring"],
                   "evidence_sources": ["performance_agent", "infrastructure_agent", "connectivity_agent"],
                   "limitations": []}
        else:
            status = ver["status"]
            h = diag.get("hypothesis")
            devs = diag["root_cause_devices"]
            where = ", ".join(devs)
            if status == "insufficient_evidence":
                cause = "Insufficient evidence for a reliable root-cause diagnosis"
                actions = ["Collect additional telemetry (interface counters, queue stats, wireless and "
                           "service metrics) for the affected devices",
                           "Re-run the diagnosis once more data is available"]
                if h and diag["top_score"] >= 0.3:
                    actions.append(f"Manually check the leading hypothesis first: {CAUSE_TEXT[h]}")
            else:
                prefix = "Likely" if status == "diagnosed" else "Possible"
                cause = f"{prefix} {CAUSE_TEXT[h]} on {where}"
                actions = list(ACTIONS[h])
            limitations = []
            if status != "diagnosed":
                limitations.append("Evidence is not strong enough to claim a definitive root cause")
            limitations.append("Root cause requires further verification on the device")
            if ver["unverifiable"]:
                limitations.append("Could not verify expected signals (metrics missing): "
                                   + ", ".join(ver["unverifiable"]))
            if ver["contradicted"]:
                limitations.append("Expected signals not observed: " + ", ".join(ver["contradicted"]))
            if diag["completeness"] < 0.8:
                limitations.append(f"Telemetry completeness is {diag['completeness']:.0%}")
            for a in diag["failed_agents"]:
                limitations.append(f"{a} was unavailable; its evidence is missing and confidence is capped")
            if data_quality.get("records_rejected"):
                limitations.append(f"{data_quality['records_rejected']} input record(s) were rejected as invalid")
            secondary = [{"device_id": d, "hypothesis": o["hypothesis"], "score": o["score"],
                          "suspected_cause": CAUSE_TEXT[o["hypothesis"]]}
                         for d, o in (diag.get("other_root_candidates") or {}).items()]
            if secondary:
                limitations.append("Other devices show a different fault pattern (see secondary_findings); "
                                   "this may be a multi-fault incident")
            sources = sorted({f"{e_dom}_agent" for e_dom in self._domains(diag)})
            rep = {**base, "status": status, "suspected_root_cause": cause,
                   "root_cause_type": h if status in ("diagnosed", "tentative") else None,
                   "leading_hypothesis": h,
                   "confidence": ver["confidence"], "confidence_category": confidence_category(ver["confidence"]),
                   "affected_devices": diag["affected_devices"], "root_cause_devices": devs,
                   "downstream_affected": sorted(diag.get("downstream", {})),
                   "supporting_evidence": [{"metric": e["metric"], "value": e["value"],
                                            "device_id": e["device_id"], "interpretation": e["interpretation"]}
                                           for e in diag["evidence"]],
                   "alternative_causes": diag["alternatives"], "recommended_actions": actions,
                   "evidence_sources": sources, "limitations": limitations,
                   "hypothesis_ranking": diag["ranking"], "conflicts_resolved": diag["conflicts"],
                   "verification": {k: ver[k] for k in ("verified", "contradicted", "unverifiable")},
                   "confidence_breakdown": ver["breakdown"], "secondary_findings": secondary,
                   "challenge_round": diag.get("challenge"),
                   "what_would_raise_confidence": self._raise_confidence(diag, ver),
                   "decision_gates": ver.get("gates", [])}
            if status != "diagnosed":
                rep["abstention" if status == "insufficient_evidence" else "hedge"] = self._abstention(diag, ver)
        tg = meta.get("trustguard")
        if tg:
            rep["trustguard"] = tg
            rep.setdefault("limitations", []).extend(self._trust_limitations(tg))
        rep["data_quality"] = data_quality
        rep["agent_health"] = health
        return self._reply(env, "report", rep)

    @staticmethod
    def _trust_limitations(tg: dict) -> list[str]:
        if tg["status"] != "audited":
            return [f"TrustGuard was unavailable ({tg.get('reason', 'no reply')}): specialist findings were "
                    "not audited before correlation"]
        out, s = [], tg["summary"]
        if s["flagged"]:
            agents = sorted({f["agent"] for f in tg["flagged"]})
            out.append(f"TrustGuard excluded {s['flagged']} claim(s) contradicted by the telemetry "
                       f"(from {', '.join(agents)}); see trustguard.flagged")
        if s["unverifiable"]:
            out.append(f"TrustGuard could not verify {s['unverifiable']} claim(s) (telemetry missing); "
                       "unverifiable votes were capped")
        return out

    @staticmethod
    def _raise_confidence(diag: dict, ver: dict) -> list[str]:
        tips = []
        dev = diag["root_cause_devices"][0] if diag.get("root_cause_devices") else "the affected device"
        for sig in ver.get("unverifiable", []):
            metric = "device status" if sig == "device_critical" else THRESHOLDS[sig][0]
            tips.append(f"Collect {metric} for {dev} (needed to confirm the hypothesis)")
        for sig in ver.get("contradicted", []):
            tips.append(f"Explain why '{sig.replace('unexpected:', '')}' "
                        + ("is present although unexpected" if sig.startswith("unexpected:")
                           else "was not observed although expected"))
        ranking = diag.get("ranking", [])
        if len(ranking) > 1 and diag.get("margin", 1) < AMBIGUITY_MARGIN + 0.1:
            top, alt = ranking[0]["hypothesis"], ranking[1]["hypothesis"]
            only_top = [s for s in EXPECTED[top] if s not in EXPECTED[alt]]
            only_alt = [s for s in EXPECTED[alt] if s not in EXPECTED[top]]
            tips.append(f"Distinguish {top} from {alt}: check {', '.join(only_top + only_alt)}")
        for a in diag.get("failed_agents", []):
            tips.append(f"Restore {a} so its evidence can be included")
        if diag.get("completeness", 1) < 0.8:
            tips.append("Increase telemetry completeness (more metrics per device)")
        return tips

    @staticmethod
    def _abstention(diag: dict, ver: dict) -> dict:
        """Why the system will not commit, and the concrete measurements that would let it."""
        why = [f"{g['gate']}: {g['explanation']} (need {g['need']})" for g in ver.get("gates", []) if not g["passed"]]
        dev = diag["root_cause_devices"][0] if diag.get("root_cause_devices") else None
        strength, unknown = diag.get("signal_strength", {}), set(diag.get("unknown_signals", []))
        ranking = diag.get("ranking", [])
        cands = [r["hypothesis"] for r in ranking[:3]] or [h for h in EXPECTED if any(
            s in unknown for s in EXPECTED[h])]
        need: dict[tuple, dict] = {}
        for h in cands:
            for sig in EXPECTED[h]:
                metric = "device status" if sig == "device_critical" else THRESHOLDS[sig][0]
                if sig in unknown:
                    reason = "not measured"
                elif 0 < strength.get(sig, 0) < 1:
                    reason = f"only elevated ({strength[sig]:.0%} of alarm level): re-sample over a longer window"
                else:
                    continue
                e = need.setdefault((dev, metric), {"device_id": dev, "metric": metric, "signal": sig,
                                                     "status": reason, "decides": []})
                e["decides"].append(h)
        req = sorted(need.values(), key=lambda e: (-len(e["decides"]), e["metric"]))
        for e in req:
            e["why"] = ("would confirm or rule out " + ", ".join(e["decides"]))
        return {"why_not_committed": why or ["confidence below the commitment threshold"],
                "leading_hypothesis": diag.get("hypothesis"),
                "required_measurements": req,
                "summary": (f"Leading hypothesis {diag.get('hypothesis') or 'none'} is not supported strongly enough. "
                            + (f"Most useful next measurement: {req[0]['metric']} on {req[0]['device_id']}."
                               if req else "No missing metric would decide it; the pattern matches no known fault."))}

    @staticmethod
    def _domains(diag: dict) -> set[str]:
        doms = set()
        for r in diag["ranking"][:1]:
            doms |= set(r["voters"])
        return doms


def render_trustguard_markdown(tg: dict | None) -> list[str]:
    """Markdown lines for a report's or trace's TrustGuard block (shared by both renderers)."""
    if not tg:
        return []
    if tg.get("status") == "unavailable":
        return ["## TrustGuard audit", "", f"TrustGuard was unavailable ({tg.get('reason')}): findings were not "
                "audited before correlation.", ""]
    s = tg["summary"]
    L = ["## TrustGuard audit", "",
         f"{s['checked']} claims checked against the telemetry: {s['accepted']} accepted, {s['flagged']} flagged, "
         f"{s['unverifiable']} unverifiable.", ""]
    odd = tg.get("flagged", []) + tg.get("unverifiable", []) if "flagged" in tg else \
        [r for r in tg.get("records", []) if r["decision"] != "trusted"]
    L += [f"- **{r['record_id']}** {r['agent']} {r['kind']} `{r['subject']}` = {r['reported']} on "
          f"{r['device_id'] or '-'}: {', '.join(r['reason_codes'])}. {r['explanation']}" for r in odd]
    ba = tg.get("before_after")
    if ba:
        b, a = ba["before"], ba["after"]
        L += ["", f"Without TrustGuard: {b['status']} {b['root_cause_type'] or b['leading_hypothesis'] or '-'} "
              f"({b['confidence']:.2f}); with TrustGuard: {a['status']} {a['root_cause_type'] or a['leading_hypothesis'] or '-'} "
              f"({a['confidence']:.2f}). Diagnosis changed: {'yes' if ba['diagnosis_changed'] else 'no'}."]
    return L + [""]


def render_markdown(rep: dict) -> str:
    L = [f"# Incident {rep['incident_id']}: {rep['status'].replace('_', ' ').upper()}", "",
         f"**Suspected root cause:** {rep['suspected_root_cause']}  ",
         f"**Confidence:** {rep['confidence']:.2f} ({rep['confidence_category']})  ",
         f"**Affected devices:** {', '.join(rep['affected_devices']) or 'none'}", ""]
    pt = (rep.get("prooftrace") or {}).get("checks")
    if pt:
        L += [f"**ProofTrace:** {pt['passed']}/{pt['total']} independent checks passed"
              + ("" if pt["verified"] else " (NOT VERIFIED)") + " (`python -m netcoop prooftrace` for the full trace)", ""]
    why = rep.get("abstention") or rep.get("hedge")
    if why:
        L += ["## Why the system does not commit", "", why["summary"], ""]
        L += [f"- {w}" for w in why["why_not_committed"]] + [""]
        if why["required_measurements"]:
            L += ["| Measure | On device | Status | Would decide |", "|---|---|---|---|"]
            L += [f"| {m['metric']} | {m['device_id']} | {m['status']} | {', '.join(m['decides'])} |"
                  for m in why["required_measurements"]] + [""]
    if rep.get("supporting_evidence"):
        L += ["## Supporting evidence", "", "| Device | Metric | Value | Interpretation |", "|---|---|---|---|"]
        L += [f"| {e['device_id']} | {e['metric']} | {e['value']} | {e['interpretation']} |"
              for e in rep["supporting_evidence"]]
        L.append("")
    if rep.get("conflicts_resolved"):
        L += ["## Agent conflicts and resolution", ""]
        L += [f"- **{c['agent']}** favoured `{c['agent_hypothesis']}`: {c['resolution']}"
              for c in rep["conflicts_resolved"]]
        L.append("")
    if rep.get("secondary_findings"):
        L += ["## Secondary findings (possible additional faults)", ""]
        L += [f"- **{f['device_id']}**: {f['suspected_cause']} (score {f['score']:.2f})"
              for f in rep["secondary_findings"]] + [""]
    if rep.get("challenge_round"):
        c = rep["challenge_round"]
        L += ["## Challenge round", "",
              f"Top hypotheses were close, so the correlation agent queried the specialist agents for graded "
              f"signal strength on {c['device_id']}. Margin {c['margin_before']:.2f} -> {c['margin_after']:.2f}"
              + (" (winner changed)" if c["winner_changed"] else "") + ".", ""]
    for title, key in (("Alternative explanations", "alternative_causes"),
                       ("What would raise confidence", "what_would_raise_confidence"),
                       ("Recommended actions", "recommended_actions"), ("Limitations", "limitations")):
        if rep.get(key):
            L += [f"## {title}", ""] + [f"- {x}" for x in rep[key]] + [""]
    L += render_trustguard_markdown(rep.get("trustguard"))
    if rep.get("confidence_breakdown"):
        L += ["## Confidence breakdown", "", "```json",
              __import__("json").dumps(rep["confidence_breakdown"], indent=2), "```", ""]
    dq = rep["data_quality"]
    warns = [i for i in dq["issues"] if i["level"] in ("warning", "error")]
    L += ["## Data quality", "", f"- Completeness: {dq['completeness']:.0%}",
          f"- Records accepted/rejected: {dq.get('records_accepted', 0)}/{dq.get('records_rejected', 0)}",
          f"- Issues: {len(warns)} warning/error, {len(dq['issues']) - len(warns)} info"]
    grouped: dict[tuple, int] = {}
    for i in warns:
        key = (i["level"], i.get("device_id") or "-", i["message"])
        grouped[key] = grouped.get(key, 0) + 1
    L += [f"  - [{lv}] {dev}: {msg}" + (f" (x{n})" if n > 1 else "")
          for (lv, dev, msg), n in list(grouped.items())[:12]]
    return "\n".join(L) + "\n"
