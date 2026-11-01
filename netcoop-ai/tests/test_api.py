import json
import urllib.error
import urllib.request

import pytest

from netcoop.api import ORG_DIR, start_in_thread


@pytest.fixture(scope="module")
def url():
    srv, u = start_in_thread()
    yield u
    srv.shutdown()


def get(url, path):
    return json.loads(urllib.request.urlopen(url + path).read())


def post(url, path, body):
    req = urllib.request.Request(url + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        return 200, json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_catalog(url):
    c = get(url, "/api/catalog")
    assert {"hardware_failure", "normal"} <= {s["name"] for s in c["scenarios"]}
    assert "hardware_failure" in c["fixes"]


def test_diagnose_returns_real_pipeline_output(url):
    code, d = post(url, "/api/diagnose", {"source": "scenario", "name": "hardware_failure", "seed": 42})
    assert code == 200 and d["report"]["root_cause_type"] == "hardware_failure"
    assert d["prooftrace"]["checks"]["verified"] and len(d["log"]) == d["prooftrace"]["integrity"]["message_count"]
    assert "prooftrace" not in d["report"]
    assert d["health"]["DEPT_SW_01"]["active_signals"] and set(d["cards"]) >= {"correlation_agent"}


def test_fault_injection_and_upload(url):
    code, d = post(url, "/api/diagnose", {"source": "scenario", "name": "link_congestion",
                                          "faults": {"infrastructure_agent": "permanent"}})
    assert d["report"]["agent_health"]["infrastructure_agent"]["status"] == "failed"
    raw = {"records": [{"device_id": "SW1", "metrics": {"latency_ms": 10, "cpu_utilization_pct": 20}, "status": "ok"}]}
    code, d = post(url, "/api/diagnose", {"source": "upload", "name": "x.json", "raw": raw})
    assert code == 200 and d["report"]["status"] == "healthy"


def test_whatif_remediate_verify(url):
    spec = {"source": "scenario", "name": "hardware_failure"}
    _, w = post(url, "/api/whatif", {**spec, "device": "DEPT_SW_01", "metric": "cpu_utilization_pct", "value": 40})
    assert w["changed"] and w["after"]["leading_hypothesis"] == "link_congestion"
    _, r = post(url, "/api/remediate", {**spec, "hypothesis": "link_congestion"})
    assert r["outcome"] == "unresolved"
    _, v = post(url, "/api/verify", {**spec, "tamper": "none"})
    assert v["verified"]
    for t in ("raw", "vote", "drop"):
        _, v = post(url, "/api/verify", {**spec, "tamper": t})
        assert not v["verified"] and v["what"] != "nothing changed"


@pytest.mark.skipif(not ORG_DIR.exists(), reason="organizer incidents not generated")
def test_organizer_incident_hides_label_from_agents(url):
    name = sorted(ORG_DIR.glob("*.json"))[0].stem
    _, d = post(url, "/api/diagnose", {"source": "organizer", "name": name})
    assert d["incident"]["ground_truth"]["label"]
    assert "label" not in json.dumps(d["log"][0])   # not passed into the pipeline


def test_errors_are_json(url):
    assert post(url, "/api/diagnose", {"source": "scenario", "name": "nope"})[0] == 404
    assert post(url, "/api/diagnose", {"source": "organizer", "name": "../../etc/passwd"})[0] == 404
    assert post(url, "/api/whatif", {"source": "scenario", "name": "normal", "device": "X", "metric": "latency_ms",
                                     "value": 1})[0] == 400
    assert post(url, "/api/nothing", {})[0] == 404


def test_benchmarks_endpoint(url):
    b = get(url, "/api/benchmarks")
    assert "internal" in b and "organizer" in b


def test_adversarial_demo_through_api(url):
    spec = {"source": "scenario", "name": "adversarial_agent"}
    _, d = post(url, "/api/diagnose", spec)
    assert d["incident"]["simulation"]["applied"] and d["incident"]["faults_applied"] == {"performance_agent": "adversarial"}
    tg = d["report"]["trustguard"]
    assert tg["summary"]["flagged"] == 1 and tg["before_after"]["computed"]
    assert d["prooftrace"]["trustguard"]["records"] and d["prooftrace"]["checks"]["verified"]
    _, off = post(url, "/api/diagnose", {**spec, "simulation": False})
    assert off["report"]["trustguard"]["summary"]["flagged"] == 0
    _, v = post(url, "/api/verify", {**spec, "tamper": "audit"})
    assert not v["verified"] and "TrustGuard record" in v["what"]
