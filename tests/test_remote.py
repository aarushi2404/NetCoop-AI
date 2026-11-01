import pytest

from netcoop import Orchestrator
from netcoop.generator import generate
from netcoop.remote import start_in_thread


@pytest.fixture()
def server():
    srv, url = start_in_thread()
    yield srv, url
    srv.shutdown()


@pytest.mark.parametrize("scenario", ["weak_wifi", "dns_failure", "dhcp_failure", "link_congestion", "normal"])
def test_remote_agent_gives_same_diagnosis_as_local(server, scenario):
    _, url = server
    local = Orchestrator().run(generate(scenario))
    remote = Orchestrator(remote_connectivity=url).run(generate(scenario))
    assert remote["status"] == local["status"]
    assert remote.get("root_cause_devices") == local.get("root_cause_devices")
    assert abs(remote["confidence"] - local["confidence"]) < 0.05


def test_card_reports_http_transport(server):
    _, url = server
    orch = Orchestrator(remote_connectivity=url)
    orch.run(generate("weak_wifi"))
    assert orch.cards["connectivity_agent"]["transport"] == "http"


def test_remote_down_degrades_gracefully():
    rep = Orchestrator(remote_connectivity="http://127.0.0.1:9").run(generate("weak_wifi"))
    assert rep["agent_health"]["connectivity_agent"]["status"] == "failed"
    assert "unreachable" in rep["agent_health"]["connectivity_agent"]["error"]
    assert rep["status"] != "error" and rep["confidence"] <= 0.75


def test_remote_malformed_response_is_contained():
    srv, url = start_in_thread("malformed")
    try:
        rep = Orchestrator(remote_connectivity=url).run(generate("weak_wifi"))
        assert rep["agent_health"]["connectivity_agent"]["status"] == "failed"
        assert rep["status"] != "error"
    finally:
        srv.shutdown()
