"""ProofTrace: an evidence-backed, independently checkable account of one diagnosis.

A report says *what* the system concluded. A ProofTrace says *why*, in a form a third party can check
without trusting NetCoop:

  raw input record -> field -> unit conversion -> aggregation -> canonical value -> graded signal
     -> agent finding (message id) -> vote -> fused hypothesis score -> verdict

It contains
  * evidence      every observed signal on the blamed device(s), with the raw samples it came from and
                  the agent messages that reported it
  * hypotheses    all 7 candidate causes: votes (with message ids), supporting / contradicting / missing
                  evidence, unexplained symptoms, and the concrete reasons each alternative was rejected
  * agents        what each agent contributed, and a leave-one-out re-correlation of the logged findings
                  showing whether the conclusion depends on it
  * sensitivity   what-if re-diagnoses: which single measurement change would flip the conclusion
  * missing_information  measurements that would decide between the leading hypotheses
  * integrity     SHA-256 digest of every protocol message plus a chain digest of the whole log
  * checks        result of `verify_prooftrace`, which re-derives every claim from the raw input and the
                  message log (run it again yourself: `python -m netcoop verify-trace ...`)

Nothing here is a hard-coded narrative: every sentence is generated from the logged messages and the
telemetry, and `verify_prooftrace` fails if the trace, the log or the input is altered.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .agents import (AUTHORITY, COVERAGE_FLOOR, EXPECTED, MUST_BE_ABSENT, NON_AUTHORITY_WEIGHT, SIGNATURE,
                     CorrelationAgent, noisy_or)
from .normalizer import RECORD_LIST_KEYS, DEVICE_KEYS, normalize
from .protocol import HYPOTHESES
from .signals import ONSETS, THRESHOLDS, graded

TRACE_VERSION = "1.0"
# the verifier's TrustGuard checks (see _verify_trustguard)
TRUSTGUARD_CHECKS = ("audit recorded in trace", "audit message exists", "trace audit records match logged audit",
                     "audit request exists", "audited findings come from logged agent messages",
                     "findings unchanged since audit", "audit reconstructed from telemetry and agent messages",
                     "audited batches are the filtered originals", "correlation received only audited findings")
MAX_WHATIFS = 12


# ----------------------------------------------------------------------------------- integrity
def message_digest(msg: dict) -> str:
    return hashlib.sha256(json.dumps(msg, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def chain_digest(log: list[dict]) -> str:
    h = hashlib.sha256()
    for m in log:
        h.update(message_digest(m).encode())
    return h.hexdigest()


def _records(raw: Any) -> list:
    """The input record list exactly as the normalizer indexes it."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        recs = next((raw[k] for k in RECORD_LIST_KEYS if isinstance(raw.get(k), list)), None)
        if recs is None and any(raw.get(k) for k in DEVICE_KEYS):
            return [raw]
        return recs or []
    return []


def _batches(log: list[dict]) -> dict[str, dict]:
    """agent -> the findings correlation actually used.

    Without TrustGuard that is the agent's last finding_batch (retries leave only the successful one). With
    TrustGuard it is the agent's audited batch inside the audit_result message; `source_message_id` keeps the
    link to the original finding_batch."""
    out = {}
    for m in log:
        if m["msg_type"] == "finding_batch":
            out[m["payload"]["agent"]] = m
    audit = _last(log, "audit_result")
    if audit:
        for b in audit["payload"]["audited_batches"]:
            src = out.get(b["agent"])
            out[b["agent"]] = {"message_id": audit["message_id"], "msg_type": "audit_result", "sender": b["agent"],
                               "source_message_id": src["message_id"] if src else None, "payload": b}
    return out


def _batch_view(m: dict | None, agent: str) -> dict | None:
    """The batch payload `agent` contributed in message `m` (a finding_batch, or its audited copy)."""
    if not m:
        return None
    if m["msg_type"] == "finding_batch":
        return m["payload"] if m["sender"] == agent else None
    if m["msg_type"] == "audit_result":
        return next((b for b in m["payload"]["audited_batches"] if b["agent"] == agent), None)
    return None


def _last(log: list[dict], msg_type: str) -> dict | None:
    return next((m for m in reversed(log) if m["msg_type"] == msg_type), None)


def _finding(batch_msg: dict, device: str) -> dict | None:
    return next((f for f in batch_msg["payload"]["findings"] if f["device_id"] == device), None)


def _strengths(f: dict) -> dict[str, float]:
    return f.get("signal_strength") or {s: 1.0 for s in f["signals_present"]}


def cited_finding(log: list[dict], message_id: str, agent: str, device_id: str) -> tuple[dict | None, dict | None]:
    """(message, finding) for a citation in a trace: the agent's finding on `device_id` inside a
    finding_batch or inside the audited copy of an audit_result message."""
    m = next((x for x in log if x["message_id"] == message_id), None)
    b = _batch_view(m, agent)
    return m, (_finding({"payload": b}, device_id) if b else None)


# ----------------------------------------------------------------------------------- build
def _evidence(devices: list[str], norm, batches: dict[str, dict]) -> list[dict]:
    items = []
    for did in devices:
        dev = norm.devices[did]
        prov = norm.provenance.get(did, {})
        observed: dict[str, list[dict]] = {}
        for agent, msg in batches.items():
            f = _finding(msg, did)
            if not f:
                continue
            for sig, v in _strengths(f).items():
                if v > 0:
                    observed.setdefault(sig, []).append({"agent": agent, "message_id": msg["message_id"],
                                                         "source_message_id": msg.get("source_message_id"),
                                                         "finding_id": f["finding_id"], "strength": v})
        for sig in sorted(observed):
            if sig == "device_critical":
                metric, value, unit, thr, onset = "status", dev["status"], None, "== Critical", None
            else:
                metric, op, t, unit, _ = THRESHOLDS[sig]
                value, thr, onset = dev["metrics"].get(metric), f"{op} {t:g} {unit}", f"{ONSETS[sig]:g} {unit}"
            p = prov.get(metric, {})
            strength = max(o["strength"] for o in observed[sig])
            items.append({
                "id": f"E{len(items) + 1}", "device_id": did, "signal": sig, "metric": metric, "value": value,
                "unit": unit, "threshold": thr, "onset": onset, "strength": strength,
                "state": "present" if strength >= 1 else "elevated",
                "aggregation": p.get("aggregation", "unknown"), "raw_samples": p.get("samples", [])[:12],
                "observed_by": observed[sig],
                "explains": [h for h in HYPOTHESES if sig in SIGNATURE[h]],
                "expected_by": [h for h in HYPOTHESES if sig in EXPECTED[h]],
                "rules_out": [h for h, bad in MUST_BE_ABSENT.items() if sig in bad and strength >= 1],
            })
    return items


def _hypotheses(primary: str, norm, batches: dict[str, dict], diag: dict, verdict_h: str | None,
                committed: bool, evidence: list[dict]) -> list[dict]:
    dev = norm.devices[primary]
    ranking = {r["hypothesis"]: r for r in diag.get("ranking_all") or diag.get("ranking", [])}
    winner = ranking.get(verdict_h) if verdict_h else None
    ev_primary = [e for e in evidence if e["device_id"] == primary]
    out = []
    for h in HYPOTHESES:
        r = ranking.get(h)
        votes = []
        for agent, msg in batches.items():
            f = _finding(msg, primary)
            if f and h in f["votes"]:
                dom = msg["payload"]["domain"]
                votes.append({"agent": agent, "vote": f["votes"][h], "message_id": msg["message_id"],
                              "source_message_id": msg.get("source_message_id"),
                              "weight": 1.0 if dom in AUTHORITY[h] else NON_AUTHORITY_WEIGHT})
        expected = []
        for sig in EXPECTED[h]:
            g = graded(sig, dev["metrics"], dev["status"])
            metric = "status" if sig == "device_critical" else THRESHOLDS[sig][0]
            value = dev["status"] if sig == "device_critical" else dev["metrics"].get(metric)
            state = ("unknown" if g is None else "present" if g >= 1 else "elevated" if g > 0 else "absent")
            expected.append({"signal": sig, "metric": metric, "value": value, "strength": g, "state": state,
                             "threshold": "== Critical" if sig == "device_critical" else
                             f"{THRESHOLDS[sig][1]} {THRESHOLDS[sig][2]:g} {THRESHOLDS[sig][3]}"})
        contradicting = [{**e, "why": f"expected {e['signal']} but {e['metric']} = {e['value']} is below the "
                          f"warning onset"} for e in expected if e["state"] == "absent"]
        contradicting += [{"signal": s, "metric": next((x["metric"] for x in ev_primary if x["signal"] == s), s),
                           "why": f"{s} is present, but {h} should not produce it"}
                          for s in sorted(MUST_BE_ABSENT.get(h, set()))
                          if any(x["signal"] == s and x["strength"] >= 1 for x in ev_primary)]
        missing = [e for e in expected if e["state"] == "unknown"]
        supporting = [x["id"] for x in ev_primary if h in x["explains"]]
        unexplained = [x["id"] for x in ev_primary if h not in x["explains"]]

        if h == verdict_h:
            verdict = "selected" if committed else "leading (not committed)"
        elif r:
            verdict = "rejected"
        else:
            verdict = "not supported"
        reasons = []
        if h != verdict_h:
            if not votes:
                reasons.append("no agent observed evidence for it on " + primary)
            if r and winner:
                reasons.append(f"fused score {r['score']:.2f} vs {winner['score']:.2f} for {verdict_h}")
                if r["coverage"] < winner["coverage"] - 0.01:
                    reasons.append(f"explains {r['coverage']:.0%} of the observed symptom strength, "
                                   f"{verdict_h} explains {winner['coverage']:.0%}")
            for c in contradicting:
                reasons.append(c["why"])
            if votes and all(v["weight"] < 1 for v in votes):
                reasons.append("only voted for by agents that cannot observe this cause directly "
                               f"(weight {NON_AUTHORITY_WEIGHT})")
            if missing and not votes:
                reasons.append("could not be tested: " + ", ".join(m["metric"] for m in missing) + " not measured")
        why_selected = []
        if h == verdict_h and r:
            why_selected = [f"highest fused score {r['score']:.2f} (base vote {r['base_vote']:.2f}, "
                            f"coverage {r['coverage']:.0%})",
                            f"{sum(e['state'] == 'present' for e in expected)} of {len(expected)} expected "
                            "signals present in the raw data"]
            if r.get("graded_support") is not None:
                why_selected.append(f"challenge round graded support {r['graded_support']:.2f}")
        out.append({"hypothesis": h, "verdict": verdict, "score": r["score"] if r else 0.0,
                    "base_vote": r["base_vote"] if r else 0.0, "coverage": r["coverage"] if r else 0.0,
                    "graded_support": r.get("graded_support") if r else None,
                    "votes": votes, "supporting_evidence": supporting, "unexplained_evidence": unexplained,
                    "expected_signals": expected, "contradicting": contradicting, "missing": missing,
                    "rejection_reasons": reasons, "why_selected": why_selected})
    order = {"selected": 0, "leading (not committed)": 0, "rejected": 1, "not supported": 2}
    out.sort(key=lambda x: (order[x["verdict"]], -x["score"]))
    return out


def _offline(batches: list[dict], norm, failed: list[str]) -> dict:
    """Re-run correlation + verification on logged findings (no new agent messages)."""
    c = CorrelationAgent()
    diag = c.correlate({"devices": norm.devices, "batches": batches, "failed_agents": failed,
                        "completeness": norm.completeness})
    ver = c.verify({"diagnosis": diag, "devices": norm.devices})
    return {"status": ver["status"], "hypothesis": diag.get("hypothesis"), "confidence": ver["confidence"],
            "root_cause_devices": diag.get("root_cause_devices", [])}


def _agents(orch, batches: dict[str, dict], log: list[dict], norm, conclusion: dict, primary: str | None,
            diag_payload: dict) -> list[dict]:
    out = []
    failed = list(diag_payload.get("failed_agents", []))
    for agent, card in orch.cards.items():
        sent = [m for m in log if m["sender"] == agent]
        entry = {"agent": agent, "transport": card.get("transport"), "domain": card.get("domain"),
                 "health": orch.health.get(agent, {}).get("status", "ok"),
                 "card_message_id": next((m["message_id"] for m in sent if m["msg_type"] == "capability_response"),
                                         None),
                 "messages_sent": len(sent), "message_types": sorted({m["msg_type"] for m in sent})}
        if agent in batches:
            msg = batches[agent]
            f = _finding(msg, primary) if primary else None
            entry["findings_message_id"] = msg.get("source_message_id") or msg["message_id"]
            if msg["msg_type"] == "audit_result":
                entry["audited_message_id"] = msg["message_id"]
                entry["trustguard"] = (orch.last_audit or {}).get("agents", {}).get(agent)
            entry["devices_flagged"] = sorted(x["device_id"] for x in msg["payload"]["findings"] if x["votes"])
            if "remote" in msg["payload"]:
                entry["remote_endpoint"] = msg["payload"]["remote"]
            if f:
                top = max(f["votes"].items(), key=lambda kv: kv[1]) if f["votes"] else None
                entry["on_root_device"] = {"votes": f["votes"],
                                           "signals": {s: v for s, v in _strengths(f).items() if v > 0},
                                           "top_vote": {"hypothesis": top[0], "vote": top[1]} if top else None,
                                           "notes": f["notes"]}
                entry["agrees_with_conclusion"] = bool(top) and top[0] == conclusion["hypothesis"]
            others = [m["payload"] for a, m in batches.items() if a != agent]
            if others and conclusion["hypothesis"]:
                loo = _offline(others, norm, failed)
                changed = loo["hypothesis"] != conclusion["hypothesis"] or (
                    (loo["status"] in ("diagnosed", "tentative")) != (conclusion["status"] in ("diagnosed", "tentative")))
                delta = round(loo["confidence"] - conclusion["confidence"], 2)
                dissent = entry.get("agrees_with_conclusion") is False and (entry.get("on_root_device") or {}).get("top_vote")
                entry["leave_one_out"] = {**loo, "conclusion_changed": changed, "confidence_delta": delta,
                                          "contribution": "decisive" if changed else
                                          "corroborating" if delta <= -0.05 else
                                          "dissenting (outvoted)" if dissent else "redundant"}
        out.append(entry)
    return out


def _trustguard(orch, norm, log: list[dict], report: dict) -> dict:
    """TrustGuard section: every audit decision with its source message, original finding, telemetry
    references (down to the raw input records) and its effect on what correlation saw."""
    a = orch.last_audit
    msg = next(m for m in log if m["message_id"] == a["message_id"])
    req = next((m for m in reversed(log[:log.index(msg)]) if m["msg_type"] == "audit_request"), None)
    src = {m["message_id"]: m for m in log if m["msg_type"] == "finding_batch"}
    effects = {("vote", "flagged"): "vote removed before correlation: it did not influence the diagnosis",
               ("vote", "unverifiable"): "vote capped before correlation",
               ("signal", "flagged"): "signal excluded from correlation coverage",
               ("signal", "unverifiable"): "signal excluded from correlation coverage",
               ("evidence", "flagged"): "evidence item withheld from the report",
               ("evidence", "unverifiable"): "evidence item withheld from the report",
               ("scope", "flagged"): "scope rejected: correlation used its topology-free fallback",
               ("finding", "flagged"): "finding removed before correlation"}
    records = []
    for r in a["records"]:
        out = {**r, "timestamp": msg["timestamp"], "audit_version": a["audit_version"],
               "effect": effects.get((r["kind"], r["decision"]), "passed to correlation unchanged")}
        prov = norm.provenance.get(r["device_id"], {}) if r["device_id"] else {}
        out["telemetry_refs"] = [{**t, "record_indexes": [s["record_index"] for s in
                                                          prov.get(t.get("metric"), {}).get("samples", [])][:12]}
                                 for t in r["telemetry_refs"]]
        if r["decision"] != "trusted" and r["message_id"] in src:
            f = next((x for x in src[r["message_id"]]["payload"]["findings"]
                      if x["finding_id"] == r["finding_id"]), None)
            out["original_finding"] = f
        records.append(out)
    return {"audit_message_id": msg["message_id"], "request_message_id": req["message_id"] if req else None,
            "audit_version": a["audit_version"], "summary": a["summary"], "agents": a["agents"],
            "parameters": a["parameters"], "before_after": (report.get("trustguard") or {}).get("before_after"),
            "records": records,
            "note": "SHA-256 digests show that the audit and the findings were not altered after the run; they do "
                    "not authenticate who wrote a message (no signatures)."}


def _normal_value(sig: str) -> Any:
    if sig == "device_critical":
        return "Warning"
    op = THRESHOLDS[sig][1]
    return round(ONSETS[sig] * 0.8, 3) if op == ">=" else ONSETS[sig] + 6


def _alarm_value(sig: str) -> Any:
    return "Critical" if sig == "device_critical" else THRESHOLDS[sig][2]


def _what_if(orch, norm, cid: str, primary: str, verdict_h: str, hyps: list[dict], conclusion: dict) -> dict:
    from .orchestrator import Orchestrator

    def rerun(changes: dict[str, Any]) -> dict:
        n2 = copy.deepcopy(norm)
        dev = n2.devices[primary]
        for metric, v in changes.items():
            if metric == "status":
                dev["status"] = v
            else:
                dev["metrics"][metric] = v
        rep = Orchestrator(prooftrace=False, **config).run_normalized(n2, cid + "-WHATIF")
        return {"status": rep["status"], "hypothesis": rep.get("leading_hypothesis") or rep.get("root_cause_type"),
                "confidence": rep["confidence"]}

    # same agent line-up as the real run: agents that failed or were incompatible stay out
    lost = {a: "permanent" for a, h in orch.health.items() if h["status"] in ("failed", "incompatible")}
    config = {**orch.config, "inject_faults": {**orch.config["inject_faults"], **lost}}
    committed = conclusion["status"] in ("diagnosed", "tentative")
    base = rerun({})
    reproduced = base["hypothesis"] == conclusion["hypothesis"] and base["status"] == conclusion["status"]
    plans: list[tuple[str, str, str, Any]] = []
    sel = next(x for x in hyps if x["hypothesis"] == verdict_h)
    for e in sel["expected_signals"]:
        if e["state"] in ("present", "elevated"):
            plans.append(("remove_support", e["signal"], e["metric"], _normal_value(e["signal"])))
        elif e["state"] == "unknown":
            plans.append(("fill_missing_normal", e["signal"], e["metric"], _normal_value(e["signal"])))
            plans.append(("fill_missing_alarm", e["signal"], e["metric"], _alarm_value(e["signal"])))
    rivals = [x for x in hyps if x["hypothesis"] != verdict_h and x["score"] > 0][:2]
    for rv in rivals:
        for e in rv["expected_signals"]:
            if e["state"] != "present":
                plans.append((f"strengthen_rival:{rv['hypothesis']}", e["signal"], e["metric"], _alarm_value(e["signal"])))
    seen, results = set(), []
    for kind, sig, metric, val in plans:
        if (metric, val) in seen or len(results) >= MAX_WHATIFS:
            continue
        seen.add((metric, val))
        dev = norm.devices[primary]
        before = dev["status"] if metric == "status" else dev["metrics"].get(metric)
        res = rerun({metric: val})
        flips = res["hypothesis"] != conclusion["hypothesis"] or (
            (res["status"] in ("diagnosed", "tentative")) != committed)
        label = {"remove_support": "below warning onset", "fill_missing_normal": "measured and normal",
                 "fill_missing_alarm": "measured at alarm level"}.get(kind, "at alarm level")
        if metric == "status":
            label = "status not Critical" if val != "Critical" else "status Critical"
        results.append({"kind": kind, "signal": sig, "metric": metric, "device_id": primary,
                        "from": before, "to": val,
                        "change": f"{metric} on {primary}: {before if before is not None else 'not measured'} -> "
                                  f"{val} ({label})",
                        "result": res, "flips_conclusion": flips})
    return {"engine": "full agent pipeline re-run on modified normalised telemetry (local, no side effects)",
            "baseline_reproduced": reproduced, "baseline": base, "scenarios": results,
            "decisive": [r["change"] for r in results if r["flips_conclusion"]],
            "robust_to": [r["change"] for r in results if not r["flips_conclusion"]]}


def build_prooftrace(orch, norm, raw: Any, report: dict, what_if: bool = True) -> dict:
    log = orch.bus.log
    conclusion = {"status": report["status"], "hypothesis": report.get("leading_hypothesis"),
                  "root_cause_type": report.get("root_cause_type"),
                  "root_cause_devices": report.get("root_cause_devices", []),
                  "confidence": report["confidence"], "summary": report["suspected_root_cause"]}
    trace: dict[str, Any] = {
        "trace_version": TRACE_VERSION, "incident_id": report["incident_id"], "conclusion": conclusion,
        "integrity": {"message_count": len(log), "chain_sha256": chain_digest(log),
                      "messages": [{"i": i, "message_id": m["message_id"], "msg_type": m["msg_type"],
                                    "sender": m["sender"], "recipient": m["recipient"], "sha256": message_digest(m)}
                                   for i, m in enumerate(log)]},
        "data_quality": {"completeness": norm.completeness, "stale_devices": norm.stale_devices,
                         "quality_flags": {d: v.get("quality", []) for d, v in norm.devices.items() if v.get("quality")},
                         "records_rejected": norm.stats.get("records_rejected", 0)},
    }
    diag_msg, batches = _last(log, "diagnosis"), _batches(log)
    if getattr(orch, "last_audit", None):
        trace["trustguard"] = _trustguard(orch, norm, log, report)
    if report["status"] == "error" or not diag_msg:
        trace["note"] = "no diagnosis was produced; the trace only covers input handling and agent health"
        trace["checks"] = verify_prooftrace(trace, raw, log)
        return trace
    diag = diag_msg["payload"]
    trace["diagnosis_message_id"] = diag_msg["message_id"]
    ver_msg = _last(log, "verification_result")
    trace["verification_message_id"] = ver_msg["message_id"] if ver_msg else None
    if diag["status"] == "healthy":
        trace["healthy_check"] = [
            {"device_id": d, "max_signal": max(((s, graded(s, v["metrics"], v["status"]) or 0) for s in THRESHOLDS),
                                                key=lambda kv: kv[1])}
            for d, v in sorted(norm.devices.items())]
        trace["agents"] = _agents(orch, batches, log, norm, conclusion, None, diag)
        trace["checks"] = verify_prooftrace(trace, raw, log)
        return trace

    primary = diag["root_cause_devices"][0]
    verdict_h = diag.get("hypothesis")
    committed = report["status"] in ("diagnosed", "tentative")
    roots = list(dict.fromkeys(diag["root_cause_devices"]))
    trace["primary_device"] = primary
    trace["evidence"] = _evidence(roots, norm, batches)
    trace["hypotheses"] = _hypotheses(primary, norm, batches, diag, verdict_h, committed, trace["evidence"]) \
        if verdict_h else []
    for h in trace["hypotheses"]:   # votes TrustGuard kept out of correlation stay visible, with the reason
        h["excluded_by_trustguard"] = [
            {k: r[k] for k in ("record_id", "agent", "reported", "decision", "reason_codes", "message_id")}
            for r in (trace.get("trustguard") or {}).get("records", [])
            if r["kind"] == "vote" and r["device_id"] == primary and r["subject"] == h["hypothesis"]
            and r["decision"] != "trusted"]
    trace["agents"] = _agents(orch, batches, log, norm, conclusion, primary, diag)
    trace["conflicts"] = diag.get("conflicts", [])
    trace["challenge_round"] = diag.get("challenge")
    trace["topology_reasoning"] = {"root_candidates": diag["scope"]["root_candidates"],
                                   "downstream": diag["scope"].get("downstream", {}),
                                   "topology_available": diag["scope"].get("topology_available")}
    trace["missing_information"] = (report.get("abstention") or report.get("hedge") or {}).get(
        "required_measurements") or [
        {"device_id": primary, "metric": m["metric"], "signal": m["signal"], "decides": [x["hypothesis"]]}
        for x in trace["hypotheses"][:3] for m in x["missing"]]
    trace["decision_gates"] = report.get("decision_gates", [])
    if what_if and verdict_h:
        trace["sensitivity"] = _what_if(orch, norm, report["incident_id"], primary, verdict_h,
                                        trace["hypotheses"], conclusion)
    if what_if and report.get("hypothesis_ranking"):
        from .remediation import compare_fixes
        trace["remediation_check"] = compare_fixes(raw, report)
    trace["checks"] = verify_prooftrace(trace, raw, log)
    return trace


# ----------------------------------------------------------------------------------- verify
def _walk(rec: Any, path: list) -> Any:
    for k in path:
        if not isinstance(rec, dict) or k not in rec:
            raise KeyError(k)
        rec = rec[k]
    return rec


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))
    return a == b


def verify_prooftrace(trace: dict, raw: Any, log: list[dict]) -> dict:
    """Independently re-derive every claim in `trace` from the raw input and the message log.

    Does not trust anything computed during the run: it re-normalises the raw input, re-hashes the log,
    looks up every cited message and recomputes the selected hypothesis' fused score."""
    from .normalizer import _json_safe
    checks: list[dict] = []

    def check(name: str, target: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "target": target, "ok": bool(ok), "detail": detail})

    integ = trace.get("integrity", {})
    check("log length", "message log", integ.get("message_count") == len(log),
          f"trace says {integ.get('message_count')}, log has {len(log)}")
    bad = [m["i"] for m, actual in zip(integ.get("messages", []), log) if m["sha256"] != message_digest(actual)]
    check("message digests", "message log", not bad and len(integ.get("messages", [])) == len(log),
          f"{len(bad)} message(s) altered" + (f" (first: #{bad[0] + 1})" if bad else ""))
    check("chain digest", "message log", integ.get("chain_sha256") == chain_digest(log))
    by_id = {m["message_id"]: m for m in log}

    rep_msg = _last(log, "report")
    concl = trace.get("conclusion", {})
    if rep_msg:
        check("conclusion matches report message", rep_msg["message_id"],
              rep_msg["payload"]["status"] == concl.get("status")
              and _same(rep_msg["payload"]["confidence"], concl.get("confidence")))
    _verify_trustguard(trace, raw, log, by_id, check)
    if "diagnosis_message_id" not in trace:
        return _summary(checks)
    diag_msg = by_id.get(trace["diagnosis_message_id"])
    check("diagnosis message exists", trace["diagnosis_message_id"], diag_msg is not None
          and diag_msg["msg_type"] == "diagnosis")
    if not diag_msg or "evidence" not in trace:
        return _summary(checks)
    diag = diag_msg["payload"]
    check("leading hypothesis matches diagnosis message", trace["diagnosis_message_id"],
          diag.get("hypothesis") == concl.get("hypothesis"),
          f"message: {diag.get('hypothesis')}, trace: {concl.get('hypothesis')}")

    norm = normalize(raw)
    records = _records(raw)
    for e in trace["evidence"]:
        dev = norm.devices.get(e["device_id"])
        if dev is None:
            check("device in input", e["id"], False, f"{e['device_id']} not found in raw input")
            continue
        actual = dev["status"] if e["metric"] == "status" else dev["metrics"].get(e["metric"])
        check("canonical value re-derived from raw input", e["id"], _same(actual, e["value"]),
              f"{e['metric']}: trace {e['value']}, re-normalised {actual}")
        g = graded(e["signal"], dev["metrics"], dev["status"])
        check("signal strength recomputed", e["id"], g is not None and _same(g, e["strength"]),
              f"{e['signal']}: trace {e['strength']}, recomputed {g}")
        miss = 0
        for s in e["raw_samples"]:
            try:
                val = _json_safe(_walk(records[s["record_index"]], s["path"]))
                miss += not _same(val, s["raw"])
            except (KeyError, IndexError, TypeError):
                miss += 1
        check("raw samples found in input", e["id"], miss == 0 and bool(e["raw_samples"]),
              f"{len(e['raw_samples']) - miss}/{len(e['raw_samples'])} sample(s) located at their record/field")
        for o in e["observed_by"]:
            b = _batch_view(by_id.get(o["message_id"]), o["agent"])
            f = _finding({"payload": b}, e["device_id"]) if b else None
            ok = bool(f) and _strengths(f).get(e["signal"], 0) > 0
            check("agent finding cited", f"{e['id']}<-{o['agent']}", ok, f"message {o['message_id']}")

    primary = trace.get("primary_device")
    ev_p = [e for e in trace["evidence"] if e["device_id"] == primary]
    total = sum(e["strength"] for e in ev_p)
    ranked = {r["hypothesis"]: r for r in diag.get("ranking_all") or diag.get("ranking", [])}
    for h in trace.get("hypotheses", []):
        for v in h["votes"]:
            b = _batch_view(by_id.get(v["message_id"]), v["agent"])
            f = _finding({"payload": b}, primary) if b else None
            check("vote cited", f"{h['hypothesis']}<-{v['agent']}", bool(f) and _same(f["votes"].get(h["hypothesis"]),
                                                                                    v["vote"]))
        if h["verdict"] in ("selected", "leading (not committed)") and h["votes"]:
            base = noisy_or([v["vote"] * v["weight"] for v in h["votes"]])
            cov = sum(e["strength"] for e in ev_p if h["hypothesis"] in e["explains"]) / total if total else 0.0
            score = base * (COVERAGE_FLOOR + (1 - COVERAGE_FLOOR) * cov)
            if any(e["strength"] >= 1 and h["hypothesis"] in e["rules_out"] for e in ev_p):
                score *= 0.5
            if h.get("graded_support") is not None:
                score = round(score, 3) * (0.5 + 0.5 * h["graded_support"])
            msg_score = ranked.get(h["hypothesis"], {}).get("score")
            check("fused score recomputed from cited votes and evidence", h["hypothesis"],
                  msg_score is not None and abs(score - msg_score) <= 0.003,
                  f"recomputed {score:.3f}, diagnosis message {msg_score}")
            others = [r["score"] for k, r in ranked.items() if k != h["hypothesis"]]
            check("selected hypothesis outranks every alternative", h["hypothesis"],
                  all(msg_score >= o for o in others), f"best alternative {max(others, default=0):.3f}")
    return _summary(checks)


def _verify_trustguard(trace: dict, raw: Any, log: list[dict], by_id: dict, check) -> None:
    """Re-run the TrustGuard audit from the raw input and the logged agent messages and compare."""
    from .trustguard import audit_batches, decision_key, finding_digest
    audits = [m for m in log if m["msg_type"] == "audit_result"]
    tg = trace.get("trustguard")
    if not audits and not tg:
        return
    check("audit recorded in trace", "trustguard", bool(tg) and bool(audits),
          "audit_result in log but no trustguard section in trace" if audits else "trace cites an audit the log lacks")
    if not tg or not audits:
        return
    msg = by_id.get(tg.get("audit_message_id"))
    check("audit message exists", str(tg.get("audit_message_id")),
          bool(msg) and msg["msg_type"] == "audit_result" and msg["sender"] == "trustguard")
    if not msg:
        return
    logged = msg["payload"]["audit"]["records"]
    check("trace audit records match logged audit", msg["message_id"],
          [decision_key(r) for r in tg["records"]] == [decision_key(r) for r in logged],
          f"trace has {len(tg['records'])} record(s), audit message has {len(logged)}")
    req = next((m for m in reversed(log[:log.index(msg)]) if m["msg_type"] == "audit_request"), None)
    if not req:
        check("audit request exists", msg["message_id"], False)
        return
    sources, missing = [], []
    for b in req["payload"]["batches"]:
        src = by_id.get(b["message_id"])
        (sources.append({"message_id": src["message_id"], "payload": src["payload"]})
         if src and src["msg_type"] == "finding_batch" else missing.append(b["message_id"]))
    check("audited findings come from logged agent messages", req["message_id"], not missing,
          f"{len(missing)} cited finding_batch message(s) not in the log")
    altered = []
    for r in logged:
        src = by_id.get(r["message_id"]) if r["message_id"] else None
        f = next((x for x in (src or {}).get("payload", {}).get("findings", [])
                  if x["finding_id"] == r["finding_id"] and x["device_id"] == r["device_id"]), None)
        if r["finding_sha256"] and (f is None or finding_digest(f) != r["finding_sha256"]):
            altered.append(r["record_id"])
    check("findings unchanged since audit", msg["message_id"], not altered,
          f"{len(altered)} record(s) whose finding no longer matches its digest"
          + (f" (first: {altered[0]})" if altered else ""))
    cards = {m["payload"]["agent"]: m["payload"] for m in log if m["msg_type"] == "capability_response"}
    cards = {a: c for a, c in cards.items() if a in {s["payload"]["agent"] for s in sources}}
    redo = audit_batches(normalize(raw).devices, sources, cards, msg["correlation_id"])
    same = [decision_key(r) for r in redo["audit"]["records"]] == [decision_key(r) for r in logged]
    check("audit reconstructed from telemetry and agent messages", msg["message_id"], same,
          f"re-audit: {redo['audit']['summary']['flagged']} flagged / {redo['audit']['summary']['unverifiable']} "
          f"unverifiable; logged: {msg['payload']['audit']['summary']['flagged']} / "
          f"{msg['payload']['audit']['summary']['unverifiable']}")
    check("audited batches are the filtered originals", msg["message_id"],
          redo["audited_batches"] == msg["payload"]["audited_batches"])
    corr = next((m for m in log[log.index(msg):] if m["msg_type"] == "correlate_request"), None)
    if corr:
        check("correlation received only audited findings", corr["message_id"],
              corr["payload"]["batches"] == msg["payload"]["audited_batches"])


def _summary(checks: list[dict]) -> dict:
    failed = [c for c in checks if not c["ok"]]
    return {"passed": len(checks) - len(failed), "failed": len(failed), "total": len(checks),
            "verified": not failed, "failures": failed[:20], "checks": checks}


def render_prooftrace_markdown(t: dict) -> str:
    c = t["conclusion"]
    ch = t.get("checks", {})
    L = [f"# ProofTrace {t['incident_id']}", "",
         f"**Conclusion:** {c['summary']} (status `{c['status']}`, confidence {c['confidence']:.2f})  ",
         f"**Independent verification:** {ch.get('passed', 0)}/{ch.get('total', 0)} checks passed"
         + ("" if ch.get("verified") else " **(FAILED)**") + f"  ",
         f"**Log integrity:** {t['integrity']['message_count']} messages, chain sha256 "
         f"`{t['integrity']['chain_sha256'][:16]}...`", ""]
    if t.get("hypotheses"):
        L += ["## Competing hypotheses", "", "| Hypothesis | Verdict | Score | Votes | Support | Contradicting | Missing |",
              "|---|---|---|---|---|---|---|"]
        for h in t["hypotheses"]:
            L.append(f"| {h['hypothesis']} | {h['verdict']} | {h['score']:.2f} | "
                     + ", ".join(f"{v['agent'].replace('_agent', '')} {v['vote']:.2f}" for v in h["votes"])
                     + f" | {', '.join(h['supporting_evidence']) or '-'} | {len(h['contradicting'])} | "
                     f"{', '.join(m['metric'] for m in h['missing']) or '-'} |")
        L += ["", "### Why the alternatives were rejected", ""]
        for h in t["hypotheses"]:
            if h["rejection_reasons"] and h["verdict"] == "rejected":
                L.append(f"- **{h['hypothesis']}**: " + "; ".join(h["rejection_reasons"]))
        L.append("")
    if t.get("evidence"):
        L += ["## Evidence provenance", "", "| Id | Device | Signal | Value | Strength | From raw | Reported by |",
              "|---|---|---|---|---|---|---|"]
        for e in t["evidence"]:
            raws = ", ".join(f"#{s['record_index']}.{'.'.join(map(str, s['path']))}={s['raw']}" for s in e["raw_samples"][:3])
            L.append(f"| {e['id']} | {e['device_id']} | {e['signal']} | {e['value']} | {e['strength']:.2f} | "
                     f"{e['aggregation']}: {raws}{'...' if len(e['raw_samples']) > 3 else ''} | "
                     + ", ".join(o["agent"].replace("_agent", "") + f" ({o['message_id']})" for o in e["observed_by"]) + " |")
        L.append("")
    if t.get("agents"):
        L += ["## Agent contributions (leave-one-out re-correlation of logged findings)", "",
              "| Agent | Transport | Health | Top vote on root | Without it | Contribution |", "|---|---|---|---|---|---|"]
        for a in t["agents"]:
            top = (a.get("on_root_device") or {}).get("top_vote")
            loo = a.get("leave_one_out")
            L.append(f"| {a['agent']} | {a['transport']} | {a['health']} | "
                     f"{(top['hypothesis'] + ' ' + format(top['vote'], '.2f')) if top else '-'} | "
                     f"{(loo['status'] + ' / ' + str(loo['hypothesis']) + ' ' + format(loo['confidence'], '.2f')) if loo else '-'} | "
                     f"{loo['contribution'] if loo else '-'} |")
        L.append("")
    s = t.get("sensitivity")
    if s:
        L += ["## What would change the diagnosis", "",
              f"What-if engine reproduces the conclusion: {'yes' if s['baseline_reproduced'] else 'NO'}", ""]
        L += [f"- {'**FLIPS**' if r['flips_conclusion'] else 'holds'}: {r['change']} -> {r['result']['status']} "
              f"{r['result']['hypothesis']} ({r['result']['confidence']:.2f})" for r in s["scenarios"]]
        L.append("")
    if t.get("missing_information"):
        L += ["## Missing information", ""]
        L += [f"- {m['metric']} on {m['device_id']}: decides {', '.join(m['decides'])}" for m in t["missing_information"]]
        L.append("")
    if t.get("trustguard"):
        from .agents import render_trustguard_markdown
        L += render_trustguard_markdown(t["trustguard"])
        L += [f"Audit message `{t['trustguard']['audit_message_id']}`; {t['trustguard']['note']}", ""]
    if ch.get("failures"):
        L += ["## Failed checks", ""] + [f"- {c['check']} [{c['target']}]: {c['detail']}" for c in ch["failures"]] + [""]
    return "\n".join(L) + "\n"
