import json

import pytest
from pydantic import ValidationError

from netcoop import Orchestrator
from netcoop.generator import generate
from netcoop.protocol import Envelope, make_envelope
from netcoop.schemas import export_schemas, validate_file


def test_every_agent_publishes_a_card():
    orch = Orchestrator()
    orch.run(generate("link_congestion"))
    assert set(orch.cards) == {"performance_agent", "infrastructure_agent", "connectivity_agent",
                               "correlation_agent", "reporting_agent", "trustguard"}
    c = orch.cards["infrastructure_agent"]
    assert "analyze_request" in c["accepts"] and "finding_batch" in c["produces"]
    assert "1.0" in c["protocol_versions"]


def test_incompatible_agent_is_excluded_not_fatal():
    orch = Orchestrator()
    agent = orch.bus.agents["infrastructure_agent"]
    original = agent.card
    agent.card = lambda: original() | {"protocol_versions": ["2.0"]}
    rep = orch.run(generate("link_congestion"))
    assert rep["agent_health"]["infrastructure_agent"]["status"] == "incompatible"
    assert rep["status"] != "error"
    assert any("infrastructure_agent" in l for l in rep["limitations"])


def test_payload_requirements_enforced():
    with pytest.raises(ValidationError, match="missing required"):
        make_envelope("a", "b", "finding_batch", {"agent": "x"}, "c")


def test_non_conforming_finding_rejected():
    bad = {"agent": "x", "domain": "performance",
           "findings": [{"finding_id": "1", "agent": "x", "domain": "performance", "device_id": "d",
                         "votes": {"link_congestion": 7}}]}
    with pytest.raises(ValidationError):
        make_envelope("x", "orchestrator", "finding_batch", bad, "c")


def test_export_schemas_and_validate_logs(tmp_path):
    paths = export_schemas(tmp_path / "schemas")
    assert any(p.name == "envelope.schema.json" for p in paths)
    assert (tmp_path / "schemas/agent_cards/correlation_agent.json").exists()
    orch = Orchestrator()
    orch.run(generate("hardware_failure"))
    log = tmp_path / "log.jsonl"
    log.write_text("\n".join(json.dumps(m) for m in orch.bus.log))
    ok, errors = validate_file(log)
    assert ok == len(orch.bus.log) and not errors


def test_validate_detects_bad_message(tmp_path):
    f = tmp_path / "m.json"
    f.write_text(json.dumps({"schema_version": "9", "sender": "a", "recipient": "b", "msg_type": "report",
                             "message_id": "1", "correlation_id": "2", "payload": {}}))
    ok, errors = validate_file(f)
    assert ok == 0 and errors


def test_replay_is_deterministic(tmp_path):
    from netcoop.schemas import replay_log
    for scenario in ("hardware_failure", "conflicting_evidence", "multi_fault"):
        orch = Orchestrator()
        orch.run(generate(scenario))
        log = tmp_path / f"{scenario}.jsonl"
        log.write_text("\n".join(json.dumps(m) for m in orch.bus.log))
        res = replay_log(log)
        assert res["deterministic"] and res["requests_replayed"] >= 10, res
