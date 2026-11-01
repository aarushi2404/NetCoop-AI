import math

from netcoop.normalizer import normalize


def rec(**metrics):
    return {"device_id": "D1", "status": "ok", "metrics": metrics}


def m(raw):
    return normalize({"records": [raw]}).devices["D1"]["metrics"]


def test_unit_conversions():
    out = m({"device_id": "D1", "latency_s": 0.25, "util_fraction": 0.9, "throughput_gbps": 1.5})
    assert out["latency_ms"] == 250 and out["link_utilization_pct"] == 90 and out["throughput_mbps"] == 1500


def test_explicit_unit_dicts_and_strings():
    out = m({"device_id": "D1", "stats": {"latency": {"value": 0.1, "unit": "s"},
                                          "util": "94%", "loss": {"value": 0.02, "unit": "fraction"}}})
    assert out["latency_ms"] == 100 and out["link_utilization_pct"] == 94 and out["packet_loss_pct"] == 2


def test_bad_values_dropped_with_warning():
    res = normalize({"records": [rec(latency_ms="abc", link_utilization_pct=140, queue_drops=-1,
                                     cpu_utilization_pct=math.nan, jitter_ms=5)]})
    assert res.devices["D1"]["metrics"] == {"jitter_ms": 5}
    assert sum(1 for i in res.issues if i["level"] == "warning") == 4


def test_unsupported_schema_rejected_clearly():
    res = normalize({"schema_version": "3.0", "records": [rec(latency_ms=5)]})
    assert res.fatal and "3.0" in res.fatal


def test_unknown_unit_rejected():
    res = normalize({"records": [{"device_id": "D1", "stats": {"latency": {"value": 5, "unit": "parsec"}}}]})
    assert "latency_ms" not in res.devices["D1"]["metrics"]


def test_median_aggregation_resists_outlier():
    recs = [rec(latency_ms=v) for v in (10, 11, 12, 900, 10)]
    assert normalize({"records": recs}).devices["D1"]["metrics"]["latency_ms"] == 11


def test_missing_metric_is_not_zero():
    d = normalize({"records": [rec(latency_ms=10)]}).devices["D1"]
    assert "queue_drops" not in d["metrics"] and d["completeness"] < 0.5


def test_topology_unknown_parent_warns():
    res = normalize({"topology": {"devices": [{"id": "D1", "parent": "GHOST"}]}, "records": [rec(latency_ms=1)]})
    assert res.devices["D1"]["parent"] is None
    assert any("GHOST" in i["message"] for i in res.issues)
