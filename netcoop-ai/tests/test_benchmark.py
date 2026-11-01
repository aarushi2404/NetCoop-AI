from netcoop.benchmark import calibration, run_benchmark


def test_benchmark_small_run_has_expected_structure():
    b = run_benchmark(n=40, seed=3, ablation=True)
    assert b["full"]["accuracy"] > 0.6 and b["full"]["selective_accuracy"] > 0.9
    assert "all 3 specialists + correlation" in b["ablation"]
    # the multi-agent system should beat every single-agent configuration
    full = b["ablation"]["all 3 specialists + correlation"]["accuracy"]
    for name in ("performance_agent only", "infrastructure_agent only", "connectivity_agent only"):
        assert full > b["ablation"][name]["accuracy"]
    assert 0 <= b["calibration"]["ece"] <= 1


def test_calibration_bins():
    rows = [{"pred": "x", "correct": True, "confidence": 0.9}, {"pred": "x", "correct": False, "confidence": 0.9},
            {"pred": "insufficient", "correct": False, "confidence": 0.1}]
    cal = calibration(rows)
    assert cal["bins"][0]["n"] == 2 and cal["bins"][0]["accuracy"] == 0.5
