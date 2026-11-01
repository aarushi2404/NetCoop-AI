"""TrustGuard: evidence-grounded audit of specialist findings (netcoop/trustguard.py)."""
import copy
import json

import pytest

from netcoop import Orchestrator
from netcoop.generator import SCENARIOS, generate, simulation_faults
from netcoop.prooftrace import verify_prooftrace
from netcoop.remediation import simulate_fix
from netcoop.trustguard import UNVERIFIABLE_CAP, audit_batches, decision_key, recompute_strength

ADV = "adversarial_agent"


def adversarial_run(**kw):
    raw = generate(ADV)
    orch = Orchestrator(inject_faults=simulation_faults(raw), **kw)
    return orch, raw, orch.run(raw)


def batch_of(orch, agent):
    return next(m for m in orch.bus.log if m["msg_type"] == "finding_batch" and m["sender"] == agent)


def audited(orch, agent):
    m = next(m for m in orch.bus.log if m["msg_type"] == "audit_result")
    return next(b for b in m["payload"]["audited_batches"] if b["agent"] == agent)


def finding(batch, device):
    return next(f for f in batch["findings"] if f["device_id"] == device)


# ------------------------------------------------------------------ independent recomputation
@pytest.mark.parametrize("signal,metrics,status,expected", [
    ("high_cpu", {"cpu_utilization_pct": 80}, "Healthy", 0.5),          # (80-70)/(90-70)
    ("high_cpu", {"cpu_utilization_pct": 95}, "Healthy", 1.0),
    ("high_cpu", {"cpu_utilization_pct": 40}, "Healthy", 0.0),
    ("weak_signal", {"wifi_rssi_dbm": -71}, "Healthy", 0.5),             # lower is worse: (-67+71)/(-67+75)
    ("queue_drops", {"queue_drops": 60}, "Healthy", 0.5),                # (60-20)/(100-20)
    ("device_critical", {}, "Critical", 1.0),
    ("device_critical", {}, "Unknown", None),
    ("high_cpu", {}, "Healthy", None),                                   # missing is unknown, never zero
])
def test_strength_recomputed_independently(signal, metrics, status, expected):
    assert recompute_strength(signal, metrics, status) == expected


# ------------------------------------------------------------------ 1-2 honest findings pass
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_honest_findings_are_all_trusted(scenario):
    rep = Orchestrator(prooftrace=False).run(generate(scenario))
    tg = rep.get("trustguard")
    if tg is None:      # input rejected before any agent ran
        assert rep["status"] == "error"
        return
    assert tg["status"] == "audited" and tg["summary"]["flagged"] == 0 and tg["summary"]["unverifiable"] == 0
    assert tg["before_after"]["computed"] is False and not tg["before_after"]["diagnosis_changed"]


def test_disagreement_is_not_flagged():
    rep = Orchestrator(prooftrace=False).run(generate("conflicting_evidence"))
    assert rep["conflicts_resolved"]                     # agents really disagree here
    assert rep["trustguard"]["summary"]["flagged"] == 0


def test_supported_vote_is_accepted():
    orch, _, rep = adversarial_run(prooftrace=False)
    rec = next(r for r in orch.last_audit["records"] if r["agent"] == "infrastructure_agent"
               and r["kind"] == "vote" and r["subject"] == "hardware_failure")
    assert rec["decision"] == "trusted" and rec["reason_codes"] == ["CONSISTENT"]


# ------------------------------------------------------------------ 3 unsupported votes are flagged
def test_adversarial_vote_is_flagged_with_reasons():
    orch, _, rep = adversarial_run(prooftrace=False)
    flagged = rep["trustguard"]["flagged"]
    assert len(flagged) == 1
    f = flagged[0]
    assert (f["agent"], f["device_id"], f["subject"], f["reported"]) == \
        ("performance_agent", "DEPT_SW_01", "link_congestion", 0.99)
    assert "UNSUPPORTED_CERTAINTY" in f["reason_codes"] and "SELF_CONTRADICTION" in f["reason_codes"]
    assert "high_utilization=0.00" in f["explanation"]
    assert any("TrustGuard excluded" in l for l in rep["limitations"])


# ------------------------------------------------------------------ 4 missing telemetry -> unverifiable
def _devices(**metrics):
    return {"SW1": {"metrics": metrics, "status": "Warning", "role": "switch", "parent": None}}


def _batch(agent, domain, votes, strengths=None, present=(), device="SW1", evidence=()):
    return {"agent": agent, "domain": domain, "findings": [{
        "finding_id": f"{agent}:{device}", "agent": agent, "domain": domain, "device_id": device, "votes": votes,
        "signals_present": list(present), "signals_unknown": [], "signal_strength": strengths or {},
        "evidence": list(evidence), "notes": []}]}


def test_missing_telemetry_is_unverifiable_not_malicious():
    # a confident congestion vote, but utilization and queue drops were never measured
    res = audit_batches(_devices(latency_ms=400),
                        [_batch("performance_agent", "performance", {"link_congestion": 0.9})])
    vote = next(r for r in res["audit"]["records"] if r["kind"] == "vote")
    assert vote["decision"] == "unverifiable" and vote["reason_codes"] == ["VOTE_UNVERIFIABLE"]
    out = finding(res["audited_batches"][0], "SW1")
    assert out["votes"]["link_congestion"] == UNVERIFIABLE_CAP          # handled conservatively, not removed
    assert out["trustguard"]["capped_votes"] == {"link_congestion": 0.9}


def test_signal_on_missing_metric_is_unverifiable():
    res = audit_batches(_devices(latency_ms=400),
                        [_batch("infrastructure_agent", "infrastructure", {}, {"high_cpu": 1.0}, ["high_cpu"])])
    rec = next(r for r in res["audit"]["records"] if r["kind"] == "signal")
    assert rec["decision"] == "unverifiable" and "MISSING_TELEMETRY" in rec["reason_codes"]
    assert "high_cpu" not in finding(res["audited_batches"][0], "SW1")["signal_strength"]


# ------------------------------------------------------------------ 5 domain authority
def test_claims_outside_declared_authority_are_flagged():
    card = {"agent": "performance_agent", "signals": ["high_latency", "high_jitter", "packet_loss", "high_utilization"],
            "hypotheses": ["link_congestion", "interface_fault", "weak_wifi", "device_overload"]}
    res = audit_batches(_devices(cpu_utilization_pct=99, latency_ms=300),
                        [_batch("performance_agent", "performance", {"hardware_failure": 0.6},
                                {"high_cpu": 1.0, "high_latency": 1.0}, ["high_cpu", "high_latency"])],
                        {"performance_agent": card})
    recs = {(r["kind"], r["subject"]): r for r in res["audit"]["records"]}
    assert recs[("vote", "hardware_failure")]["decision"] == "flagged"
    assert "OUT_OF_DOMAIN_CLAIM" in recs[("vote", "hardware_failure")]["reason_codes"]
    assert "FOREIGN_DOMAIN_SIGNAL" in recs[("signal", "high_cpu")]["reason_codes"]
    assert recs[("signal", "high_latency")]["decision"] == "trusted"   # the in-domain signal is kept
    f = finding(res["audited_batches"][0], "SW1")
    assert f["votes"] == {} and f["signal_strength"] == {"high_latency": 1.0}


def test_misreported_strength_and_evidence_are_flagged():
    ev = [{"metric": "cpu_utilization_pct", "value": 99.0, "device_id": "SW1", "unit": "%", "threshold": ">= 90 %",
           "strength": 1.0, "interpretation": "x"}]
    res = audit_batches(_devices(cpu_utilization_pct=30, memory_utilization_pct=40, queue_drops=0),
                        [_batch("infrastructure_agent", "infrastructure", {"device_overload": 0.6},
                                {"high_cpu": 1.0}, ["high_cpu"], evidence=ev)])
    codes = {r["kind"]: r["reason_codes"] for r in res["audit"]["records"]}
    assert {"STRENGTH_MISMATCH", "SIGNAL_NOT_PRESENT"} <= set(codes["signal"])
    assert "EVIDENCE_VALUE_MISMATCH" in codes["evidence"]
    assert "VOTE_EVIDENCE_MISMATCH" in codes["vote"]
    f = finding(res["audited_batches"][0], "SW1")
    assert not f["votes"] and not f["signal_strength"] and not f["evidence"]


def test_binary_strength_from_foreign_agent_is_accepted():
    # WirelessOps reports 0/1 at the alarm threshold instead of a graded value: consistent, not a mismatch
    res = audit_batches({"AP": {"metrics": {"wifi_rssi_dbm": -80, "retransmission_pct": 10}, "status": "Warning"}},
                        [_batch("connectivity_agent", "connectivity", {"weak_wifi": 0.55},
                                {"weak_signal": 1.0, "retransmissions": 0.0}, ["weak_signal"], device="AP")])
    assert all(r["decision"] == "trusted" for r in res["audit"]["records"])


def test_scope_naming_a_healthy_device_is_rejected():
    devs = {**_devices(cpu_utilization_pct=20), "SW2": {"metrics": {"latency_ms": 500}, "status": "Warning"}}
    b = _batch("connectivity_agent", "connectivity", {})
    b["scope"] = {"degraded": ["SW1"], "root_candidates": ["SW1"], "downstream": {}}
    res = audit_batches(devs, [b])
    rec = next(r for r in res["audit"]["records"] if r["kind"] == "scope")
    assert rec["decision"] == "flagged" and "SCOPE_MISMATCH" in rec["reason_codes"]
    assert "scope" not in res["audited_batches"][0] and "scope_rejected" in res["audited_batches"][0]


# ------------------------------------------------------------------ 6-7 claim-by-claim filtering
def test_findings_are_filtered_individually_and_valid_ones_preserved():
    orch, _, _ = adversarial_run(prooftrace=False)
    orig, aud = batch_of(orch, "performance_agent")["payload"], audited(orch, "performance_agent")
    root_o, root_a = finding(orig, "DEPT_SW_01"), finding(aud, "DEPT_SW_01")
    assert "link_congestion" not in root_a["votes"]
    assert {h: v for h, v in root_o["votes"].items() if h != "link_congestion"} == root_a["votes"]
    assert root_a["signal_strength"] == root_o["signal_strength"]      # truthful evidence kept
    assert root_a["evidence"] == root_o["evidence"]
    for f in orig["findings"]:                                          # every other finding passes unchanged
        if f["device_id"] != "DEPT_SW_01":
            a = finding(aud, f["device_id"])
            assert {k: v for k, v in a.items() if k != "trustguard"} == f


# ------------------------------------------------------------------ 8 reproducible
def test_adversarial_scenario_is_reproducible():
    o1, _, r1 = adversarial_run(prooftrace=False)
    o2, _, r2 = adversarial_run(prooftrace=False)
    def keys(o):   # everything except the per-run random message ids
        return [k[:5] + k[6:] for k in map(decision_key, o.last_audit["records"])]
    assert keys(o1) == keys(o2)
    strip = lambda r: {k: r[k] for k in ("status", "root_cause_type", "root_cause_devices", "confidence")}  # noqa: E731
    assert strip(r1) == strip(r2)
    assert r1["trustguard"]["summary"] == r2["trustguard"]["summary"]
    assert simulation_faults(generate(ADV)) == {"performance_agent": "adversarial"}


# ------------------------------------------------------------------ 9 diagnosis recomputed from audited findings
def test_correlation_only_sees_audited_findings():
    orch, _, rep = adversarial_run(prooftrace=False)
    corr = next(m for m in orch.bus.log if m["msg_type"] == "correlate_request")
    perf = next(b for b in corr["payload"]["batches"] if b["agent"] == "performance_agent")
    assert "link_congestion" not in finding(perf, "DEPT_SW_01")["votes"]
    ba = rep["trustguard"]["before_after"]
    assert ba["computed"] and ba["before"]["confidence"] < ba["after"]["confidence"]
    honest = Orchestrator(prooftrace=False).run(generate(ADV))
    assert (rep["status"], rep["root_cause_type"], rep["confidence"]) == \
        (honest["status"], honest["root_cause_type"], honest["confidence"])


@pytest.mark.parametrize("scenario,agent", [("link_congestion", "connectivity_agent"),
                                            ("weak_wifi", "infrastructure_agent"),
                                            ("dns_failure", "performance_agent"),
                                            ("interface_fault", "connectivity_agent")])
def test_audit_restores_the_honest_diagnosis(scenario, agent):
    rep = Orchestrator(inject_faults={agent: "adversarial"}, prooftrace=False).run(generate(scenario))
    honest = Orchestrator(prooftrace=False).run(generate(scenario))
    assert rep["trustguard"]["summary"]["flagged"] + rep["trustguard"]["summary"]["unverifiable"] >= 1
    assert (rep["status"], rep.get("root_cause_type"), rep.get("root_cause_devices")) == \
        (honest["status"], honest.get("root_cause_type"), honest.get("root_cause_devices"))


def test_without_trustguard_a_lie_changes_the_diagnosis():
    from netcoop.benchmark import make_cases
    case = make_cases(11, 1)[10]          # benchmark incident #10: a mild device overload
    assert case["truth"] == "device_overload"
    rep = Orchestrator(inject_faults={"performance_agent": "adversarial"}, prooftrace=False).run(case["doc"])
    ba = rep["trustguard"]["before_after"]
    assert ba["diagnosis_changed"]
    assert (ba["before"]["status"], ba["before"]["root_cause_type"]) == ("diagnosed", "link_congestion")  # misled
    honest = Orchestrator(prooftrace=False).run(case["doc"])
    assert (ba["after"]["status"], ba["after"]["root_cause_type"]) == (honest["status"], honest.get("root_cause_type"))


# ------------------------------------------------------------------ 10 abstention preserved
@pytest.mark.parametrize("faults", [{}, {"performance_agent": "adversarial"}, {"infrastructure_agent": "adversarial"}])
def test_insufficient_evidence_still_abstains(faults):
    rep = Orchestrator(inject_faults=faults).run(generate("insufficient_data"))
    assert rep["status"] == "insufficient_evidence" and rep["root_cause_type"] is None


def test_trustguard_failure_degrades_gracefully():
    rep = Orchestrator(inject_faults={"trustguard": "permanent"}).run(generate("hardware_failure"))
    assert rep["trustguard"]["status"] == "unavailable"
    assert rep["root_cause_type"] == "hardware_failure"
    assert any("not audited" in l for l in rep["limitations"])
    assert rep["prooftrace"]["checks"]["verified"]


# ------------------------------------------------------------------ 11-12 ProofTrace
def test_audit_events_are_in_prooftrace():
    orch, _, rep = adversarial_run()
    t = rep["prooftrace"]
    tg = t["trustguard"]
    assert len(tg["records"]) == tg["summary"]["checked"] == rep["trustguard"]["summary"]["checked"]
    r = next(x for x in tg["records"] if x["decision"] == "flagged")
    for k in ("message_id", "agent", "device_id", "finding_id", "original_finding", "decision", "reason_codes",
              "telemetry_refs", "timestamp", "audit_version", "finding_sha256", "effect"):
        assert r.get(k) not in (None, ""), k
    assert r["original_finding"]["votes"]["link_congestion"] == 0.99
    assert any(t_["record_indexes"] for t_ in r["telemetry_refs"])             # back to raw input records
    assert "did not influence" in r["effect"]
    lc = next(h for h in t["hypotheses"] if h["hypothesis"] == "link_congestion")
    assert lc["excluded_by_trustguard"] and all(v["agent"] != "performance_agent" for v in lc["votes"])
    names = {c["check"] for c in t["checks"]["checks"]}
    assert {"audit reconstructed from telemetry and agent messages", "findings unchanged since audit",
            "correlation received only audited findings"} <= names
    assert t["checks"]["verified"]


def _tampered(kind):
    orch, raw, rep = adversarial_run()
    log, trace = copy.deepcopy(orch.bus.log), copy.deepcopy(rep["prooftrace"])
    audit = next(m for m in log if m["msg_type"] == "audit_result")
    if kind == "flip_decision":
        r = next(x for x in audit["payload"]["audit"]["records"] if x["decision"] == "flagged")
        r["decision"] = "trusted"
    elif kind == "remove_record":
        audit["payload"]["audit"]["records"].pop()
    elif kind == "alter_finding":
        f = finding(batch_of(orch, "performance_agent")["payload"], "DEPT_SW_01")
        m = next(x for x in log if x["message_id"] == batch_of(orch, "performance_agent")["message_id"])
        finding(m["payload"], "DEPT_SW_01")["votes"]["link_congestion"] = 0.2
        assert f["votes"]["link_congestion"] == 0.99
    elif kind == "trace_record":
        trace["trustguard"]["records"][0]["decision"] = "flagged"
    elif kind == "drop_audit":
        log.remove(audit)
    return verify_prooftrace(trace, raw, log)


@pytest.mark.parametrize("kind,expected_failure", [
    ("flip_decision", "audit reconstructed from telemetry and agent messages"),
    ("remove_record", "trace audit records match logged audit"),
    ("alter_finding", "findings unchanged since audit"),
    ("trace_record", "trace audit records match logged audit"),
    ("drop_audit", "audit recorded in trace"),
])
def test_tampered_audit_fails_verification(kind, expected_failure):
    res = _tampered(kind)
    assert not res["verified"]
    assert expected_failure in {c["check"] for c in res["failures"]}, res["failures"]


# ------------------------------------------------------------------ 13-14 nothing else broke
def test_remote_agent_findings_pass_the_audit():
    from netcoop.remote import start_in_thread
    srv, url = start_in_thread()
    try:
        rep = Orchestrator(remote_connectivity=url).run(generate("weak_wifi"))
    finally:
        srv.shutdown()
    assert rep["root_cause_type"] == "weak_wifi"
    assert rep["trustguard"]["summary"]["flagged"] == 0 and rep["trustguard"]["summary"]["unverifiable"] == 0
    assert rep["prooftrace"]["checks"]["verified"]


def test_remediation_still_works_on_audited_diagnosis():
    _, raw, rep = adversarial_run(prooftrace=False)
    assert simulate_fix(raw, rep)["outcome"] == "resolved"
    assert simulate_fix(raw, rep, hypothesis="link_congestion")["outcome"] == "unresolved"


def test_report_json_is_serialisable():
    _, _, rep = adversarial_run()
    json.dumps(rep)
