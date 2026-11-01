import json
from pathlib import Path

import pytest

from netcoop import Orchestrator
from netcoop.generator import generate

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_scenario(name):
    exp = EXPECTED[name]
    rep = Orchestrator().run(generate(name))
    assert rep["status"] == exp["status"], rep["suspected_root_cause"]
    if "devices" in exp:
        assert sorted(rep["root_cause_devices"]) == sorted(exp["devices"])
        assert exp["cause"].lower() in rep["suspected_root_cause"].lower()
    if exp["status"] in ("diagnosed", "tentative"):
        assert rep["supporting_evidence"] and rep["recommended_actions"] and rep["limitations"]
        assert len(rep["evidence_sources"]) >= 1


def test_report_has_required_fields():
    rep = Orchestrator().run(generate("link_congestion"))
    for k in ("incident_id", "status", "suspected_root_cause", "confidence", "affected_devices",
              "supporting_evidence", "alternative_causes", "recommended_actions",
              "evidence_sources", "limitations"):
        assert k in rep
    assert 0 <= rep["confidence"] <= 1
    json.dumps(rep)  # must be serialisable


def test_evidence_from_multiple_agents():
    rep = Orchestrator().run(generate("link_congestion"))
    assert {"performance_agent", "infrastructure_agent"} <= set(rep["evidence_sources"])


def test_downstream_devices_not_blamed():
    rep = Orchestrator().run(generate("link_congestion"))
    assert rep["root_cause_devices"] == ["HOSTEL_CORE_SW_01"]
    assert set(rep["downstream_affected"]) == {"HOSTEL_AP_01", "HOSTEL_AP_02", "HOSTEL_AP_03"}


def test_conflict_is_reported_and_resolved():
    rep = Orchestrator().run(generate("hardware_failure"))
    assert rep["conflicts_resolved"], "performance agent should disagree with the fused result"
    assert rep["conflicts_resolved"][0]["resolved_to"] == "hardware_failure"


def test_no_exact_claim_without_evidence():
    for name in ("latency_spike", "insufficient_data"):
        rep = Orchestrator().run(generate(name))
        assert rep["status"] == "insufficient_evidence"
        assert rep["confidence"] < 0.45
        assert "insufficient" in rep["suspected_root_cause"].lower()


def test_interop_inputs_give_same_diagnosis_as_native():
    native = Orchestrator().run(generate("link_congestion"))
    for name in ("incompatible_schema_v0", "incompatible_schema_v2"):
        rep = Orchestrator().run(generate(name))
        assert rep["root_cause_devices"] == native["root_cause_devices"]
        assert abs(rep["confidence"] - native["confidence"]) < 0.1


def test_malformed_input_reports_issues():
    rep = Orchestrator().run(generate("malformed_input"))
    dq = rep["data_quality"]
    assert dq["records_rejected"] >= 2
    levels = [i["level"] for i in dq["issues"]]
    assert "error" in levels and "warning" in levels


def test_missing_file_and_bad_json(tmp_path):
    rep = Orchestrator().run_file(tmp_path / "nope.json")
    assert rep["status"] == "error" and "not found" in rep["suspected_root_cause"]
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    rep = Orchestrator().run_file(bad)
    assert rep["status"] == "error" and "not valid JSON" in rep["suspected_root_cause"]


def test_unrecognised_structure():
    for raw in ("hello", 42, {"foo": "bar"}, []):
        assert Orchestrator().run(raw)["status"] == "error"
