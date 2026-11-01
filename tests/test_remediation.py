import pytest

from netcoop import Orchestrator
from netcoop.generator import generate
from netcoop.remediation import simulate_fix


@pytest.mark.parametrize("scenario", ["link_congestion", "weak_wifi", "interface_fault", "dns_failure",
                                      "dhcp_failure", "hardware_failure", "device_overload", "multi_fault"])
def test_simulated_fix_clears_incident(scenario):
    doc = generate(scenario)
    rep = Orchestrator().run(doc)
    sim = simulate_fix(doc, rep)
    assert sim["simulated"]
    if scenario == "multi_fault":   # only the primary fault is fixed: the secondary one must remain
        assert sim["after"]["status"] != "healthy"
    else:
        assert sim["incident_cleared"], sim


def test_no_simulation_without_diagnosis():
    doc = generate("latency_spike")
    assert simulate_fix(doc, Orchestrator().run(doc))["simulated"] is False
