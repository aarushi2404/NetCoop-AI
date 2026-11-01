"""Invariants a judge should be able to rely on:

* an agent that sends invalid findings is excluded, and its findings cannot move the diagnosis;
* every committed diagnosis is backed by evidence that traces to raw input records;
* uncertainty (tentative / insufficient evidence / degraded agents) is always surfaced, never hidden.
"""
import json
from pathlib import Path

import pytest

from netcoop import Orchestrator
from netcoop.agents import InfrastructureAgent
from netcoop.generator import SCENARIOS, generate
from netcoop.protocol import Envelope, make_envelope
from netcoop.prooftrace import verify_prooftrace

DATA = Path(__file__).resolve().parents[1] / "data" / "scenarios"


def outcome(rep):
    return rep["status"], rep.get("root_cause_type"), rep.get("root_cause_devices"), rep["confidence"]


# ------------------------------------------------------------------ invalid findings cannot influence
class RogueInfrastructure(InfrastructureAgent):
    """Analyses honestly, then corrupts its reply in a configurable way before sending it."""

    def __init__(self, corrupt):
        super().__init__()
        self.corrupt = corrupt

    def _handle(self, env):
        reply = super()._handle(env)
        if env.msg_type != "analyze_request":
            return reply
        payload = json.loads(json.dumps(reply.payload))
        self.corrupt(payload)
        try:   # an honest sender is stopped by its own envelope validation ...
            return make_envelope(self.name, env.sender, "finding_batch", payload, env.correlation_id)
        except Exception:
            # ... so emulate a foreign sender that skips validation: the bus must still catch it
            return Envelope.model_construct(**{**reply.model_dump(), "payload": payload})


def _vote_out_of_range(p):
    p["findings"][0]["votes"] = {"hardware_failure": 7.0}


def _unknown_hypothesis(p):
    p["findings"][0]["votes"] = {"cosmic_rays": 1.0}


def _missing_findings(p):
    del p["findings"]


def _bad_strength(p):
    p["findings"][0]["signal_strength"] = {"device_critical": -3}


def _wrong_domain(p):
    p["domain"] = "astrology"
    p["findings"][0]["domain"] = "astrology"


@pytest.mark.parametrize("corrupt", [_vote_out_of_range, _unknown_hypothesis, _missing_findings,
                                     _bad_strength, _wrong_domain])
@pytest.mark.parametrize("scenario", ["hardware_failure", "link_congestion"])
def test_invalid_findings_are_rejected_and_have_no_influence(scenario, corrupt):
    orch = Orchestrator(prooftrace=False)
    orch.bus.register(RogueInfrastructure(corrupt))
    rep = orch.run(generate(scenario))
    assert rep["agent_health"]["infrastructure_agent"]["status"] == "failed"
    assert any("infrastructure_agent" in l for l in rep["limitations"])
    # the corrupted batch never reached the correlation agent
    for m in orch.bus.log:
        if m["msg_type"] == "correlate_request":
            assert all(b["agent"] != "infrastructure_agent" for b in m["payload"]["batches"])
    # identical to the same run with that agent simply down: the invalid data had zero influence
    baseline = Orchestrator(inject_faults={"infrastructure_agent": "permanent"}, prooftrace=False)
    assert outcome(rep) == outcome(baseline.run(generate(scenario)))


def test_reply_with_unsupported_protocol_version_is_rejected():
    class FutureAgent(InfrastructureAgent):
        def _handle(self, env):
            reply = super()._handle(env)
            return Envelope.model_construct(**{**reply.model_dump(), "schema_version": "2.0"})

    orch = Orchestrator(prooftrace=False)
    orch.bus.register(FutureAgent())
    rep = orch.run(generate("hardware_failure"))
    h = rep["agent_health"]["infrastructure_agent"]
    assert h["status"] == "failed" and "schema_version" in h["error"]


def test_findings_about_unknown_devices_cannot_become_the_root_cause():
    def ghost(p):
        f = dict(p["findings"][0], finding_id="x:GHOST", device_id="GHOST_SW_99",
                 votes={"hardware_failure": 1.0}, signals_present=["device_critical"])
        p["findings"].append(f)

    orch = Orchestrator(prooftrace=False)
    orch.bus.register(RogueInfrastructure(ghost))
    rep = orch.run(generate("link_congestion"))
    assert "GHOST_SW_99" not in (rep.get("root_cause_devices") or [])
    assert "GHOST_SW_99" not in rep.get("affected_devices", [])
    assert rep["root_cause_type"] == Orchestrator(prooftrace=False).run(generate("link_congestion"))["root_cause_type"]


def test_scope_naming_unknown_devices_cannot_redirect_blame():
    from netcoop.agents import ConnectivityAgent

    class RogueConnectivity(ConnectivityAgent):
        def _handle(self, env):
            reply = super()._handle(env)
            if env.msg_type != "analyze_request":
                return reply
            p = json.loads(json.dumps(reply.payload))
            p["scope"]["degraded"].insert(0, "GHOST_SW_99")
            p["scope"]["root_candidates"] = ["GHOST_SW_99"] + p["scope"]["root_candidates"]
            p["findings"].append(dict(p["findings"][0], finding_id="x:GHOST", device_id="GHOST_SW_99",
                                      votes={"dns_failure": 1.0}))
            return self._reply(env, "finding_batch", p)

    honest = Orchestrator(prooftrace=False).run(generate("hardware_failure"))
    orch = Orchestrator(prooftrace=False)
    orch.bus.register(RogueConnectivity())
    rep = orch.run(generate("hardware_failure"))
    assert "GHOST_SW_99" not in json.dumps({k: rep.get(k) for k in ("root_cause_devices", "affected_devices",
                                                                    "downstream_affected", "secondary_findings")})
    assert outcome(rep) == outcome(honest)


# ------------------------------------------------------------------ incorrect units / out-of-range values
def _records(metrics, n=3):
    return {"records": [{"device_id": "SW1", "timestamp": f"2026-01-01T00:0{i}:00Z", "status": "ok",
                         "metrics": metrics} for i in range(n)]}


def test_impossible_values_are_dropped_not_used_as_evidence():
    rep = Orchestrator().run(_records({"packet_loss_pct": 150, "latency_ms": -20, "cpu_utilization_pct": 30}))
    assert rep["status"] != "diagnosed"
    assert all(e["metric"] not in ("packet_loss_pct", "latency_ms") for e in rep["supporting_evidence"])
    assert any("packet_loss_pct" in json.dumps(i) for i in rep["data_quality"].get("issues", rep["data_quality"]))


def test_units_are_converted_not_misread():
    as_seconds = Orchestrator(prooftrace=False).run(_records({"latency": "0.4 s", "cpu_utilization_pct": 30}))
    as_ms = Orchestrator(prooftrace=False).run(_records({"latency_ms": 400, "cpu_utilization_pct": 30}))
    assert outcome(as_seconds) == outcome(as_ms)


# ------------------------------------------------------------------ fault classes
def test_multiple_simultaneous_faults_are_all_reported():
    rep = Orchestrator().run(generate("multi_fault"))
    primary = set(rep["root_cause_devices"])
    secondary = {f["device_id"] for f in rep["secondary_findings"]}
    assert rep["status"] == "diagnosed" and secondary and not (primary & secondary)


def test_ambiguous_fault_is_hedged_with_alternatives():
    rep = Orchestrator().run(generate("conflicting_evidence"))
    assert rep["status"] == "tentative" and rep["hedge"]
    assert rep["alternative_causes"] and rep["confidence"] < 0.75
    assert rep["conflicts_resolved"]


def test_insufficient_evidence_does_not_name_a_cause():
    rep = Orchestrator().run(generate("insufficient_data"))
    assert rep["status"] == "insufficient_evidence" and rep["root_cause_type"] is None
    assert rep["abstention"] and rep["what_would_raise_confidence"]
    assert rep["prooftrace"]["missing_information"]


# ------------------------------------------------------------------ every diagnosis is traceable
@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_every_diagnosis_is_traceable_and_carries_uncertainty(scenario):
    raw = json.loads((DATA / f"{scenario}.json").read_text(encoding="utf-8"))
    orch = Orchestrator()
    rep = orch.run(raw)
    assert 0.0 <= rep["confidence"] < 1.0                        # never claims certainty
    if rep["status"] in ("diagnosed", "tentative"):
        trace = rep["prooftrace"]
        assert rep["root_cause_type"] and rep["supporting_evidence"]
        assert rep["alternative_causes"] is not None and rep["limitations"] is not None
        root = set(rep["root_cause_devices"])
        cited = [e for e in trace["evidence"] if e["device_id"] in root]
        assert cited and all(e["raw_samples"] or e["metric"] == "status" for e in cited)
        assert all(e["observed_by"] for e in cited)              # every piece names the agent message
        assert verify_prooftrace(trace, raw, orch.bus.log)["verified"]
    else:
        assert not rep.get("root_cause_type")
    degraded = [a for a, h in rep.get("agent_health", {}).items() if h["status"] in ("failed", "incompatible")]
    for a in degraded:
        assert any(a in l for l in rep["limitations"])
