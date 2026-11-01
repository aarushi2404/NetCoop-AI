import json

import pytest

from netcoop import Orchestrator
from netcoop.organizer import NOTEBOOK, build_incidents, evaluate, load_generator, score

pytestmark = pytest.mark.skipif(not NOTEBOOK.exists(), reason="organizer notebook not present")


def test_notebook_generator_is_loaded_not_reimplemented():
    ns, info = load_generator()
    assert info["function"] == "generate_telemetry"
    assert set(info["fault_types"]) == {"normal", "latency_spike", "hardware_failure"}   # discovered from the code
    assert any("print" in s for s in info["skipped_statements"])                         # example cell not executed
    rec = ns["generate_telemetry"]("hardware_failure")
    assert rec["status"] == "Critical" and rec["metrics"]["cpu_utilization_pct"] == 99.9


def test_incidents_are_reproducible_and_keep_generator_ids():
    a, _ = build_incidents(6, seed=3)
    b, _ = build_incidents(6, seed=3)
    assert json.dumps(a) == json.dumps(b)
    assert all("generator_device_id" in r for inc in a for r in inc["records"])
    assert {inc["label"] for inc in a} == {"normal", "latency_spike", "hardware_failure"}


def test_organizer_records_need_no_field_mapping():
    incs, _ = build_incidents(3, seed=1)
    rep = Orchestrator(prooftrace=False).run(incs[0])
    assert rep["data_quality"]["records_rejected"] == 0
    assert not [i for i in rep["data_quality"]["issues"] if "unknown field" in i["message"]]


def test_scoring_rules():
    inc = {"incident_id": "x", "label": "latency_spike", "faulty_device": "SW_CAMPUS_1"}
    base = {"confidence": 0.3, "root_cause_devices": ["SW_CAMPUS_1"]}
    assert score(inc, {**base, "status": "insufficient_evidence"})["outcome"] == "correct"
    assert score(inc, {**base, "status": "tentative", "root_cause_type": "link_congestion"})["outcome"] == "hedged"
    assert score(inc, {**base, "status": "diagnosed", "root_cause_type": "link_congestion"})["outcome"] == "false_diagnosis"
    assert score(inc, {**base, "status": "healthy", "root_cause_devices": []})["outcome"] == "missed"


def test_small_evaluation_runs_and_reports_separately():
    r = evaluate(n=9, seed=11, stress=True)
    for k in ("clean", "stressed"):
        assert r[k]["n"] == 9 and 0 <= r[k]["accuracy"] <= 1
        assert r[k]["prooftrace_verified"] == "9/9"
    assert r["source"]["notebook"].endswith(".ipynb")
