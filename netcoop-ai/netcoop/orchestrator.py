"""Orchestrator: ingest -> fan-out to analysis agents (retry / degrade) -> TrustGuard audit ->
correlate -> verify -> report. Every step is a protocol message on the bus."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agents import (AMBIGUITY_MARGIN, EXPECTED, ConnectivityAgent, CorrelationAgent, InfrastructureAgent, PerformanceAgent,
                     ReportingAgent)
from .bus import MessageBus
from .normalizer import normalize
from pydantic import ValidationError

from .protocol import SUPPORTED_PROTOCOL_VERSIONS, AgentCard, make_envelope

ANALYSIS_AGENTS = ("performance_agent", "infrastructure_agent", "connectivity_agent")
DOMAIN_AGENT = {"performance": "performance_agent", "infrastructure": "infrastructure_agent",
                "connectivity": "connectivity_agent"}


class Orchestrator:
    name = "orchestrator"

    def __init__(self, inject_faults: dict[str, str] | None = None, max_retries: int = 1,
                 remote_connectivity: str | None = None, prooftrace: bool = True, trustguard: bool = True):
        faults = inject_faults or {}
        self.max_retries = max_retries
        self.prooftrace = prooftrace
        self.trustguard = trustguard
        self._faults = dict(faults)
        # what ProofTrace needs to re-run the same agent line-up for what-if analysis
        self.config = {"inject_faults": {k: v for k, v in faults.items() if v in ("permanent", "adversarial")},
                       "remote_connectivity": remote_connectivity, "trustguard": trustguard}
        self.required = dict(self.REQUIRED)
        self.last_norm_result = None
        self.last_audit: dict | None = None
        self.last_reply_id: str | None = None
        self.bus = MessageBus()
        for cls in (PerformanceAgent, InfrastructureAgent, ConnectivityAgent,
                    CorrelationAgent, ReportingAgent):
            self.bus.register(cls(fault=faults.get(cls.name)))
        if remote_connectivity:   # swap the local connectivity agent for a foreign one behind an adapter
            from .remote import RemoteConnectivityAgent
            self.bus.register(RemoteConnectivityAgent(remote_connectivity, fault=faults.get("connectivity_agent")))
        if trustguard:
            from .trustguard import TrustGuardAgent
            self.bus.register(TrustGuardAgent(fault=faults.get("trustguard")))
            self.required["trustguard"] = "audit_request"
        self.bus.register(self)  # so replies addressed to the orchestrator are valid
        self.health: dict[str, dict] = {}
        self.cards: dict[str, dict] = {}
        self.last_norm: dict = {"devices": {}, "topology": {"devices": []}}

    def handle(self, env):  # never called: the orchestrator only receives replies
        raise RuntimeError("orchestrator does not accept requests")

    # ---------------------------------------------------------------- helpers
    def _call(self, recipient: str, msg_type: str, payload: dict, cid: str, retries: int | None = None):
        """Send a request; retry on failure. Returns reply payload or None if the agent is lost."""
        retries = self.max_retries if retries is None else retries
        last = None
        for attempt in range(1, retries + 2):
            try:
                reply = self.bus.request(make_envelope(self.name, recipient, msg_type, payload, cid))
                self.last_reply_id = reply.message_id
                self.health[recipient] = {"status": "ok" if attempt == 1 else "recovered", "attempts": attempt}
                return reply.payload
            except Exception as exc:
                last = exc
        self.health[recipient] = {"status": "failed", "attempts": retries + 1, "error": str(last)}
        return None

    # ---------------------------------------------------------------- pipeline
    def run(self, raw: Any, incident_id: str | None = None) -> dict:
        norm = normalize(raw)
        incident = incident_id or (raw.get("incident_id") if isinstance(raw, dict) else None) or "INC-0001"
        rep = self.run_normalized(norm, str(incident))
        if self.trustguard and "trustguard" in rep:
            rep["trustguard"]["before_after"] = self._before_after(norm, str(incident), rep)
        if self.prooftrace:
            from .prooftrace import build_prooftrace
            rep["prooftrace"] = build_prooftrace(self, norm, raw, rep)
        return rep

    def run_normalized(self, norm, cid: str) -> dict:
        """Diagnose already-normalised telemetry (also used by ProofTrace what-if analysis)."""
        self.bus.log.clear()
        self.health = {}
        self.cards = {}
        self.last_audit = None
        self.last_norm_result = norm
        self.last_norm = {"devices": norm.devices, "topology": norm.topology}
        meta = {"completeness": norm.completeness, "stats": norm.stats, "issues": norm.issues}

        if norm.fatal:
            return self._finish(cid, {"incident_id": cid, "reason": norm.fatal, "diagnosis": None,
                                      "verification": None, "meta": {**meta, "agent_health": {}}})

        # 0. discovery + version handshake
        incompatible = self._handshake(cid)

        # 1. fan-out
        req = {"devices": norm.devices, "topology": norm.topology}
        # the auditor holds no evidence of its own: losing it is reported separately, not as a failed analyst
        batches, failed, sent = [], [a for a in incompatible if a != "trustguard"], []
        for agent in ANALYSIS_AGENTS:
            if agent in incompatible:
                continue
            out = self._call(agent, "analyze_request", req, cid)
            (batches.append(out) if out else failed.append(agent))
            if out:
                sent.append({"message_id": self.last_reply_id, "payload": out})
        if not batches:
            return self._finish(cid, {"incident_id": cid, "reason": "all analysis agents failed",
                                      "diagnosis": None, "verification": None,
                                      "meta": {**meta, "agent_health": self.health}})

        # 1b. TrustGuard: audit every claim against the telemetry; only audited findings reach correlation
        if self.trustguard:
            batches, meta["trustguard"] = self._audit(norm, sent, batches, incompatible, cid)

        # 2. correlate (+ 3. verify). Correlation is essential: a failure here is fatal.
        diag = self._call("correlation_agent", "correlate_request",
                          {"devices": norm.devices, "batches": batches, "failed_agents": failed,
                           "completeness": norm.completeness}, cid)
        if diag:
            diag = self._challenge_if_ambiguous(diag, norm.devices, batches, failed, norm.completeness, cid)
        ver = None
        if diag:
            ver = self._call("correlation_agent", "verify_request",
                             {"diagnosis": diag, "devices": norm.devices}, cid)
        if not diag or not ver:
            return self._finish(cid, {"incident_id": cid, "reason": "correlation agent failed",
                                      "diagnosis": None, "verification": None,
                                      "meta": {**meta, "agent_health": self.health}})
        return self._finish(cid, {"incident_id": cid, "diagnosis": diag, "verification": ver,
                                  "meta": {**meta, "agent_health": self.health}})

    def _audit(self, norm, sent: list[dict], batches: list[dict], incompatible: list[str], cid: str):
        """Send the logged finding batches to TrustGuard; return (batches for correlation, report summary)."""
        if "trustguard" in incompatible:
            return batches, {"status": "unavailable", "reason": self.health["trustguard"]["error"]}
        res = self._call("trustguard", "audit_request",
                         {"devices": norm.devices, "batches": sent,
                          "cards": {a: c for a, c in self.cards.items() if a in ANALYSIS_AGENTS}}, cid)
        if res is None:   # degrade: proceed with unaudited findings, and say so in the report
            return batches, {"status": "unavailable", "reason": self.health["trustguard"]["error"]}
        a = res["audit"]
        self.last_audit = {**a, "message_id": self.last_reply_id}
        return res["audited_batches"], {"status": "audited", "audit_message_id": self.last_reply_id,
                                        "summary": a["summary"], "flagged": a["flagged"],
                                        "unverifiable": a["unverifiable"], "agents": a["agents"]}

    def _before_after(self, norm, cid: str, after: dict) -> dict:
        """What the same agents would have concluded without TrustGuard (full pipeline re-run, no side effects).

        Only re-run when the audit changed something: if every claim was trusted, the audited findings are
        identical to the originals and the diagnosis is the same by construction."""
        def view(r: dict) -> dict:
            return {"status": r["status"], "root_cause_type": r.get("root_cause_type"),
                    "leading_hypothesis": r.get("leading_hypothesis"),
                    "root_cause_devices": r.get("root_cause_devices", []), "confidence": r["confidence"]}
        s = (after.get("trustguard") or {}).get("summary") or {}
        a = view(after)
        if not (s.get("flagged") or s.get("unverifiable")):
            return {"computed": False, "reason": "every claim was trusted: audited findings equal the originals",
                    "before": a, "after": a, "diagnosis_changed": False, "confidence_delta": 0.0,
                    "sufficient_evidence_after": a["status"] in ("diagnosed", "tentative", "healthy")}
        shadow = Orchestrator(inject_faults=self._faults, max_retries=self.max_retries,
                              remote_connectivity=self.config["remote_connectivity"], prooftrace=False,
                              trustguard=False).run_normalized(norm, cid + "-UNAUDITED")
        b = view(shadow)
        return {"computed": True, "engine": "full pipeline re-run with the same agents and TrustGuard disabled",
                "before": b, "after": a,
                "diagnosis_changed": (b["root_cause_type"], b["status"], b["root_cause_devices"]) !=
                                     (a["root_cause_type"], a["status"], a["root_cause_devices"]),
                "confidence_delta": round(a["confidence"] - b["confidence"], 3),
                "sufficient_evidence_after": a["status"] in ("diagnosed", "tentative", "healthy")}

    REQUIRED = {"performance_agent": "analyze_request", "infrastructure_agent": "analyze_request",
                "connectivity_agent": "analyze_request", "correlation_agent": "correlate_request",
                "reporting_agent": "report_request"}

    def _handshake(self, cid: str) -> list[str]:
        """Ask every agent for its card; exclude agents that cannot speak our protocol version or
        do not accept the message type we need from them."""
        self.cards, bad = {}, []
        for agent, needed in self.required.items():
            card = self._call(agent, "capability_request", {}, cid, retries=0)
            if card is None:
                continue  # unreachable: the normal retry/degrade path handles it when work is sent
            self.cards[agent] = card
            why = None
            neg = card.get("negotiation") or {}
            try:
                AgentCard.model_validate(card)
            except ValidationError as exc:
                why = "invalid agent card: " + "; ".join(e["msg"] for e in exc.errors())
            if why:
                pass
            elif neg.get("status") == "incompatible":
                why = f"format negotiation failed: {neg.get('reason')}"
            elif not set(card["protocol_versions"]) & set(SUPPORTED_PROTOCOL_VERSIONS):
                why = f"speaks protocol {card['protocol_versions']}, need {list(SUPPORTED_PROTOCOL_VERSIONS)}"
            elif needed not in card["accepts"]:
                why = f"does not accept '{needed}'"
            if why:
                self.health[agent] = {"status": "incompatible", "attempts": 1, "error": why}
                bad.append(agent)
        return bad

    def _challenge_if_ambiguous(self, diag, devices, batches, failed, completeness, cid):
        """If the top two hypotheses are too close, ask the specialists for graded evidence and re-score."""
        from .signals import DOMAIN_SIGNALS
        if diag["status"] != "candidate" or diag["margin"] >= AMBIGUITY_MARGIN or len(diag["ranking"]) < 2:
            return diag
        device = diag["root_cause_devices"][0]
        wanted = {s for r in diag["ranking"][:2] for s in EXPECTED[r["hypothesis"]]}
        answers = {}
        for domain, agent in DOMAIN_AGENT.items():
            sigs = sorted(wanted & set(DOMAIN_SIGNALS[domain]))
            if not sigs or agent in failed:
                continue
            out = self._call(agent, "challenge_request",
                             {"device_id": device, "signals": sigs, "devices": {device: devices[device]}}, cid)
            if out:
                answers.update(out["answers"])
        if not answers:
            return diag
        again = self._call("correlation_agent", "correlate_request",
                           {"devices": devices, "batches": batches, "failed_agents": failed,
                            "completeness": completeness,
                            "challenge": {"device_id": device, "answers": answers,
                                          "leader_before": diag["hypothesis"]}}, cid)
        return again or diag

    def _finish(self, cid: str, payload: dict) -> dict:
        payload.setdefault("reason", "")
        report = self._call("reporting_agent", "report_request", payload, cid)
        if report is None:  # last resort: still return something structured
            report = {"incident_id": cid, "status": "error",
                      "suspected_root_cause": "No diagnosis possible: reporting agent failed",
                      "confidence": 0.0, "affected_devices": [], "supporting_evidence": [],
                      "recommended_actions": [], "limitations": ["reporting agent failed"]}
        report["protocol"] = {"version": "1.0", "messages_exchanged": len(self.bus.log)}
        return report

    def run_file(self, path: str | Path, **kw) -> dict:
        try:
            raw = json.loads(Path(path).read_text())
        except FileNotFoundError:
            raw = None
            msg = f"input file not found: {path}"
        except json.JSONDecodeError as exc:
            raw = None
            msg = f"input is not valid JSON ({exc.msg} at line {exc.lineno})"
        if raw is None:
            cid = "INC-INPUT-ERROR"
            self.bus.log.clear()
            self.health = {}
            return self._finish(cid, {"incident_id": cid, "reason": msg, "diagnosis": None,
                                      "verification": None,
                                      "meta": {"completeness": 0.0, "stats": {},
                                               "issues": [{"level": "error", "message": msg,
                                                           "device_id": None, "field": None,
                                                           "record_index": None}],
                                               "agent_health": {}}})
        return self.run(raw, **kw)
