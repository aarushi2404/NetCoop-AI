import pytest

from netcoop import Orchestrator
from netcoop.generator import generate
from netcoop.remediation import compare_fixes, simulate_fix
from netcoop.remote import RemoteConnectivityAgent, start_in_thread


def _diag(name):
    doc = generate(name)
    return doc, Orchestrator(prooftrace=False).run(doc)


def test_fix_reports_before_after_health_and_expected_improvement():
    doc, rep = _diag("interface_fault")
    sim = simulate_fix(doc, rep)
    assert sim["outcome"] == "resolved"
    root = next(d for d in sim["devices"] if d["role"] == "root cause")
    assert root["before"]["active_signals"] and not root["after"]["active_signals"]
    assert root["after"]["health_index"] > root["before"]["health_index"]
    assert sim["expected_improvements"] and all(e["achieved"] for e in sim["expected_improvements"])


def test_wrong_fix_is_reported_unresolved():
    doc, rep = _diag("hardware_failure")
    sim = simulate_fix(doc, rep, hypothesis="link_congestion")
    assert sim["outcome"] == "unresolved" and not sim["incident_cleared"]
    assert {"high_cpu", "interface_errors"} <= set(sim["residual_signals"])


def test_partial_fix_is_reported_unresolved():
    doc, rep = _diag("link_congestion")
    sim = simulate_fix(doc, rep, efficacy=0.3)
    assert sim["outcome"] == "unresolved"
    assert not all(e["achieved"] for e in sim["expected_improvements"])


def test_fix_with_nothing_to_act_on_does_not_relieve_symptoms():
    doc, rep = _diag("latency_spike")
    sim = simulate_fix(doc, rep, hypothesis="interface_fault")
    assert sim["outcome"] == "unresolved" and "nothing to act on" in sim["explanation"]


def test_compare_fixes_corroborates_correct_diagnosis():
    doc, rep = _diag("hardware_failure")
    c = compare_fixes(doc, rep)
    assert c["resolving"] == ["hardware_failure"]


# ------------------------------------------------------------------ interoperability
@pytest.fixture()
def remote():
    srvs = []

    def start(mode="ok"):
        srv, url = start_in_thread(mode)
        srvs.append(srv)
        return url
    yield start
    for s in srvs:
        s.shutdown()


def test_negotiation_selects_common_format(remote):
    agent = RemoteConnectivityAgent(remote("ok"))
    neg = agent.negotiate()
    assert neg["status"] == "compatible" and neg["format"] == "wlo-1"
    assert "CO_CHANNEL_INTERFERENCE" in neg["unmapped_causes"]
    assert set(agent.card()["hypotheses"]) == {"weak_wifi", "dns_failure", "dhcp_failure"}


def test_incompatible_agent_rejected_at_handshake(remote):
    rep = Orchestrator(remote_connectivity=remote("incompatible")).run(generate("weak_wifi"))
    h = rep["agent_health"]["connectivity_agent"]
    assert h["status"] == "incompatible" and "no common format" in h["error"]
    assert rep["status"] != "error"


def test_invalid_reply_items_dropped_not_fatal(remote):
    orch = Orchestrator(remote_connectivity=remote("partial"))
    rep = orch.run(generate("weak_wifi"))
    batch = next(m["payload"] for m in orch.bus.log if m["msg_type"] == "finding_batch"
                 and m["sender"] == "connectivity_agent")
    probs = batch["remote_validation"]["problems"]
    assert len(probs) == 4 and any("strength" in p for p in probs)
    assert rep["root_cause_type"] == "weak_wifi"


def test_flaky_remote_recovers(remote):
    rep = Orchestrator(remote_connectivity=remote("flaky")).run(generate("weak_wifi"))
    assert rep["agent_health"]["connectivity_agent"]["status"] == "recovered"


def test_slow_remote_times_out_gracefully(remote):
    orch = Orchestrator(remote_connectivity=remote("slow"), prooftrace=False)
    orch.bus.agents["connectivity_agent"].timeout = 0.5
    rep = orch.run(generate("weak_wifi"))
    assert rep["agent_health"]["connectivity_agent"]["status"] == "failed"
    assert "timed out" in rep["agent_health"]["connectivity_agent"]["error"]


def test_remote_findings_are_decisive_and_cited(remote):
    orch = Orchestrator(remote_connectivity=remote("ok"))
    rep = orch.run(generate("weak_wifi"))
    t = rep["prooftrace"]
    conn = next(a for a in t["agents"] if a["agent"] == "connectivity_agent")
    assert conn["transport"] == "http" and conn["leave_one_out"]["contribution"] == "decisive"
    batch = next(m for m in orch.bus.log if m["message_id"] == conn["findings_message_id"])
    assert len(batch["payload"]["remote_response_sha256"]) == 64
    assert any(o["agent"] == "connectivity_agent" for e in t["evidence"] for o in e["observed_by"])
    assert t["checks"]["verified"]
