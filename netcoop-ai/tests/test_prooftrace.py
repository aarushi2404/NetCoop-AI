import copy
import json

import pytest

from netcoop import Orchestrator
from netcoop.generator import SCENARIOS, generate
from netcoop.prooftrace import message_digest, render_prooftrace_markdown, verify_prooftrace
from netcoop.protocol import HYPOTHESES


def _run(name):
    orch = Orchestrator()
    doc = generate(name)
    rep = orch.run(doc)
    return orch, doc, rep, rep["prooftrace"]


@pytest.mark.parametrize("name", SCENARIOS)
def test_every_scenario_has_a_verified_trace(name):
    _, _, rep, t = _run(name)
    assert t["checks"]["verified"], t["checks"]["failures"]
    assert t["conclusion"]["status"] == rep["status"]
    json.dumps(t)  # serialisable


def test_all_hypotheses_listed_with_verdicts():
    _, _, rep, t = _run("hardware_failure")
    assert {h["hypothesis"] for h in t["hypotheses"]} == set(HYPOTHESES)
    sel = [h for h in t["hypotheses"] if h["verdict"] == "selected"]
    assert [h["hypothesis"] for h in sel] == ["hardware_failure"] == [rep["root_cause_type"]]
    for h in t["hypotheses"]:
        if h["verdict"] == "rejected":
            assert h["rejection_reasons"], h["hypothesis"]
    assert sel[0]["why_selected"]


def test_evidence_traces_back_to_raw_records():
    _, doc, _, t = _run("incompatible_schema_v2")      # nested {value, unit} input: provenance must survive
    e = next(x for x in t["evidence"] if x["metric"] == "latency_ms")
    s = e["raw_samples"][0]
    raw = doc["records"][s["record_index"]]
    assert raw[s["path"][0]][s["path"][1]] == s["raw"]   # e.g. stats.latency = {"value": 0.28, "unit": "s"}
    assert s["raw"]["unit"] == "s" and s["value"] == pytest.approx(s["raw"]["value"] * 1000)
    assert e["observed_by"] and e["observed_by"][0]["agent"] == "performance_agent"


def test_votes_cite_real_messages():
    orch, _, _, t = _run("link_congestion")
    ids = {m["message_id"]: m for m in orch.bus.log}
    for h in t["hypotheses"]:
        for v in h["votes"]:
            # the vote correlation used: TrustGuard's audited copy, linked to the agent's own finding_batch
            assert ids[v["message_id"]]["msg_type"] == "audit_result"
            src = ids[v["source_message_id"]]
            assert src["msg_type"] == "finding_batch" and src["sender"] == v["agent"]


def test_leave_one_out_identifies_decisive_agent():
    _, _, _, t = _run("hardware_failure")
    by = {a["agent"]: a for a in t["agents"]}
    assert by["infrastructure_agent"]["leave_one_out"]["contribution"] == "decisive"
    assert by["performance_agent"]["agrees_with_conclusion"] is False


def test_sensitivity_finds_decisive_measurements_and_reproduces_baseline():
    _, _, _, t = _run("hardware_failure")
    s = t["sensitivity"]
    assert s["baseline_reproduced"]
    assert any("cpu_utilization_pct" in c for c in s["decisive"])


def test_abstention_trace_lists_missing_information():
    _, _, rep, t = _run("insufficient_data")
    assert rep["status"] == "insufficient_evidence"
    assert rep["abstention"]["required_measurements"] and rep["abstention"]["why_not_committed"]
    assert t["missing_information"]


@pytest.mark.parametrize("tamper", ["raw", "vote", "drop", "trace"])
def test_tampering_is_detected(tamper):
    orch, doc, _, t = _run("hardware_failure")
    raw, log, trace = copy.deepcopy(doc), copy.deepcopy(orch.bus.log), copy.deepcopy(t)
    if tamper == "raw":
        e = next(x for x in trace["evidence"] if x["metric"] == "cpu_utilization_pct")
        s = e["raw_samples"][0]
        raw["records"][s["record_index"]]["metrics"]["cpu_utilization_pct"] = 10.0
    elif tamper == "vote":
        m = next(x for x in log if x["msg_type"] == "finding_batch" and x["sender"] == "infrastructure_agent")
        f = next(f for f in m["payload"]["findings"] if f["device_id"] == "DEPT_SW_01")
        f["votes"]["hardware_failure"] = 0.1
    elif tamper == "drop":
        log.pop(5)
    else:
        trace["evidence"][0]["value"] = 12345
    res = verify_prooftrace(trace, raw, log)
    assert not res["verified"] and res["failed"] >= 1


def test_digest_is_stable_across_serialisation():
    orch, *_ = _run("weak_wifi")
    for m in orch.bus.log:
        assert message_digest(json.loads(json.dumps(m))) == message_digest(m)


def test_markdown_renders():
    _, _, _, t = _run("conflicting_evidence")
    md = render_prooftrace_markdown(t)
    assert "Competing hypotheses" in md and "What would change the diagnosis" in md


def test_prooftrace_can_be_disabled():
    assert "prooftrace" not in Orchestrator(prooftrace=False).run(generate("normal"))
