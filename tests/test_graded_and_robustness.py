import copy

from netcoop import Orchestrator
from netcoop.generator import generate
from netcoop.normalizer import normalize
from netcoop.signals import graded, signal_strength


def test_graded_strength_band():
    assert graded("high_cpu", {"cpu_utilization_pct": 60}, None) == 0.0      # below onset (70)
    assert graded("high_cpu", {"cpu_utilization_pct": 80}, None) == 0.5
    assert graded("high_cpu", {"cpu_utilization_pct": 95}, None) == 1.0
    assert graded("weak_signal", {"wifi_rssi_dbm": -71}, None) == 0.5        # "<=" signals are mirrored
    assert graded("high_cpu", {}, None) is None                              # missing is unknown, never zero
    assert signal_strength("high_cpu", {"cpu_utilization_pct": 89}, None)["state"] == "elevated"


def test_borderline_cpu_no_longer_ignored():
    """CPU at 89 % used to count as 'absent' (threshold 90 %), which produced confident errors."""
    doc = generate("hardware_failure")
    for r in doc["records"]:
        if r["device_id"] == "DEPT_SW_01":
            r["metrics"]["cpu_utilization_pct"] = 89.0
    rep = Orchestrator(prooftrace=False).run(doc)
    assert rep["root_cause_type"] == "hardware_failure"


def test_wifi_not_proposed_for_wired_switch():
    rep = Orchestrator(prooftrace=False).run(generate("device_overload"))
    ranked = {r["hypothesis"] for r in rep["hypothesis_ranking"]}
    assert "weak_wifi" not in ranked


def test_mild_overload_is_graded_not_ignored():
    rep = Orchestrator(prooftrace=False).run(generate("device_overload", severity=0.85))
    assert rep["leading_hypothesis"] == "device_overload"


def test_status_contradiction_flagged_and_penalised():
    doc = generate("link_congestion")
    for r in doc["records"]:
        if r["device_id"] == "HOSTEL_CORE_SW_01":
            r["status"] = "Healthy"
    res = normalize(doc)
    codes = [q["code"] for q in res.devices["HOSTEL_CORE_SW_01"]["quality"]]
    assert "status_contradiction" in codes
    rep = Orchestrator(prooftrace=False).run(doc)
    clean = Orchestrator(prooftrace=False).run(generate("link_congestion"))
    assert rep["confidence"] < clean["confidence"]
    assert rep["confidence_breakdown"]["consistency_penalty"] > 0


def test_unstable_metric_flagged():
    doc = generate("device_overload")
    sw = [r for r in doc["records"] if r["device_id"] == "HOSTEL_CORE_SW_01"]
    for i, r in enumerate(sw):
        r["metrics"]["cpu_utilization_pct"] = 96 if i % 2 else 30
    q = normalize(doc).devices["HOSTEL_CORE_SW_01"]["quality"]
    assert any(x["code"] == "unstable_metric" and x["metric"] == "cpu_utilization_pct" for x in q)


def test_inconsistent_throughput_flagged():
    doc = generate("normal")
    for r in doc["records"]:
        if r["device_id"] == "DEPT_SW_01":
            r["metrics"]["throughput_mbps"] = 5000
    q = normalize(doc).devices["DEPT_SW_01"]["quality"]
    assert any(x["code"] == "inconsistent_metrics" for x in q)


def test_conflicting_duplicate_samples_flagged():
    doc = generate("normal")
    dup = copy.deepcopy(doc["records"][0])
    dup["metrics"]["latency_ms"] = 500
    doc["records"].append(dup)
    q = normalize(doc).devices[dup["device_id"]]["quality"]
    assert any(x["code"] == "conflicting_duplicates" for x in q)


def test_fully_stale_device_treated_as_silent():
    doc = generate("normal")
    for r in doc["records"]:
        if r["device_id"] == "LECTURE_AP_01":
            r["timestamp"] = "2026-10-30T00:00:00Z"
    res = normalize(doc)
    assert "LECTURE_AP_01" not in res.devices and res.stale_devices == ["LECTURE_AP_01"]


def test_abstention_explains_itself():
    rep = Orchestrator(prooftrace=False).run(generate("latency_spike"))
    ab = rep["abstention"]
    assert rep["status"] == "insufficient_evidence"
    assert ab["why_not_committed"] and ab["summary"]
    failed = [g for g in rep["decision_gates"] if not g["passed"]]
    assert failed, "an abstention must name the gate(s) that failed"
    for m in ab["required_measurements"]:
        assert m["metric"] and m["decides"]


def test_tentative_reports_hedge():
    rep = Orchestrator(prooftrace=False).run(generate("conflicting_evidence"))
    assert rep["status"] == "tentative" and rep["hedge"]["why_not_committed"]
