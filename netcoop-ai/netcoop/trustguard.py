"""TrustGuard: evidence-grounded audit of specialist findings before they reach correlation.

The correlation agent fuses whatever the specialists send. TrustGuard sits between the two and checks every
claim in every `finding_batch` against the normalised telemetry:

  vote      "I believe cause H on device D with strength v"
  signal    "signal S on D has graded strength s" (and "S is present")
  evidence  "metric M on D has value x"
  scope     the connectivity agent's root / downstream analysis

Each claim gets one decision:

  trusted       consistent with the telemetry
  flagged       demonstrably contradicted by the telemetry or outside the agent's declared authority
  unverifiable  cannot be checked because the telemetry it would need is missing

and the batch is filtered *claim by claim*: a flagged vote is removed, an unverifiable vote is capped at
UNVERIFIABLE_CAP, a flagged or unverifiable signal / evidence item is left out of coverage, but every other
claim of the same agent passes unchanged. TrustGuard never adds a vote, never changes a trusted claim and never
produces a diagnosis; correlation stays with the correlation agent.

What TrustGuard does NOT do: it never compares a vote with the leading hypothesis or with other agents.
Disagreement is not evidence of a fault; only a mismatch between a claim and the telemetry is.

Independence. Signal strengths are recomputed here from the canonical metrics with this module's own
implementation (`recompute_strength`), not with the agents' code. The *constants* are shared on purpose:
the alarm thresholds and warning onsets (signals.THRESHOLDS / signals.ONSETS) are the documented domain
definition of each signal, and SIGNATURE (agents.SIGNATURE) is the documented list of symptoms each cause can
explain. Vote rules are not shared: TrustGuard does not call any agent's vote function. Instead it applies
two evidence bounds that every honest vote satisfies (tests/test_trustguard.py checks them on 900 incidents):

  1. evidence ceiling   vote <= max strength of a symptom of H the agent can observe + CEILING_TOLERANCE
  2. specificity        a vote >= SPECIFIC_VOTE needs a cause-specific indicator of H (CAUSE_INDICATORS) the
                        agent can observe, with strength >= SPECIFIC_STRENGTH. Latency, jitter and loss are
                        symptoms of almost every cause, so they cannot carry a confident claim on their own.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .agents import AUTHORITY, SIGNATURE, BaseAgent
from .protocol import Envelope
from .signals import BAD_STATUSES, DOMAIN_SIGNALS, ONSETS, THRESHOLDS

AUDIT_VERSION = "1.0"
STRENGTH_TOLERANCE = 0.05   # reported vs recomputed graded strength
CEILING_TOLERANCE = 0.10    # vote may exceed the strongest observable symptom by this much (rounding, noisy-OR)
SPECIFIC_VOTE = 0.5         # votes at or above this level are "confident" and need cause-specific evidence
SPECIFIC_STRENGTH = 0.5
UNVERIFIABLE_CAP = 0.25     # = the non-discriminating vote level honest agents use when they cannot tell
VALUE_TOLERANCE = 1e-6

# Cause-specific indicators: what distinguishes a cause from its symptoms (domain knowledge, independent of
# the agents' vote rules). Hardware failure is distinguished by a failing device (Critical status) and
# physical-layer faults; CPU saturation alone points to overload.
CAUSE_INDICATORS: dict[str, tuple[str, ...]] = {
    "link_congestion": ("high_utilization", "queue_drops"),
    "interface_fault": ("interface_errors", "link_flaps"),
    "weak_wifi": ("weak_signal", "retransmissions"),
    "device_overload": ("high_cpu", "high_memory"),
    "hardware_failure": ("device_critical", "interface_errors", "link_flaps"),
    "dns_failure": ("dns_failures",),
    "dhcp_failure": ("dhcp_failures",),
}

FLAG_CODES = {
    "UNKNOWN_DEVICE": "the finding is about a device that is not in the telemetry",
    "OUT_OF_DOMAIN_CLAIM": "the agent's card does not declare this hypothesis",
    "FOREIGN_DOMAIN_SIGNAL": "the signal belongs to another specialist's domain",
    "STRENGTH_MISMATCH": "reported signal strength differs from the strength recomputed from telemetry",
    "SIGNAL_NOT_PRESENT": "the signal is reported present but the telemetry is below its alarm threshold",
    "EVIDENCE_DEVICE_MISMATCH": "the evidence item names a different device than its finding",
    "EVIDENCE_VALUE_MISMATCH": "the evidence value differs from the normalised telemetry",
    "VOTE_EVIDENCE_MISMATCH": "the vote exceeds the strongest observable symptom of the hypothesis",
    "UNSUPPORTED_CERTAINTY": "a confident vote without any cause-specific indicator in the telemetry",
    "SELF_CONTRADICTION": "the agent's own reported signals do not support its vote",
    "SCOPE_MISMATCH": "the topology scope does not match the degraded devices in the telemetry",
}
UNVERIFIABLE_CODES = {
    "MISSING_TELEMETRY": "the metric needed to check this claim is not in the telemetry",
    "VOTE_UNVERIFIABLE": "the telemetry needed to support or refute this vote is missing",
}


# ------------------------------------------------------------------------------ independent recomputation
def recompute_strength(signal: str, metrics: dict, status: str | None) -> float | None:
    """Graded strength of `signal` from canonical telemetry, implemented independently of signals.graded.

    0 at or below the warning onset, 1 at or beyond the alarm threshold, linear in between;
    None when the metric (or, for device_critical, the status) is missing."""
    if signal == "device_critical":
        if status is None or status == "Unknown":
            return None
        return 1.0 if status == "Critical" else 0.0
    metric, op, alarm = THRESHOLDS[signal][:3]
    value = metrics.get(metric)
    if value is None:
        return None
    onset = ONSETS[signal]
    if op == ">=":
        frac = (value - onset) / (alarm - onset)
    else:   # lower is worse (RSSI)
        frac = (onset - value) / (onset - alarm)
    return round(min(1.0, max(0.0, frac)), 3)


def _strength_consistent(reported: float, expected: float) -> bool:
    """Graded agreement within tolerance, or a binary report that matches the alarm-threshold state
    (foreign agents such as WirelessOps report 0/1 instead of a graded value)."""
    if abs(reported - expected) <= STRENGTH_TOLERANCE:
        return True
    return reported in (0.0, 1.0) and reported == (1.0 if expected >= 1.0 else 0.0)


def finding_digest(finding: dict) -> str:
    """SHA-256 of a finding as sent (canonical JSON). Detects a finding altered after it was audited."""
    return hashlib.sha256(json.dumps(finding, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _independently_degraded(dev: dict) -> bool:
    if dev.get("status") in BAD_STATUSES:
        return True
    return any((recompute_strength(s, dev["metrics"], dev.get("status")) or 0) >= 1
               for s in THRESHOLDS)


# ------------------------------------------------------------------------------ audit
class _Audit:
    def __init__(self, devices: dict, cards: dict):
        self.devices, self.cards = devices, cards
        self.records: list[dict] = []

    def add(self, *, kind: str, agent: str, device_id: str | None, finding_id: str | None, message_id: str | None,
            subject: str, reported: Any, expected: dict, flags: list[str], unverifiable: list[str],
            explanation: str, telemetry: list[dict], digest: str | None) -> dict:
        decision = "flagged" if flags else "unverifiable" if unverifiable else "trusted"
        rec = {"record_id": f"TG-{len(self.records) + 1:03d}", "kind": kind, "agent": agent,
               "device_id": device_id, "finding_id": finding_id, "message_id": message_id, "subject": subject,
               "reported": reported, "expected": expected, "decision": decision,
               "reason_codes": flags + unverifiable if (flags or unverifiable) else ["CONSISTENT"],
               "explanation": explanation, "telemetry_refs": telemetry, "finding_sha256": digest}
        self.records.append(rec)
        return rec

    # -- what an agent may claim, from its validated Agent Card (falls back to its domain's signals)
    def observable(self, agent: str, domain: str) -> tuple[set[str], set[str] | None]:
        card = self.cards.get(agent) or {}
        sigs = set(card.get("signals") or DOMAIN_SIGNALS.get(domain, ()))
        hyps = set(card["hypotheses"]) if card.get("hypotheses") else None
        return sigs, hyps

    def telemetry_ref(self, did: str, signal: str) -> dict:
        dev = self.devices[did]
        if signal == "device_critical":
            return {"signal": signal, "metric": "status", "value": dev.get("status"),
                    "strength": recompute_strength(signal, dev["metrics"], dev.get("status"))}
        metric = THRESHOLDS[signal][0]
        return {"signal": signal, "metric": metric, "value": dev["metrics"].get(metric),
                "strength": recompute_strength(signal, dev["metrics"], dev.get("status"))}

    # -- one finding
    def finding(self, batch: dict, mid: str | None, f: dict) -> None:
        agent, domain, did = batch["agent"], batch["domain"], f["device_id"]
        digest = finding_digest(f)
        common = {"agent": agent, "device_id": did, "finding_id": f["finding_id"], "message_id": mid,
                  "digest": digest}
        if did not in self.devices:
            for h, v in sorted(f["votes"].items()):
                self.add(kind="vote", subject=h, reported=v, expected={}, flags=["UNKNOWN_DEVICE"],
                         unverifiable=[], telemetry=[],
                         explanation=f"{agent} votes {h}={v:.2f} for {did}, which is not in the telemetry", **common)
            if not f["votes"]:
                self.add(kind="finding", subject=did, reported=None, expected={}, flags=["UNKNOWN_DEVICE"],
                         unverifiable=[], telemetry=[],
                         explanation=f"{agent} reports on {did}, which is not in the telemetry", **common)
            return
        dev = self.devices[did]
        sigs, hyps = self.observable(agent, domain)
        st = {s: recompute_strength(s, dev["metrics"], dev.get("status")) for s in sigs if s in ONSETS or
              s == "device_critical"}

        # A. evidence consistency: every reported signal strength and every "present" claim
        reported = dict(f.get("signal_strength") or {})
        for s in f.get("signals_present", []):
            reported.setdefault(s, 1.0)
        for s, val in sorted(reported.items()):
            flags, unv = [], []
            known = s in ONSETS or s == "device_critical"
            exp = recompute_strength(s, dev["metrics"], dev.get("status")) if known else None
            if s not in sigs:
                flags.append("FOREIGN_DOMAIN_SIGNAL")
            if known and exp is None:
                unv.append("MISSING_TELEMETRY")
            elif known:
                if not _strength_consistent(val, exp):
                    flags.append("STRENGTH_MISMATCH")
                if s in f.get("signals_present", []) and exp < 1.0:
                    flags.append("SIGNAL_NOT_PRESENT")
            elif not flags:
                unv.append("MISSING_TELEMETRY")
            ref = self.telemetry_ref(did, s) if known else {"signal": s}
            why = (f"{agent} reports {s}={val:.2f}; recomputed from telemetry: "
                   + ("not measurable" if exp is None else f"{exp:.2f}"))
            if "FOREIGN_DOMAIN_SIGNAL" in flags:
                why += f"; {s} is outside {agent}'s declared signals"
            self.add(kind="signal", subject=s, reported=val, expected={"strength": exp}, flags=flags,
                     unverifiable=unv, telemetry=[ref], explanation=why, **common)

        for i, e in enumerate(f.get("evidence", [])):
            flags, unv = [], []
            if e.get("device_id") not in (None, did):
                flags.append("EVIDENCE_DEVICE_MISMATCH")
            actual = dev.get("status") if e["metric"] == "status" else dev["metrics"].get(e["metric"])
            if actual is None and e["metric"] != "status":
                unv.append("MISSING_TELEMETRY")
            elif isinstance(e.get("value"), (int, float)) and isinstance(actual, (int, float)):
                if abs(e["value"] - actual) > VALUE_TOLERANCE * max(1.0, abs(actual)):
                    flags.append("EVIDENCE_VALUE_MISMATCH")
            elif e.get("value") != actual:
                flags.append("EVIDENCE_VALUE_MISMATCH")
            self.add(kind="evidence", subject=f"{e['metric']}#{i}", reported=e.get("value"),
                     expected={"value": actual}, flags=flags, unverifiable=unv,
                     telemetry=[{"metric": e["metric"], "value": actual}],
                     explanation=f"{agent} cites {e['metric']}={e.get('value')} on {e.get('device_id') or did}; "
                                 f"telemetry has {actual}", **common)

        # B-D. vote consistency, domain authority, missing evidence
        for h, v in sorted(f["votes"].items()):
            flags, unv = [], []
            symptoms = sorted(SIGNATURE.get(h, set()) & sigs)
            indicators = sorted(set(CAUSE_INDICATORS.get(h, ())) & sigs)
            known = {s: st[s] for s in symptoms if st.get(s) is not None}
            ceiling = max(known.values(), default=None)
            spec = {s: st[s] for s in indicators if st.get(s) is not None}
            specific = max(spec.values(), default=None)
            if (hyps is not None and h not in hyps) or not symptoms:
                flags.append("OUT_OF_DOMAIN_CLAIM")       # not declared, or nothing of H it could observe
            elif ceiling is None:
                unv.append("VOTE_UNVERIFIABLE")
            elif v > ceiling + CEILING_TOLERANCE:
                if len(known) < len(symptoms):            # a missing symptom might have supported it
                    unv.append("VOTE_UNVERIFIABLE")
                else:
                    flags.append("VOTE_EVIDENCE_MISMATCH")
            if v >= SPECIFIC_VOTE and symptoms:
                if not indicators:
                    flags.append("UNSUPPORTED_CERTAINTY")
                elif specific is None or (specific < SPECIFIC_STRENGTH and len(spec) < len(indicators)):
                    if "VOTE_UNVERIFIABLE" not in unv:    # the missing indicator might have supported it
                        unv.append("VOTE_UNVERIFIABLE")
                elif specific < SPECIFIC_STRENGTH:
                    flags.append("UNSUPPORTED_CERTAINTY")
            flags = list(dict.fromkeys(flags))
            own = [reported.get(s) for s in indicators if s in reported]
            if v >= SPECIFIC_VOTE and own and max(own) < SPECIFIC_STRENGTH:
                flags.append("SELF_CONTRADICTION")
            parts = [f"{agent} votes {h}={v:.2f} on {did}"]
            if ceiling is not None:
                top = max(known, key=known.get)
                parts.append(f"strongest observable symptom {top}={ceiling:.2f}")
            if indicators:
                parts.append("cause-specific indicators " + ", ".join(
                    f"{s}={'missing' if st.get(s) is None else format(st[s], '.2f')}" for s in indicators))
            if "SELF_CONTRADICTION" in flags:
                parts.append("its own report gives " + ", ".join(
                    f"{s}={reported[s]:.2f}" for s in indicators if s in reported))
            if not flags and not unv:
                parts.append("supported")
            self.add(kind="vote", subject=h, reported=v,
                     expected={"ceiling": ceiling, "specific_support": specific,
                               "ceiling_tolerance": CEILING_TOLERANCE, "authority": domain in AUTHORITY.get(h, ())},
                     flags=flags, unverifiable=unv, explanation="; ".join(parts),
                     telemetry=[self.telemetry_ref(did, s) for s in symptoms], **common)

    def scope(self, batch: dict, mid: str | None) -> None:
        sc = batch["scope"]
        degraded = sorted(d for d, dev in self.devices.items() if _independently_degraded(dev))
        claimed = set(sc.get("degraded", []))
        flags = []
        if claimed != set(degraded) or not set(sc.get("root_candidates", [])) <= claimed \
                or not set(sc.get("downstream", {})) <= claimed:
            flags.append("SCOPE_MISMATCH")
        extra, missing = sorted(claimed - set(degraded)), sorted(set(degraded) - claimed)
        why = f"{batch['agent']} scope lists {len(claimed)} degraded device(s); telemetry has {len(degraded)}"
        if extra:
            why += f"; not degraded or unknown: {', '.join(extra)}"
        if missing:
            why += f"; missing: {', '.join(missing)}"
        self.add(kind="scope", agent=batch["agent"], device_id=None, finding_id=None, message_id=mid,
                 subject="scope", reported=sorted(claimed), expected={"degraded": degraded}, flags=flags,
                 unverifiable=[], explanation=why, telemetry=[], digest=None)


def audit_batches(devices: dict, batches: list[dict], cards: dict | None = None,
                  incident_id: str | None = None) -> dict:
    """Audit every claim in `batches` ([{message_id, payload}] or bare finding_batch payloads).

    Returns {"audit": {...records, summary...}, "audited_batches": [...]}; deterministic for the same input."""
    a = _Audit(devices, cards or {})
    payloads: list[tuple[str | None, dict]] = []
    for b in batches:
        mid, p = (b.get("message_id"), b["payload"]) if "payload" in b else (None, b)
        payloads.append((mid, p))
        for f in p.get("findings", []):
            a.finding(p, mid, f)
        if "scope" in p:
            a.scope(p, mid)
    audited = [apply_audit(p, a.records) for _, p in payloads]
    return {"audit": summarise(a.records, incident_id), "audited_batches": audited}


def apply_audit(batch: dict, records: list[dict]) -> dict:
    """Filter one batch claim by claim according to the audit records (pure function)."""
    out = copy.deepcopy(batch)
    mine = [r for r in records if r["agent"] == batch["agent"]]
    findings = []
    for f in out.get("findings", []):
        rs = [r for r in mine if r["finding_id"] == f["finding_id"] and r["device_id"] == f["device_id"]]
        if any("UNKNOWN_DEVICE" in r["reason_codes"] for r in rs):
            continue
        removed, capped, dropped_sig, dropped_ev = {}, {}, [], []
        for r in rs:
            if r["decision"] == "trusted":
                continue
            if r["kind"] == "vote" and r["subject"] in f["votes"]:
                if r["decision"] == "flagged":
                    removed[r["subject"]] = f["votes"].pop(r["subject"])
                else:
                    capped[r["subject"]] = f["votes"][r["subject"]]
                    f["votes"][r["subject"]] = min(f["votes"][r["subject"]], UNVERIFIABLE_CAP)
            elif r["kind"] == "signal":
                f.get("signal_strength", {}).pop(r["subject"], None)
                if r["subject"] in f.get("signals_present", []):
                    f["signals_present"].remove(r["subject"])
                dropped_sig.append(r["subject"])
            elif r["kind"] == "evidence":
                dropped_ev.append(int(r["subject"].rsplit("#", 1)[1]))
        if dropped_ev:
            f["evidence"] = [e for i, e in enumerate(f["evidence"]) if i not in dropped_ev]
        dropped_metrics = {THRESHOLDS[s][0] if s in THRESHOLDS else "status" for s in dropped_sig}
        f["evidence"] = [e for e in f.get("evidence", []) if e["metric"] not in dropped_metrics]
        f["trustguard"] = {"records": [r["record_id"] for r in rs], "removed_votes": removed,
                           "capped_votes": capped, "excluded_signals": sorted(dropped_sig),
                           "excluded_evidence": len(dropped_ev)}
        findings.append(f)
    out["findings"] = findings
    if "scope" in out and any(r["kind"] == "scope" and r["decision"] == "flagged" for r in mine):
        out["scope_rejected"] = out.pop("scope")   # correlation falls back to its topology-free scope
    return out


def summarise(records: list[dict], incident_id: str | None = None) -> dict:
    count = {d: sum(r["decision"] == d for r in records) for d in ("trusted", "flagged", "unverifiable")}
    agents: dict[str, dict] = {}
    for r in records:
        a = agents.setdefault(r["agent"], {"checked": 0, "trusted": 0, "flagged": 0, "unverifiable": 0})
        a["checked"] += 1
        a[r["decision"]] += 1
    votes = [r for r in records if r["kind"] == "vote"]
    return {
        "audit_version": AUDIT_VERSION, "incident_id": incident_id, "auditor": "trustguard",
        "summary": {"checked": len(records), "accepted": count["trusted"], "flagged": count["flagged"],
                    "unverifiable": count["unverifiable"], "votes_checked": len(votes),
                    "votes_flagged": sum(r["decision"] == "flagged" for r in votes),
                    "votes_unverifiable": sum(r["decision"] == "unverifiable" for r in votes)},
        "agents": agents,
        "flagged": [{k: r[k] for k in ("record_id", "agent", "device_id", "kind", "subject", "reported",
                                       "reason_codes", "explanation")} for r in records if r["decision"] == "flagged"],
        "unverifiable": [{k: r[k] for k in ("record_id", "agent", "device_id", "kind", "subject", "reported",
                                            "reason_codes", "explanation")}
                         for r in records if r["decision"] == "unverifiable"],
        "parameters": {"strength_tolerance": STRENGTH_TOLERANCE, "ceiling_tolerance": CEILING_TOLERANCE,
                       "specific_vote": SPECIFIC_VOTE, "specific_strength": SPECIFIC_STRENGTH,
                       "unverifiable_cap": UNVERIFIABLE_CAP},
        "records": records,
    }


def decision_key(r: dict) -> tuple:
    """The parts of a record that a re-run of the audit must reproduce exactly."""
    return (r["record_id"], r["kind"], r["agent"], r["device_id"], r["finding_id"], r["message_id"], r["subject"],
            json.dumps(r["reported"], sort_keys=True, default=str), r["decision"], tuple(r["reason_codes"]),
            r["finding_sha256"])


# ------------------------------------------------------------------------------ bus agent
class TrustGuardAgent(BaseAgent):
    """Auditor on the bus: `audit_request` {devices, batches[{message_id, payload}], cards} -> `audit_result`.

    Being an ordinary protocol participant means its decisions are logged, hashed into the ProofTrace chain
    and replayable like every other message. It can fail like any agent; the orchestrator then proceeds with
    unaudited findings and says so in the report."""
    name = "trustguard"
    description = ("Audits every specialist claim against the normalised telemetry before correlation: "
                   "trusted / flagged / unverifiable, filtered claim by claim. Never diagnoses.")
    accepts, produces = ("audit_request",), ("audit_result",)

    def _handle(self, env: Envelope) -> Envelope:
        if env.msg_type != "audit_request":
            raise ValueError(f"{self.name} cannot handle '{env.msg_type}'")
        p = env.payload
        res = audit_batches(p["devices"], p["batches"], p.get("cards"), env.correlation_id)
        return self._reply(env, "audit_result", res)
