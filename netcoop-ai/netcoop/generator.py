"""Synthetic telemetry generator covering every scenario in the problem statement.

Extends the organizer's Colab generator (same metric names, same `device_id / metrics /
status / timestamp` shape) with: a campus topology, wireless + DNS/DHCP metrics,
multiple samples per device, and scenarios for malformed and incompatible input.

    python -m netcoop generate --out data/scenarios
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOPOLOGY = {"devices": [
    {"id": "CAMPUS_CORE_RTR_01", "role": "router", "parent": None},
    {"id": "HOSTEL_CORE_SW_01", "role": "switch", "parent": "CAMPUS_CORE_RTR_01"},
    {"id": "HOSTEL_AP_01", "role": "access_point", "parent": "HOSTEL_CORE_SW_01"},
    {"id": "HOSTEL_AP_02", "role": "access_point", "parent": "HOSTEL_CORE_SW_01"},
    {"id": "HOSTEL_AP_03", "role": "access_point", "parent": "HOSTEL_CORE_SW_01"},
    {"id": "DEPT_SW_01", "role": "switch", "parent": "CAMPUS_CORE_RTR_01"},
    {"id": "LECTURE_AP_01", "role": "access_point", "parent": "DEPT_SW_01"},
]}

_BASE = dict(latency_ms=12, jitter_ms=2, packet_loss_pct=0, link_utilization_pct=35,
             cpu_utilization_pct=22, memory_utilization_pct=40, queue_drops=0,
             interface_errors=0, link_flaps=0, throughput_mbps=300, bandwidth_mbps=1000)
_AP_EXTRA = dict(wifi_rssi_dbm=-58, retransmission_pct=3, dns_failure_pct=0, dhcp_failure_pct=0,
                 throughput_mbps=90, bandwidth_mbps=300, link_utilization_pct=30)
_COUNTS = {"queue_drops", "interface_errors", "link_flaps"}
_T0 = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
SAMPLES = 5

# scenario -> {device: ({metric overrides}, status)}
_FAULTS: dict[str, dict[str, tuple[dict, str]]] = {
    "link_congestion": {
        "HOSTEL_CORE_SW_01": (dict(link_utilization_pct=94, queue_drops=160, latency_ms=280,
                                   jitter_ms=45, packet_loss_pct=2.5, cpu_utilization_pct=55), "Warning"),
        **{f"HOSTEL_AP_0{i}": (dict(latency_ms=140, packet_loss_pct=1.2, jitter_ms=18), "Warning")
           for i in (1, 2, 3)},
    },
    "weak_wifi": {
        "HOSTEL_AP_02": (dict(wifi_rssi_dbm=-82, retransmission_pct=22, packet_loss_pct=3,
                              jitter_ms=45, latency_ms=90), "Warning"),
    },
    "interface_fault": {
        "DEPT_SW_01": (dict(interface_errors=320, link_flaps=7, packet_loss_pct=8, latency_ms=60,
                            jitter_ms=20), "Warning"),
        "LECTURE_AP_01": (dict(latency_ms=130, packet_loss_pct=2), "Warning"),
    },
    "dns_failure": {
        f"HOSTEL_AP_0{i}": (dict(dns_failure_pct=88 + i), "Warning") for i in (1, 2, 3)
    },
    "dhcp_failure": {
        "LECTURE_AP_01": (dict(dhcp_failure_pct=92), "Warning"),
    },
    "hardware_failure": {
        "DEPT_SW_01": (dict(cpu_utilization_pct=99.9, link_utilization_pct=99.5, packet_loss_pct=22,
                            latency_ms=800, queue_drops=9000, interface_errors=300, jitter_ms=120),
                       "Critical"),
        "LECTURE_AP_01": (dict(latency_ms=700, packet_loss_pct=20), "Warning"),
    },
    "device_overload": {
        "HOSTEL_CORE_SW_01": (dict(cpu_utilization_pct=96, memory_utilization_pct=93, latency_ms=160,
                                   packet_loss_pct=1.5, link_utilization_pct=55, jitter_ms=25), "Warning"),
        **{f"HOSTEL_AP_0{i}": (dict(latency_ms=125, packet_loss_pct=1.1), "Warning") for i in (1, 2, 3)},
    },
    # two independent faults at the same time, in different parts of the campus
    "multi_fault": {
        "HOSTEL_AP_02": (dict(wifi_rssi_dbm=-84, retransmission_pct=24, packet_loss_pct=3.5,
                              jitter_ms=42, latency_ms=95), "Warning"),
        "DEPT_SW_01": (dict(interface_errors=340, link_flaps=8, packet_loss_pct=7, latency_ms=70,
                            jitter_ms=22), "Warning"),
        "LECTURE_AP_01": (dict(latency_ms=125, packet_loss_pct=1.8), "Warning"),
    },
    # slowly worsening interface: an early-warning case (values ramp over the 5 samples)
    "trend_interface_errors": {
        "DEPT_SW_01": (dict(interface_errors=[0, 15, 60, 150, 320], link_flaps=[0, 0, 2, 4, 7],
                            packet_loss_pct=[0.1, 0.3, 1.5, 4, 8], latency_ms=[12, 20, 45, 90, 140]),
                       "Warning"),
    },
    # latency spike without any corroborating cause (organizer's 'latency_spike' profile)
    "latency_spike": {
        "HOSTEL_CORE_SW_01": (dict(latency_ms=260, jitter_ms=55, packet_loss_pct=0.6,
                                   link_utilization_pct=72, cpu_utilization_pct=55, queue_drops=20),
                              "Warning"),
    },
    # a failing switch whose link is NOT saturated (40 %); used with an adversarial performance agent that
    # claims congestion with 0.99 certainty. The telemetry is an ordinary hardware failure; only the agent lies.
    "adversarial_agent": {
        "DEPT_SW_01": (dict(cpu_utilization_pct=99.9, interface_errors=300, link_utilization_pct=40,
                            latency_ms=450, packet_loss_pct=9, jitter_ms=60, queue_drops=40,
                            memory_utilization_pct=62), "Critical"),
        "LECTURE_AP_01": (dict(latency_ms=380, packet_loss_pct=8), "Warning"),
    },
    # congestion-like and interface-fault-like symptoms at once: agents disagree
    "conflicting_evidence": {
        "DEPT_SW_01": (dict(link_utilization_pct=88, latency_ms=180, packet_loss_pct=4, jitter_ms=40,
                            queue_drops=10, interface_errors=400, link_flaps=5, cpu_utilization_pct=45),
                       "Warning"),
    },
}

# ground truth used by the benchmark: scenario -> (root-cause type or "healthy", root-cause devices)
SCENARIO_TRUTH: dict[str, tuple[str, list[str]]] = {
    "normal": ("healthy", []),
    "link_congestion": ("link_congestion", ["HOSTEL_CORE_SW_01"]),
    "weak_wifi": ("weak_wifi", ["HOSTEL_AP_02"]),
    "interface_fault": ("interface_fault", ["DEPT_SW_01"]),
    "dns_failure": ("dns_failure", ["HOSTEL_AP_01", "HOSTEL_AP_02", "HOSTEL_AP_03"]),
    "dhcp_failure": ("dhcp_failure", ["LECTURE_AP_01"]),
    "hardware_failure": ("hardware_failure", ["DEPT_SW_01"]),
    "device_overload": ("device_overload", ["HOSTEL_CORE_SW_01"]),
    "conflicting_evidence": ("interface_fault", ["DEPT_SW_01"]),
    "trend_interface_errors": ("interface_fault", ["DEPT_SW_01"]),
    "adversarial_agent": ("hardware_failure", ["DEPT_SW_01"]),
}

# Demo-only run configuration carried by a scenario file. It is never read by the orchestrator or the agents:
# the CLI, the dashboards and the API apply it explicitly (and show that they did) via `simulation_faults`.
SIMULATION: dict[str, dict] = {
    "adversarial_agent": {
        "inject_faults": {"performance_agent": "adversarial"},
        "note": "controlled adversarial test: the performance agent submits one misleading vote (0.99) on the "
                "most degraded device while its evidence stays truthful",
    },
}

SCENARIOS = ["normal", *_FAULTS, "insufficient_data", "malformed_input",
             "incompatible_schema_v0", "incompatible_schema_v2", "unsupported_schema"]


def _noisy(rng: random.Random, name: str, centre: float, noise: float = 0.05) -> float:
    v = centre * (1 + rng.uniform(-noise, noise))
    if name in _COUNTS:
        return float(int(round(v)))
    if name.endswith("_pct"):
        v = min(100.0, max(0.0, v))
    return round(v, 2)


def _device_profile(dev: dict) -> dict:
    prof = dict(_BASE)
    if dev["role"] == "access_point":
        prof.update(_AP_EXTRA)
    return prof


def _scale(base: float, target, severity: float):
    """Interpolate from healthy `base` to the fault value `target` (scalar or per-sample list)."""
    if isinstance(target, list):
        return [base + (t - base) * severity for t in target]
    return base + (target - base) * severity


def _canonical_records(scenario: str, rng: random.Random, severity: float = 1.0,
                       noise: float = 0.05, dropout: float = 0.0) -> list[dict]:
    faults = _FAULTS.get(scenario, {})
    records = []
    for dev in TOPOLOGY["devices"]:
        prof = _device_profile(dev)
        override, status = faults.get(dev["id"], ({}, "Healthy"))
        if severity != 1.0:
            override = {k: _scale(prof[k], v, severity) for k, v in override.items()}
        prof.update(override)
        for s in range(SAMPLES):
            records.append({
                "timestamp": (_T0 + timedelta(minutes=s)).isoformat().replace("+00:00", "Z"),
                "device_id": dev["id"],
                "metrics": {k: _noisy(rng, k, v[s] if isinstance(v, list) else v, noise)
                            for k, v in prof.items() if rng.random() >= dropout},
                "status": status,
            })
    return records


def _to_v0(rec: dict) -> dict:
    """Legacy flat layout: seconds, fractions, short names, epoch timestamps."""
    m = rec["metrics"]
    ts = datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00")).timestamp()
    out = {"schema_version": "0.9", "node": rec["device_id"], "ts": int(ts),
           "state": {"Healthy": "ok", "Warning": "degraded", "Critical": "down"}[rec["status"]],
           "latency_s": round(m["latency_ms"] / 1000, 4), "jitter_s": round(m["jitter_ms"] / 1000, 4),
           "loss_fraction": round(m["packet_loss_pct"] / 100, 4),
           "util_fraction": round(m["link_utilization_pct"] / 100, 4),
           "cpu_fraction": round(m["cpu_utilization_pct"] / 100, 4),
           "drops": m["queue_drops"], "if_errors": m["interface_errors"]}
    return out


def _to_v2(rec: dict) -> dict:
    """Nested layout with explicit {value, unit} pairs."""
    m = rec["metrics"]
    return {"schemaVersion": "2.1", "devId": rec["device_id"], "time": rec["timestamp"],
            "state": {"Healthy": "ok", "Warning": "degraded", "Critical": "failed"}[rec["status"]],
            "stats": {
                "latency": {"value": round(m["latency_ms"] / 1000, 4), "unit": "s"},
                "jitter": {"value": m["jitter_ms"], "unit": "ms"},
                "loss": {"value": m["packet_loss_pct"], "unit": "pct"},
                "link_util": {"value": round(m["link_utilization_pct"] / 100, 4), "unit": "fraction"},
                "cpu": {"value": m["cpu_utilization_pct"], "unit": "pct"},
                "drops": {"value": m["queue_drops"]},
                "if_errors": {"value": m["interface_errors"]},
            }}


def generate(scenario: str, seed: int = 42, severity: float = 1.0, noise: float = 0.05,
             dropout: float = 0.0) -> dict:
    """Return the raw input document for a scenario (what a collector would hand us)."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario '{scenario}'. Choose from: {', '.join(SCENARIOS)}")
    rng = random.Random(f"{scenario}-{seed}")
    base = "link_congestion" if scenario.startswith(("incompatible", "malformed", "unsupported")) else scenario
    recs = _canonical_records(base, rng, severity, noise, dropout)
    doc: dict = {"incident_id": f"INC-{scenario.upper()}", "topology": TOPOLOGY}

    if scenario == "insufficient_data":
        keep = {"HOSTEL_CORE_SW_01", "HOSTEL_AP_01"}
        thin = []
        for r in recs:
            if r["device_id"] in keep:
                thin.append({"timestamp": r["timestamp"], "device_id": r["device_id"],
                             "metrics": {"latency_ms": 240 if r["device_id"] in keep else 12},
                             "status": "Unknown"})
        doc["records"] = thin
    elif scenario == "malformed_input":
        bad: list = []
        for r in recs:
            r = json.loads(json.dumps(r))
            if r["device_id"] == "HOSTEL_AP_01" and len(bad) % 2 == 0:
                r["metrics"]["link_utilization_pct"] = 140          # out of range
            if r["device_id"] == "DEPT_SW_01":
                r["metrics"]["latency_ms"] = "n/a"                   # non-numeric
                r["metrics"]["queue_drops"] = -5                     # impossible
            if r["device_id"] == "HOSTEL_AP_02":
                r["metrics"]["cpu_utilization_pct"] = float("nan")   # NaN
            bad.append(r)
        bad += ["this-is-not-a-record", {"metrics": {"latency_ms": 10}},     # junk + no device id
                {"device_id": "GHOST_SW_99", "metrics": {}, "timestamp": "yesterday-ish"}]
        doc["records"] = bad
    elif scenario == "incompatible_schema_v0":
        doc.pop("topology")  # legacy collectors did not send topology
        doc["topology"] = TOPOLOGY
        doc["records"] = [_to_v0(r) for r in recs]
    elif scenario == "incompatible_schema_v2":
        doc["records"] = [_to_v2(r) for r in recs]
    elif scenario in SIMULATION:
        doc["schema_version"] = "1.0"
        doc["records"] = recs
        doc["simulation"] = SIMULATION[scenario]
    elif scenario == "unsupported_schema":
        doc["schema_version"] = "3.0"
        doc["records"] = recs
    else:
        doc["schema_version"] = "1.0"
        doc["records"] = recs
    return doc


def simulation_faults(raw) -> dict[str, str]:
    """Fault injection requested by a demo scenario's `simulation` block ({} for ordinary telemetry)."""
    sim = raw.get("simulation") if isinstance(raw, dict) else None
    faults = sim.get("inject_faults") if isinstance(sim, dict) else None
    if not isinstance(faults, dict):
        return {}
    ok = {"transient", "permanent", "adversarial"}
    return {str(a): str(m) for a, m in faults.items() if m in ok}


def generate_telemetry(fault_type: str = "normal") -> dict:
    """Single-record helper mirroring the organizer's Colab generator output shape."""
    rng = random.Random()
    prof = dict(_BASE)
    status = "Healthy"
    if fault_type == "latency_spike":
        prof.update(latency_ms=rng.uniform(150, 400), jitter_ms=rng.uniform(30, 80),
                    link_utilization_pct=rng.uniform(60, 85), packet_loss_pct=rng.uniform(0.1, 1.5),
                    queue_drops=rng.randint(0, 50))
        status = "Warning"
    elif fault_type == "hardware_failure":
        prof.update(cpu_utilization_pct=99.9, link_utilization_pct=100.0,
                    packet_loss_pct=rng.uniform(15, 30), latency_ms=rng.uniform(500, 1000),
                    queue_drops=rng.randint(5000, 15000), interface_errors=rng.randint(100, 500))
        status = "Critical"
    return {"timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "device_id": f"SW_CAMPUS_{rng.randint(1, 10)}",
            "metrics": {k: round(v, 2) for k, v in prof.items()}, "status": status}


def write_all(out_dir: str | Path, seed: int = 42) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in SCENARIOS:
        p = out / f"{name}.json"
        p.write_text(json.dumps(generate(name, seed), indent=2, allow_nan=True))
        paths.append(p)
    return paths


# one-line description of every scenario (shown by the dashboards)
DESCRIPTIONS = {
    "normal": "All metrics within range.", "link_congestion": "High utilization, queue drops, latency.",
    "weak_wifi": "Poor RSSI and retransmissions on one AP.", "interface_fault": "CRC errors and link flaps.",
    "dns_failure": "DNS failing on three APs; network path healthy.", "dhcp_failure": "DHCP failing on one AP.",
    "hardware_failure": "Critical device: agents disagree, conflict resolved.",
    "device_overload": "CPU/memory exhausted on a core switch.",
    "multi_fault": "Two simultaneous, unrelated faults.", "trend_interface_errors": "Errors rising over time.",
    "latency_spike": "Latency with no corroboration: system should abstain.",
    "conflicting_evidence": "Congestion-like and interface-like symptoms: challenge round.",
    "adversarial_agent": "Hardware failure + an adversarial performance agent claiming congestion: TrustGuard.",
    "insufficient_data": "Almost no metrics.", "malformed_input": "NaN, junk rows, out-of-range values.",
    "incompatible_schema_v0": "Legacy field names/units (seconds, fractions).",
    "incompatible_schema_v2": "Nested {value, unit} layout.", "unsupported_schema": "schema_version 3.0: rejected.",
}
