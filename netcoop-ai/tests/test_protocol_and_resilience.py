import pytest
from pydantic import ValidationError

from netcoop import Orchestrator
from netcoop.bus import MessageBus
from netcoop.generator import generate
from netcoop.protocol import Envelope, Finding, make_envelope


def test_envelope_rejects_unknown_protocol_version():
    with pytest.raises(ValidationError):
        Envelope(schema_version="9.9", message_id="x", correlation_id="y", sender="a",
                 recipient="b", msg_type="report", payload={})


def test_finding_validates_votes():
    with pytest.raises(ValidationError):
        Finding(finding_id="f", agent="a", domain="performance", device_id="d", votes={"nonsense": .5})
    with pytest.raises(ValidationError):
        Finding(finding_id="f", agent="a", domain="performance", device_id="d", votes={"weak_wifi": 1.5})


def test_bus_rejects_invalid_raw_message():
    reply = MessageBus().deliver_raw({"schema_version": "2.0", "sender": "x", "recipient": "y",
                                      "msg_type": "report", "message_id": "1", "correlation_id": "c"})
    assert reply.msg_type == "error" and "unsupported protocol" in reply.payload["error"]


def test_agent_rejects_wrong_message_type():
    orch = Orchestrator()
    with pytest.raises(ValueError):
        orch.bus.request(make_envelope("orchestrator", "performance_agent", "verify_request", {}, "c"))


def test_every_message_is_logged_and_valid():
    orch = Orchestrator()
    orch.run(generate("link_congestion"))
    assert len(orch.bus.log) == 26  # 12 handshake + 2 TrustGuard audit + 12 diagnosis
    for msg in orch.bus.log:
        Envelope.model_validate(msg)


def test_transient_fault_recovers_with_same_diagnosis():
    clean = Orchestrator().run(generate("link_congestion"))
    rep = Orchestrator(inject_faults={"infrastructure_agent": "transient"}).run(generate("link_congestion"))
    assert rep["agent_health"]["infrastructure_agent"]["status"] == "recovered"
    assert rep["status"] == clean["status"] and rep["confidence"] == clean["confidence"]


def test_permanent_fault_degrades_gracefully():
    rep = Orchestrator(inject_faults={"infrastructure_agent": "permanent"}).run(generate("link_congestion"))
    assert rep["agent_health"]["infrastructure_agent"]["status"] == "failed"
    assert rep["status"] != "error"
    assert rep["confidence"] <= 0.75
    assert any("infrastructure_agent" in l for l in rep["limitations"])


def test_connectivity_loss_falls_back_without_topology():
    rep = Orchestrator(inject_faults={"connectivity_agent": "permanent"}).run(generate("interface_fault"))
    assert rep["status"] != "error" and rep["root_cause_devices"]


def test_all_analysis_agents_fail_is_reported_clearly():
    faults = {a: "permanent" for a in ("performance_agent", "infrastructure_agent", "connectivity_agent")}
    rep = Orchestrator(inject_faults=faults).run(generate("link_congestion"))
    assert rep["status"] == "error" and "all analysis agents failed" in rep["suspected_root_cause"]


def test_correlation_failure_is_reported_clearly():
    rep = Orchestrator(inject_faults={"correlation_agent": "permanent"}).run(generate("link_congestion"))
    assert rep["status"] == "error" and "correlation agent failed" in rep["suspected_root_cause"]
