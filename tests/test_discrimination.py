"""Overlapping and borderline measurements: does the system tell similar causes apart, and does it abstain
when the evidence is genuinely weak? No thresholds are tuned here; these document current behaviour."""
import pytest

from netcoop import Orchestrator


def incident(metrics: dict, status: str = "Warning", n: int = 5) -> dict:
    base = dict(latency_ms=12, jitter_ms=2, packet_loss_pct=0, link_utilization_pct=35, cpu_utilization_pct=22,
                memory_utilization_pct=40, queue_drops=0, interface_errors=0, link_flaps=0)
    topo = {"devices": [{"id": "CORE", "role": "router", "parent": None},
                        {"id": "SW1", "role": "switch", "parent": "CORE"}]}
    recs = []
    for i in range(n):
        for dev, m, st in (("CORE", base, "Healthy"), ("SW1", {**base, **metrics}, status)):
            recs.append({"device_id": dev, "timestamp": f"2026-01-01T00:0{i}:00Z", "metrics": dict(m), "status": st})
    return {"schema_version": "1.0", "topology": topo, "records": recs}


def diagnose(metrics, status="Warning"):
    return Orchestrator(prooftrace=False).run(incident(metrics, status))


@pytest.mark.parametrize("name,metrics,status,cause", [
    # saturated CPU AND a failing device (Critical, interface errors): hardware, not overload
    ("hw: cpu + critical + errors", dict(cpu_utilization_pct=99, interface_errors=300, latency_ms=400,
                                          packet_loss_pct=8), "Critical", "hardware_failure"),
    # saturated CPU and memory on a device that is not failing: overload, not hardware
    ("overload: cpu + memory", dict(cpu_utilization_pct=97, memory_utilization_pct=94, latency_ms=180,
                                     packet_loss_pct=1.5), "Warning", "device_overload"),
    # utilization + queue drops + latency: congestion
    ("congestion: util + drops", dict(link_utilization_pct=96, queue_drops=900, latency_ms=220,
                                       packet_loss_pct=2.5), "Warning", "link_congestion"),
    # interface errors + flaps, healthy CPU, not Critical: interface fault, not hardware
    ("interface: errors + flaps", dict(interface_errors=400, link_flaps=7, packet_loss_pct=6,
                                        latency_ms=90), "Warning", "interface_fault"),
])
def test_overlapping_causes_are_told_apart(name, metrics, status, cause):
    rep = diagnose(metrics, status)
    assert rep["status"] in ("diagnosed", "tentative"), (name, rep["suspected_root_cause"])
    assert rep["root_cause_type"] == cause, (name, rep["hypothesis_ranking"][:3])


def test_overload_is_not_called_hardware_without_device_failure():
    rep = diagnose(dict(cpu_utilization_pct=99, memory_utilization_pct=96, latency_ms=200), "Warning")
    assert rep["root_cause_type"] != "hardware_failure"


def test_critical_status_alone_is_not_a_hardware_diagnosis():
    rep = diagnose({}, "Critical")          # a status flag with every metric normal: no corroboration
    assert rep["status"] == "insufficient_evidence" and rep["root_cause_type"] is None


@pytest.mark.parametrize("metrics", [
    dict(cpu_utilization_pct=74, latency_ms=110),        # barely past the CPU warning onset (70 %)
    dict(cpu_utilization_pct=78),                         # elevated CPU, no symptom at all
])
def test_borderline_overload_abstains_rather_than_guessing(metrics):
    rep = diagnose(metrics)
    assert rep["status"] in ("insufficient_evidence", "tentative", "healthy")
    assert rep["status"] != "diagnosed"
