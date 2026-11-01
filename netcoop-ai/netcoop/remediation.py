"""Counterfactual remediation (dry run). NEVER touches a real network.

A fix is modelled by *what it can physically change*: replacing a cable restores interface errors and
flaps, it does not lower CPU. We apply that change to a copy of the normalised telemetry, re-derive each
device's health, re-run the complete multi-agent diagnosis and then check whether the improvement the
diagnosis predicted actually happened. If the diagnosis was wrong, the fix for it leaves the real
cause's symptoms in place and the outcome is reported as `unresolved`, not glossed over.

    diagnose -> propose fix -> apply fix to telemetry copy -> re-diagnose -> verify expected improvement

`compare_fixes` runs the same experiment for the competing hypotheses: if only the selected hypothesis'
fix clears the incident, that is independent, behavioural evidence for the diagnosis.
"""
from __future__ import annotations

from .agents import EXPECTED
from .normalizer import normalize
from .orchestrator import Orchestrator
from .signals import THRESHOLDS, derive_signals, derive_strengths

HEALTHY = {"latency_ms": 12, "jitter_ms": 2, "packet_loss_pct": 0.0, "link_utilization_pct": 40,
           "cpu_utilization_pct": 25, "memory_utilization_pct": 45, "queue_drops": 0, "interface_errors": 0,
           "link_flaps": 0, "wifi_rssi_dbm": -58, "retransmission_pct": 3, "dns_failure_pct": 0,
           "dhcp_failure_pct": 0}
PATH_METRICS = ("latency_ms", "packet_loss_pct", "jitter_ms")   # symptoms a downstream device inherits

# hypothesis -> (action, cause metrics the fix restores, symptom metrics that recover *only if* the fix
# removed a real abnormality, i.e. one of its cause metrics was substantially elevated beforehand)
FIX = {
    "link_congestion": ("Apply QoS policy / add uplink capacity", ["link_utilization_pct", "queue_drops"],
                        ["latency_ms", "jitter_ms", "packet_loss_pct"]),
    "interface_fault": ("Replace cable / SFP on the faulty port", ["interface_errors", "link_flaps"],
                        ["packet_loss_pct", "latency_ms", "jitter_ms"]),
    "weak_wifi": ("Re-site / re-channel the access point", ["wifi_rssi_dbm", "retransmission_pct"],
                  ["packet_loss_pct", "jitter_ms", "latency_ms"]),
    "device_overload": ("Offload control-plane load / upgrade device",
                        ["cpu_utilization_pct", "memory_utilization_pct"], ["latency_ms", "packet_loss_pct"]),
    "hardware_failure": ("Fail over to a redundant device and replace the faulty unit", list(HEALTHY), []),
    "dns_failure": ("Restore resolver / switch to secondary DNS", ["dns_failure_pct"], []),
    "dhcp_failure": ("Restore DHCP server / relay", ["dhcp_failure_pct"], []),
}
ACTED_ON = 0.5   # graded strength a cause metric must have had for its fix to relieve downstream symptoms
_METRIC_SIGNAL = {m: sig for sig, (m, *_r) in THRESHOLDS.items()}
# only these fixes replace the box, so only they can clear a device-reported Critical status
REPLACES_DEVICE = {"hardware_failure"}


def device_health(metrics: dict, status: str) -> dict:
    """Explainable health of one device: active alarms, elevated signals, health index = 1 - max strength."""
    st = derive_strengths(metrics, status)
    active = sorted(s for s, v in st.items() if v >= 1)
    elevated = {s: v for s, v in sorted(st.items()) if 0 < v < 1}
    return {"status": status, "active_signals": active, "elevated_signals": elevated,
            "health_index": round(1 - max(st.values(), default=0.0), 2)}


def _recomputed_status(metrics: dict, old: str, can_clear_critical: bool) -> str:
    present, _ = derive_signals(metrics, None)
    if old == "Critical" and not can_clear_critical:
        return "Critical"
    return "Healthy" if not present else old


def simulate_fix(raw: object, report: dict, hypothesis: str | None = None, efficacy: float = 1.0) -> dict:
    """Apply the fix for `hypothesis` (default: the diagnosed cause) with the given efficacy (1.0 = metrics
    fully restored to baseline, 0.5 = half-way) and verify the outcome by re-diagnosing."""
    hyp = hypothesis or report.get("root_cause_type")
    if hypothesis is None and report["status"] not in ("diagnosed", "tentative"):
        return {"simulated": False, "reason": "no actionable diagnosis to simulate"}
    if hyp not in FIX:
        return {"simulated": False, "reason": f"no fix model for '{hyp}'"}
    efficacy = max(0.0, min(1.0, efficacy))
    action, cause_metrics, symptom_metrics = FIX[hyp]
    norm = normalize(raw)
    roots = [d for d in report.get("root_cause_devices", []) if d in norm.devices]
    downstream = {d: p for d, p in (report.get("downstream_map") or {}).items()}
    if not downstream:
        downstream = {d: None for d in report.get("downstream_affected", [])}
    after_dev: dict[str, dict] = {}
    acted_on: dict[str, list[str]] = {}
    for did, dev in norm.devices.items():
        m, status = dict(dev["metrics"]), dev["status"]
        if did in roots:
            st = derive_strengths(dev["metrics"], dev["status"])
            acted = [k for k in cause_metrics if st.get(_METRIC_SIGNAL.get(k), 0) >= ACTED_ON]
            acted_on[did] = acted
            for k in cause_metrics + (symptom_metrics if acted else []):
                if k in m:
                    m[k] = round(m[k] + (HEALTHY[k] - m[k]) * efficacy, 3)
            status = _recomputed_status(m, status, hyp in REPLACES_DEVICE and efficacy >= 1.0)
        after_dev[did] = {"metrics": m, "status": status, "role": dev["role"], "parent": dev["parent"]}
    # downstream devices only recover if their upstream root is actually healthy after the fix
    roots_ok = all(after_dev[r]["status"] == "Healthy" for r in roots)
    for did in downstream:
        if did not in after_dev:
            continue
        d = after_dev[did]
        if roots_ok:
            for k in PATH_METRICS:
                if k in d["metrics"]:
                    d["metrics"][k] = HEALTHY[k]
        d["status"] = _recomputed_status(d["metrics"], d["status"], False)
    records = [{"device_id": did, "metrics": d["metrics"], "status": d["status"],
                "timestamp": "2026-10-31T13:00:00Z", "role": d["role"], "parent": d["parent"]}
               for did, d in after_dev.items()]
    after = Orchestrator(prooftrace=False).run({"incident_id": report["incident_id"] + "-AFTER-FIX",
                                                "topology": norm.topology, "schema_version": "1.0",
                                                "records": records})

    devices = []
    for did in roots + [d for d in downstream if d in norm.devices and d not in roots]:
        b, a = norm.devices[did], after_dev[did]
        changed = {k: {"before": b["metrics"][k], "after": a["metrics"][k]} for k in b["metrics"]
                   if a["metrics"].get(k) != b["metrics"][k]}
        devices.append({"device_id": did, "role": "root cause" if did in roots else "downstream",
                        "before": device_health(b["metrics"], b["status"]),
                        "after": device_health(a["metrics"], a["status"]), "metrics_changed": changed})
    # the improvement the diagnosis predicts: its expected signals disappear on the root devices
    expectations = []
    for did in roots:
        for sig in EXPECTED.get(hyp, []):
            if sig == "device_critical":
                before, aft = norm.devices[did]["status"], after_dev[did]["status"]
                expectations.append({"device_id": did, "signal": sig, "metric": "status", "before": before,
                                     "after": aft, "achieved": aft != "Critical"})
                continue
            metric, op, thr, *_ = THRESHOLDS[sig]
            before = norm.devices[did]["metrics"].get(metric)
            if before is None:
                continue
            aft = after_dev[did]["metrics"].get(metric)
            ok = aft < thr if op == ">=" else aft > thr
            expectations.append({"device_id": did, "signal": sig, "metric": metric, "before": before,
                                 "after": aft, "expected": f"{'<' if op == '>=' else '>'} {thr:g}", "achieved": ok})
    residual = sorted({s for d in devices if d["role"] == "root cause" for s in d["after"]["active_signals"]})
    expected_ok = all(e["achieved"] for e in expectations)
    if after["status"] == "healthy":
        outcome = "resolved"
    elif expected_ok and not residual:
        outcome = "partially_resolved"   # the root device is fine, but another fault remains elsewhere
    else:
        outcome = "unresolved"
    explanation = {
        "resolved": "the expected improvement occurred and the re-diagnosis finds no fault",
        "partially_resolved": "the targeted fault cleared, but the re-diagnosis still finds a fault elsewhere: "
                              + after["suspected_root_cause"],
        "unresolved": ("the issue remains: "
                       + ("the fix had nothing to act on (its target metrics were not elevated); "
                          if not any(acted_on.values()) and hyp not in REPLACES_DEVICE else "")
                       + (f"root device still shows {', '.join(residual)}" if residual
                                                 else "expected improvement did not occur")
                       + f"; re-diagnosis: {after['suspected_root_cause']}"),
    }[outcome]
    return {"simulated": True, "hypothesis": hyp, "action": action, "efficacy": efficacy,
            "devices_modified": sorted(set(roots) | set(downstream)),
            "before": {"status": report["status"], "cause": report["suspected_root_cause"],
                       "confidence": report["confidence"]},
            "after": {"status": after["status"], "cause": after["suspected_root_cause"],
                      "confidence": after["confidence"], "root_cause_type": after.get("root_cause_type"),
                      "root_cause_devices": after.get("root_cause_devices", [])},
            "devices": devices, "expected_improvements": expectations, "residual_signals": residual,
            "fix_acted_on": acted_on,
            "outcome": outcome, "explanation": explanation, "incident_cleared": outcome == "resolved",
            "note": "Dry run on a copy of the telemetry; no real device was modified."}


def compare_fixes(raw: object, report: dict, k: int = 3) -> dict:
    """Counterfactual check: apply the fix of each of the top-k hypotheses and see which one clears it."""
    ranking = [r["hypothesis"] for r in report.get("hypothesis_ranking", [])][:k]
    if not ranking:
        return {"compared": False, "reason": "no competing hypotheses to compare"}
    results = {h: simulate_fix(raw, report, hypothesis=h) for h in ranking}
    resolving = [h for h, r in results.items() if r.get("outcome") == "resolved"]
    selected = report.get("root_cause_type") or report.get("leading_hypothesis")
    if resolving == [selected]:
        verdict = "only the selected hypothesis' fix resolves the incident: behaviour corroborates the diagnosis"
    elif selected in resolving:
        verdict = (f"fixes for {', '.join(resolving)} would all resolve it: the remediation test cannot tell these "
                   "hypotheses apart")
    elif resolving:
        verdict = f"the selected hypothesis' fix does NOT resolve it, but {', '.join(resolving)} would: diagnosis doubtful"
    else:
        verdict = "no single fix resolves the incident (possible multi-fault or unmodelled cause)"
    return {"compared": True, "selected": selected, "resolving": resolving, "verdict": verdict,
            "results": {h: {"action": r["action"], "outcome": r["outcome"], "after_status": r["after"]["status"],
                            "residual_signals": r["residual_signals"], "explanation": r["explanation"]}
                        for h, r in results.items()}}
