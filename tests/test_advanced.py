import copy
import random

from netcoop import Orchestrator
from netcoop.generator import SCENARIOS, generate
from netcoop.normalizer import normalize


def test_multi_fault_reports_secondary_finding():
    rep = Orchestrator().run(generate("multi_fault"))
    sec = {f["device_id"]: f["hypothesis"] for f in rep["secondary_findings"]}
    assert sec == {"DEPT_SW_01": "interface_fault"}
    assert any("multi-fault" in l for l in rep["limitations"])


def test_rising_trend_detected():
    res = normalize(generate("trend_interface_errors"))
    t = res.devices["DEPT_SW_01"]["trends"]
    assert "interface_errors" in t and t["interface_errors"]["last"] > 250
    assert res.devices["DEPT_SW_01"]["metrics"]["interface_errors"] > 250   # latest, not median


def test_stale_samples_ignored():
    doc = generate("link_congestion")
    stale = copy.deepcopy(doc["records"][0])
    stale["timestamp"] = "2026-10-30T00:00:00Z"
    stale["metrics"]["latency_ms"] = 9999
    doc["records"].append(stale)
    res = normalize(doc)
    assert any("stale" in i["message"] for i in res.issues)
    assert res.devices[stale["device_id"]]["metrics"]["latency_ms"] < 9999


def test_challenge_round_widens_margin_on_ambiguous_case():
    rep = Orchestrator().run(generate("conflicting_evidence"))
    c = rep["challenge_round"]
    assert c and c["triggered"] and c["margin_after"] > c["margin_before"]


def test_challenge_not_triggered_on_clear_case():
    orch = Orchestrator()
    rep = orch.run(generate("link_congestion"))
    assert rep["challenge_round"] is None
    assert not any(m["msg_type"] == "challenge_request" for m in orch.bus.log)


def test_guidance_for_low_confidence():
    rep = Orchestrator().run(generate("conflicting_evidence"))
    assert rep["what_would_raise_confidence"]


def _mutate(rng, node):
    """Randomly corrupt a JSON-like structure."""
    if isinstance(node, dict) and node:
        k = rng.choice(list(node))
        r = rng.random()
        if r < .2: del node[k]
        elif r < .4: node[k] = rng.choice([None, "x", -1, 1e99, float("nan"), [], {}, True, "100%"])
        elif r < .5: node[rng.choice(["a", "metrics", "status"])] = rng.choice([[], "q", 5])
        else: _mutate(rng, node[k])
    elif isinstance(node, list) and node:
        i = rng.randrange(len(node))
        if rng.random() < .3: node.pop(i)
        elif rng.random() < .3: node[i] = rng.choice([None, 3, "junk", [], {}])
        else: _mutate(rng, node[i])


def test_fuzz_never_crashes_and_always_returns_structured_report():
    rng = random.Random(7)
    for i in range(300):
        doc = copy.deepcopy(generate(rng.choice(SCENARIOS), seed=i))
        for _ in range(rng.randint(1, 6)):
            _mutate(rng, doc)
        rep = Orchestrator().run(doc)
        assert rep["status"] in ("healthy", "diagnosed", "tentative", "insufficient_evidence", "error")
        assert 0.0 <= rep["confidence"] <= 1.0
        assert isinstance(rep["limitations"], list) and "suspected_root_cause" in rep


def test_fuzz_garbage_top_level():
    rng = random.Random(3)
    for _ in range(50):
        junk = rng.choice([None, "", [], {}, [None], [[]], {"records": None}, {"records": [1, 2]},
                           {"records": "x"}, 3.14, True])
        assert Orchestrator().run(junk)["status"] == "error"
