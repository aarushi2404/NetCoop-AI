"""Input normalizer: turns heterogeneous telemetry into the canonical v1 schema.

Handles: differing field names, nested/flat layouts, units (s vs ms, fraction vs %,
kbps/Gbps vs Mbps), string values with unit suffixes, schema versions 0.x/1.x/2.x,
out-of-range / NaN / non-numeric values, records without a device, and multiple
samples per device (aggregated by median). Never raises on bad data: problems are
reported as structured `issues`; only an unusable input as a whole sets `fatal`.

Every canonical value keeps its provenance (input record index, field path, raw value,
converted value, aggregation), so ProofTrace can walk any piece of evidence back to the
exact bytes that produced it. Per-device `quality` flags mark telemetry that is stale,
self-contradictory or unstable, so the correlation agent can discount it.
"""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .protocol import CORE_METRICS, METRICS
from .signals import THRESHOLDS, derive_signals

SUPPORTED_DATA_MAJORS = (0, 1, 2)
STALE_AFTER_S = 30 * 60
HIGHER_IS_WORSE = ("latency_ms", "jitter_ms", "packet_loss_pct", "link_utilization_pct",
                   "cpu_utilization_pct", "memory_utilization_pct", "queue_drops", "interface_errors",
                   "link_flaps", "retransmission_pct", "dns_failure_pct", "dhcp_failure_pct")


def _is_rising(series: list[float], median: float) -> bool:
    """Monotone-ish, substantial increase whose latest value is well above the median."""
    first, last = series[0], series[-1]
    if last - first < 0.5 * max(abs(last), 1e-9) or last <= median * 1.3:
        return False
    ups = sum(1 for a, b in zip(series, series[1:]) if b > a)
    return ups >= len(series) - 2

DEVICE_KEYS = ("device_id", "deviceId", "devId", "device", "node", "host", "hostname")
TS_KEYS = ("timestamp", "ts", "time", "collected_at")
STATUS_KEYS = ("status", "state", "health")
CONTAINER_KEYS = ("metrics", "stats", "telemetry", "counters")
VERSION_KEYS = ("schema_version", "schemaVersion", "version")
OTHER_KNOWN = ("role", "parent", "incident_id", "interface", "site")
RECORD_LIST_KEYS = ("records", "data", "samples", "telemetry")

# alias -> (canonical metric, factor applied when the value carries no explicit unit)
ALIASES: dict[str, tuple[str, float]] = {m: (m, 1.0) for m in METRICS}
ALIASES.update({
    "latency": ("latency_ms", 1), "latency_s": ("latency_ms", 1000), "rtt_ms": ("latency_ms", 1),
    "rtt_s": ("latency_ms", 1000), "rtt": ("latency_ms", 1),
    "jitter": ("jitter_ms", 1), "jitter_s": ("jitter_ms", 1000),
    "loss": ("packet_loss_pct", 1), "loss_pct": ("packet_loss_pct", 1),
    "packet_loss": ("packet_loss_pct", 1), "pkt_loss_pct": ("packet_loss_pct", 1),
    "loss_fraction": ("packet_loss_pct", 100), "packet_loss_ratio": ("packet_loss_pct", 100),
    "throughput": ("throughput_mbps", 1), "throughput_kbps": ("throughput_mbps", 0.001),
    "throughput_gbps": ("throughput_mbps", 1000),
    "bandwidth": ("bandwidth_mbps", 1), "bw_mbps": ("bandwidth_mbps", 1),
    "bandwidth_kbps": ("bandwidth_mbps", 0.001), "bandwidth_gbps": ("bandwidth_mbps", 1000),
    "util": ("link_utilization_pct", 1), "util_pct": ("link_utilization_pct", 1),
    "utilization": ("link_utilization_pct", 1), "link_util": ("link_utilization_pct", 1),
    "link_utilization": ("link_utilization_pct", 1),
    "util_fraction": ("link_utilization_pct", 100),
    "link_utilization_fraction": ("link_utilization_pct", 100),
    "utilization_ratio": ("link_utilization_pct", 100),
    "cpu": ("cpu_utilization_pct", 1), "cpu_pct": ("cpu_utilization_pct", 1),
    "cpu_util": ("cpu_utilization_pct", 1), "cpu_fraction": ("cpu_utilization_pct", 100),
    "mem": ("memory_utilization_pct", 1), "mem_pct": ("memory_utilization_pct", 1),
    "memory_pct": ("memory_utilization_pct", 1), "memory_utilization": ("memory_utilization_pct", 1),
    "mem_fraction": ("memory_utilization_pct", 100),
    "drops": ("queue_drops", 1), "queue_drop_count": ("queue_drops", 1),
    "egress_drops": ("queue_drops", 1),
    "if_errors": ("interface_errors", 1), "crc_errors": ("interface_errors", 1),
    "interface_error_count": ("interface_errors", 1), "errors": ("interface_errors", 1),
    "flaps": ("link_flaps", 1),
    "rssi": ("wifi_rssi_dbm", 1), "rssi_dbm": ("wifi_rssi_dbm", 1),
    "signal_dbm": ("wifi_rssi_dbm", 1), "wifi_signal_dbm": ("wifi_rssi_dbm", 1),
    "retx_pct": ("retransmission_pct", 1), "retransmissions_pct": ("retransmission_pct", 1),
    "retransmit_pct": ("retransmission_pct", 1), "retx_fraction": ("retransmission_pct", 100),
    "dns_fail_pct": ("dns_failure_pct", 1), "dns_failure_rate_pct": ("dns_failure_pct", 1),
    "dhcp_fail_pct": ("dhcp_failure_pct", 1),
})

_KIND = {m: ("ms" if m.endswith("_ms") and "latency" in m or m == "jitter_ms" else None)
         for m in METRICS}
for _m, (_u, *_r) in METRICS.items():
    _KIND[_m] = {"ms": "ms", "%": "pct", "Mbps": "mbps", "dBm": "dbm"}.get(_u, "count")

UNIT_FACTORS: dict[str, dict[str, float]] = {
    "ms": {"ms": 1, "s": 1000, "sec": 1000, "us": 0.001, "µs": 0.001},
    "pct": {"%": 1, "pct": 1, "percent": 1, "fraction": 100, "ratio": 100},
    "mbps": {"mbps": 1, "kbps": 0.001, "gbps": 1000, "bps": 1e-6},
    "count": {"count": 1, "packets": 1, "errors": 1, "flaps": 1},
    "dbm": {"dbm": 1},
}

STATUS_MAP = {
    "healthy": "Healthy", "ok": "Healthy", "up": "Healthy", "normal": "Healthy", "green": "Healthy",
    "warning": "Warning", "warn": "Warning", "degraded": "Warning", "yellow": "Warning",
    "critical": "Critical", "crit": "Critical", "down": "Critical", "failed": "Critical",
    "red": "Critical",
}

_NUM_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([%a-zA-Zµ]*)\s*$")


@dataclass
class NormalizationResult:
    devices: dict[str, dict] = field(default_factory=dict)
    topology: dict[str, Any] = field(default_factory=lambda: {"devices": []})
    issues: list[dict] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    fatal: str | None = None
    # device -> metric -> {"value", "aggregation", "samples": [{record_index, path, raw, value, timestamp}]}
    provenance: dict[str, dict[str, dict]] = field(default_factory=dict)
    stale_devices: list[str] = field(default_factory=list)

    @property
    def completeness(self) -> float:
        if not self.devices:
            return 0.0
        return round(sum(d["completeness"] for d in self.devices.values()) / len(self.devices), 3)


def _issue(issues: list[dict], level: str, message: str, device_id: str | None = None,
           field_: str | None = None, idx: int | None = None) -> None:
    issues.append({"level": level, "device_id": device_id, "field": field_,
                   "record_index": idx, "message": message})


def _first(d: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _parse_version(v: Any) -> int | None:
    m = re.match(r"^\s*v?(\d+)", str(v))
    return int(m.group(1)) if m else None


def _coerce(canonical: str, raw: Any, alias_factor: float) -> tuple[float | None, str | None]:
    """Convert one raw metric value to canonical units. Returns (value, error)."""
    unit: str | None = None
    if isinstance(raw, dict):
        unit = raw.get("unit")
        raw = raw.get("value")
    if raw is None:
        return None, None  # simply missing
    if isinstance(raw, bool):
        return None, f"boolean is not a valid value ({raw!r})"
    if isinstance(raw, str):
        m = _NUM_RE.match(raw)
        if not m:
            return None, f"non-numeric value {raw!r}"
        raw = float(m.group(1))
        if m.group(2) and unit is None:
            unit = m.group(2)
    if not isinstance(raw, (int, float)) or math.isnan(raw) or math.isinf(raw):
        return None, f"invalid number {raw!r}"
    factor = alias_factor
    if unit is not None:
        table = UNIT_FACTORS[_KIND[canonical]]
        if unit.lower() not in table:
            return None, f"unknown unit '{unit}' for {canonical}"
        factor = table[unit.lower()]
    value = float(raw) * factor
    _, lo, hi = METRICS[canonical]
    if not lo <= value <= hi:
        return None, f"value {value:g} outside valid range [{lo:g}, {hi:g}] for {canonical}"
    return round(value, 4), None


def _norm_ts(v: Any) -> str | None:
    try:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return datetime.fromtimestamp(float(v), tz=timezone.utc).isoformat().replace("+00:00", "Z")
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00")).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _json_safe(v: Any) -> Any:
    """Raw values as they can be written to JSON (NaN/inf become strings)."""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return repr(v)
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    return v


def _normalize_record(raw: Any, idx: int, issues: list[dict], conversions: Counter,
                      inherited_version: Any) -> dict | None:
    if not isinstance(raw, dict):
        _issue(issues, "error", f"record is not an object (got {type(raw).__name__}); rejected", idx=idx)
        return None
    version = _first(raw, VERSION_KEYS)
    if version is None:
        version = inherited_version
    major = _parse_version(version) if version is not None else 0  # no version => legacy
    dev_id = _first(raw, DEVICE_KEYS)
    if major is None or major not in SUPPORTED_DATA_MAJORS:
        _issue(issues, "error",
               f"unsupported data schema_version '{version}' "
               f"(supported majors: {', '.join(map(str, SUPPORTED_DATA_MAJORS))}); record rejected",
               device_id=str(dev_id) if dev_id else None, idx=idx)
        return None
    if not dev_id or not isinstance(dev_id, str):
        _issue(issues, "error", "record has no usable device identifier; rejected", idx=idx)
        return None

    container, container_key = None, None
    for k in CONTAINER_KEYS:
        if isinstance(raw.get(k), dict):
            container, container_key = raw[k], k
            break
    if container is None:  # flat layout: metrics live next to the metadata
        reserved = set(DEVICE_KEYS + TS_KEYS + STATUS_KEYS + VERSION_KEYS + OTHER_KNOWN + CONTAINER_KEYS)
        container = {k: v for k, v in raw.items() if k not in reserved}

    metrics: dict[str, float] = {}
    sources: dict[str, dict] = {}
    for key, val in container.items():
        if key not in ALIASES:
            _issue(issues, "info", f"unknown field '{key}' ignored", dev_id, key, idx)
            continue
        canonical, factor = ALIASES[key]
        value, err = _coerce(canonical, val, factor)
        if err:
            _issue(issues, "warning", f"{err}; metric dropped", dev_id, key, idx)
            continue
        if value is None:
            continue
        if canonical in metrics:
            _issue(issues, "warning", f"duplicate metric {canonical} (from '{key}'); keeping first",
                   dev_id, key, idx)
            continue
        metrics[canonical] = value
        sources[canonical] = {"path": [container_key, key] if container_key else [key], "raw": _json_safe(val)}
        explicit_unit = isinstance(val, dict) and val.get("unit") is not None
        if key != canonical or factor != 1 or explicit_unit:
            unit = val.get("unit") if explicit_unit else None
            conversions[(key, canonical, factor if not explicit_unit else unit)] += 1

    if not metrics:
        _issue(issues, "warning", "record contains no usable metrics", dev_id, None, idx)

    raw_status = _first(raw, STATUS_KEYS)
    status_key = next((k for k in STATUS_KEYS if raw.get(k) is not None), None)
    status = STATUS_MAP.get(str(raw_status).strip().lower(), "Unknown") if raw_status is not None else "Unknown"
    if raw_status is not None and status == "Unknown":
        _issue(issues, "warning", f"unrecognised status '{raw_status}' treated as Unknown", dev_id, "status", idx)

    ts_raw = _first(raw, TS_KEYS)
    ts = _norm_ts(ts_raw) if ts_raw is not None else None
    if ts_raw is not None and ts is None:
        _issue(issues, "warning", f"unparseable timestamp {ts_raw!r}", dev_id, "timestamp", idx)
    return {"device_id": dev_id, "metrics": metrics, "status": status, "timestamp": ts,
            "role": raw.get("role"), "parent": raw.get("parent"), "record_index": idx, "sources": sources,
            "status_source": {"path": [status_key], "raw": _json_safe(raw_status)} if status_key else None}


def _normalize_topology(raw: Any, issues: list[dict]) -> dict:
    if raw is None:
        return {"devices": []}
    entries = raw.get("devices") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        _issue(issues, "warning", "topology is malformed (expected {'devices': [...]}); ignored")
        return {"devices": []}
    out, ids = [], set()
    for e in entries:
        did = _first(e, ("id", "device_id")) if isinstance(e, dict) else None
        if not isinstance(did, str):
            _issue(issues, "warning", f"topology entry without id ignored: {e!r}")
            continue
        ids.add(did)
        out.append({"id": did, "role": e.get("role"), "parent": e.get("parent")})
    for e in out:
        if e["parent"] is not None and e["parent"] not in ids:
            _issue(issues, "warning", f"topology parent '{e['parent']}' of {e['id']} is not a known device; "
                   "treated as no parent", e["id"])
            e["parent"] = None
    return {"devices": out}


def _quality_flags(did: str, samples: list[dict], merged: dict, status: str, trends: dict,
                   issues: list[dict]) -> list[dict]:
    """Detect telemetry that is internally inconsistent or too unstable to trust at face value."""
    flags: list[dict] = []

    def flag(code: str, message: str, metric: str | None = None) -> None:
        flags.append({"code": code, "metric": metric, "message": message})
        _issue(issues, "warning", message, did, metric)

    present, _ = derive_signals(merged, status)
    alarms = present - {"device_critical"}
    if status == "Healthy" and len(alarms) >= 2:
        flag("status_contradiction", f"device reports Healthy but {len(alarms)} metrics are past alarm "
             f"thresholds ({', '.join(sorted(alarms))})")
    if status == "Critical" and not alarms:
        flag("status_contradiction", "device reports Critical but every reported metric is within normal range")
    thr, bw = merged.get("throughput_mbps"), merged.get("bandwidth_mbps")
    if thr is not None and bw and thr > bw * 1.05:
        flag("inconsistent_metrics", f"throughput {thr:g} Mbps exceeds link bandwidth {bw:g} Mbps", "throughput_mbps")
    for sig, (metric, op, t, unit, _) in THRESHOLDS.items():
        series = [s["metrics"][metric] for s in samples if metric in s["metrics"]]
        if len(series) < 3 or metric in trends:
            continue   # a rising trend is a real change, not instability
        above = sum(1 for v in series if (v >= t if op == ">=" else v <= t))
        if 0 < above < len(series) and min(above, len(series) - above) >= max(1, round(len(series) * 0.3)):
            flag("unstable_metric", f"{metric} straddles its alarm threshold ({op} {t:g} {unit}): "
                 f"{above}/{len(series)} samples past it", metric)
    by_ts: dict[str, dict] = {}
    for s in samples:
        if not s["timestamp"]:
            continue
        prev = by_ts.setdefault(s["timestamp"], s["metrics"])
        if prev is s["metrics"]:
            continue
        for m, v in s["metrics"].items():
            if m in prev and abs(prev[m] - v) > 0.1 * max(abs(prev[m]), abs(v), 1e-9):
                flag("conflicting_duplicates", f"two samples with the same timestamp {s['timestamp']} disagree "
                     f"on {m} ({prev[m]:g} vs {v:g})", m)
                break
    return flags


def normalize(raw: Any) -> NormalizationResult:
    res = NormalizationResult()
    issues = res.issues
    inherited_version = None
    topology_raw = None
    records: Any
    if isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict):
        topology_raw = raw.get("topology")
        inherited_version = _first(raw, VERSION_KEYS) if any(k in raw for k in RECORD_LIST_KEYS) else None
        records = next((raw[k] for k in RECORD_LIST_KEYS if isinstance(raw.get(k), list)), None)
        if records is None and _first(raw, DEVICE_KEYS):
            records = [raw]
    else:
        records = None
    if records is None:
        res.fatal = ("unrecognised input structure: expected a record list, an object with a "
                     "'records' list, or a single device record")
        _issue(issues, "error", res.fatal)
        res.stats = {"records_in": 0, "records_accepted": 0, "records_rejected": 0}
        return res

    res.topology = _normalize_topology(topology_raw, issues)
    conversions: Counter = Counter()
    versions: Counter = Counter()
    by_device: dict[str, list[dict]] = {}
    for i, r in enumerate(records):
        if isinstance(r, dict):
            v = _first(r, VERSION_KEYS) or inherited_version
            versions[str(v) if v is not None else "unversioned(legacy)"] += 1
        rec = _normalize_record(r, i, issues, conversions, inherited_version)
        if rec:
            by_device.setdefault(rec["device_id"], []).append(rec)

    for (src, canon, how), n in sorted(conversions.items(), key=str):
        if src == canon and isinstance(how, str):
            msg = f"converted '{canon}' from unit '{how}' to canonical unit ({n} values)"
        elif isinstance(how, str):
            msg = f"mapped '{src}' -> {canon} converting from unit '{how}' ({n} values)"
        elif how != 1:
            msg = f"mapped '{src}' -> {canon} with scale x{how:g} ({n} values)"
        else:
            msg = f"mapped field '{src}' -> {canon} ({n} values)"
        _issue(issues, "info", msg)

    # stale-sample filter: drop samples far older than the newest timestamp in the batch
    stamps = [x["timestamp"] for v in by_device.values() for x in v if x["timestamp"]]
    if stamps:
        newest = datetime.fromisoformat(max(stamps).replace("Z", "+00:00"))
        for did, samples in by_device.items():
            fresh = [x for x in samples if not x["timestamp"] or
                     (newest - datetime.fromisoformat(x["timestamp"].replace("Z", "+00:00"))).total_seconds()
                     <= STALE_AFTER_S]
            if not fresh:
                _issue(issues, "warning", f"all {len(samples)} sample(s) are stale (older than "
                       f"{STALE_AFTER_S // 60} min before the newest telemetry); device treated as silent", did)
                res.stale_devices.append(did)
                by_device[did] = fresh
            elif len(fresh) < len(samples):
                _issue(issues, "warning", f"{len(samples) - len(fresh)} stale sample(s) older than "
                       f"{STALE_AFTER_S // 60} min ignored", did)
                by_device[did] = fresh
        for did in res.stale_devices:
            del by_device[did]
    topo_parent = {d["id"]: d["parent"] for d in res.topology["devices"]}
    topo_role = {d["id"]: d["role"] for d in res.topology["devices"]}
    for did, samples in by_device.items():
        samples.sort(key=lambda s: s["timestamp"] or "")
        merged: dict[str, float] = {}
        prov: dict[str, dict] = {}
        for m in METRICS:
            vals = [s["metrics"][m] for s in samples if m in s["metrics"]]
            if vals:
                merged[m] = round(statistics.median(vals), 4)
                prov[m] = {"value": merged[m], "aggregation": f"median of {len(vals)} sample(s)",
                           "samples": [{"record_index": s["record_index"], "timestamp": s["timestamp"],
                                        **s["sources"][m], "value": s["metrics"][m]}
                                       for s in samples if m in s["metrics"]]}
        trends: dict[str, dict] = {}
        for m in HIGHER_IS_WORSE:
            series = [x["metrics"][m] for x in samples if m in x["metrics"]]
            if len(series) >= 4 and _is_rising(series, merged.get(m, 0)):
                trends[m] = {"first": series[0], "last": series[-1], "median": merged[m], "samples": len(series)}
                merged[m] = series[-1]  # act on the current value of a worsening metric, not its median
                prov[m].update(value=merged[m], aggregation=f"latest of {len(series)} samples (rising trend)")
                _issue(issues, "info", f"{m} is rising ({series[0]:g} -> {series[-1]:g} over "
                       f"{len(series)} samples); using latest value", did, m)
        known = [s["status"] for s in samples if s["status"] != "Unknown"]
        st_samples = [s for s in samples if s["status"] != "Unknown" and s["status_source"]]
        if st_samples:
            prov["status"] = {"value": st_samples[-1]["status"], "aggregation": "latest known status",
                              "samples": [{"record_index": s["record_index"], "timestamp": s["timestamp"],
                                           **s["status_source"], "value": s["status"]} for s in st_samples]}
        quality = _quality_flags(did, samples, merged, known[-1] if known else "Unknown", trends, issues)
        res.provenance[did] = prov
        present_core = sum(1 for m in CORE_METRICS if m in merged)
        res.devices[did] = {
            "metrics": merged,
            "status": known[-1] if known else "Unknown",
            "samples": len(samples),
            "role": topo_role.get(did) or samples[-1]["role"],
            "parent": topo_parent.get(did, samples[-1]["parent"]),
            "completeness": round(present_core / len(CORE_METRICS), 3),
            "trends": trends,
            "quality": quality,
        }
    accepted = sum(len(v) for v in by_device.values())
    res.stats = {
        "records_in": len(records), "records_accepted": accepted,
        "records_rejected": len(records) - accepted,
        "schema_versions_seen": dict(versions), "devices": len(res.devices),
    }
    if not res.devices:
        first = next((i["message"] for i in issues if i["level"] == "error"), None)
        res.fatal = "no valid telemetry records after validation" + (f" ({first})" if first else "")
        _issue(issues, "error", res.fatal)
    return res
