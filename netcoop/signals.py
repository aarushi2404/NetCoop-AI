"""Symptom signals: named, thresholded observations derived from canonical metrics.

Thresholds are deliberately simple and documented so that every diagnosis can be
traced back to a concrete comparison ("link_utilization_pct >= 85").
A signal is `present`, `absent` (metric known, threshold not met) or `unknown`
(metric missing). Missing data is never treated as zero.

Besides the binary alarm threshold every signal has a documented *onset* (warning level). Between onset
and threshold the signal is graded: strength = (value - onset) / (threshold - onset), so CPU at 89 %
counts as 0.95 of a saturated CPU instead of "absent". Onsets are standard operational warning levels
(e.g. CPU 70 %, RSSI -67 dBm), set from domain practice, not fitted to the benchmark.
"""
from __future__ import annotations

import operator

from .protocol import METRICS, Evidence

_OPS = {">=": operator.ge, "<=": operator.le}

# signal -> (metric, op, threshold, unit, interpretation)
THRESHOLDS: dict[str, tuple[str, str, float, str, str]] = {
    "high_latency": ("latency_ms", ">=", 100, "ms", "High network latency"),
    "high_jitter": ("jitter_ms", ">=", 30, "ms", "High jitter"),
    "packet_loss": ("packet_loss_pct", ">=", 1.0, "%", "Packet loss above tolerance"),
    "high_utilization": ("link_utilization_pct", ">=", 85, "%", "High link utilization"),
    "queue_drops": ("queue_drops", ">=", 100, "packets", "Elevated egress queue drops"),
    "interface_errors": ("interface_errors", ">=", 50, "errors", "Elevated interface errors"),
    "link_flaps": ("link_flaps", ">=", 3, "flaps", "Unstable link (flapping)"),
    "high_cpu": ("cpu_utilization_pct", ">=", 90, "%", "Device CPU saturated"),
    "high_memory": ("memory_utilization_pct", ">=", 90, "%", "Device memory nearly exhausted"),
    "weak_signal": ("wifi_rssi_dbm", "<=", -75, "dBm", "Weak Wi-Fi signal strength"),
    "retransmissions": ("retransmission_pct", ">=", 15, "%", "High wireless retransmission rate"),
    "dns_failures": ("dns_failure_pct", ">=", 20, "%", "High DNS resolution failure rate"),
    "dhcp_failures": ("dhcp_failure_pct", ">=", 20, "%", "High DHCP failure rate"),
}

# signal -> warning onset (strength 0 at or below it, rising linearly to 1 at the alarm threshold)
ONSETS: dict[str, float] = {
    "high_latency": 50, "high_jitter": 15, "packet_loss": 0.5, "high_utilization": 70,
    "queue_drops": 20, "interface_errors": 10, "link_flaps": 1, "high_cpu": 70, "high_memory": 75,
    "weak_signal": -67, "retransmissions": 8, "dns_failures": 5, "dhcp_failures": 5,
}

DOMAIN_SIGNALS: dict[str, tuple[str, ...]] = {
    "performance": ("high_latency", "high_jitter", "packet_loss", "high_utilization"),
    "infrastructure": ("queue_drops", "interface_errors", "link_flaps", "high_cpu",
                       "high_memory", "device_critical"),
    "connectivity": ("weak_signal", "retransmissions", "dns_failures", "dhcp_failures"),
}

ALL_SIGNALS = tuple(s for sigs in DOMAIN_SIGNALS.values() for s in sigs)

BAD_STATUSES = ("Warning", "Critical")


def derive_signals(metrics: dict, status: str | None,
                   domain: str | None = None) -> tuple[set[str], set[str]]:
    """Return (present, unknown) signal sets, optionally restricted to one domain."""
    wanted = DOMAIN_SIGNALS[domain] if domain else ALL_SIGNALS
    present: set[str] = set()
    unknown: set[str] = set()
    for sig in wanted:
        if sig == "device_critical":
            if status == "Critical":
                present.add(sig)
            elif status in (None, "Unknown"):
                unknown.add(sig)
            continue
        metric, op, thr, *_ = THRESHOLDS[sig]
        val = metrics.get(metric)
        if val is None:
            unknown.add(sig)
        elif _OPS[op](val, thr):
            present.add(sig)
    return present, unknown


def graded(signal: str, metrics: dict, status: str | None) -> float | None:
    """Strength of one signal in [0, 1]; None when the metric (or status) is missing."""
    if signal == "device_critical":
        if status in (None, "Unknown"):
            return None
        return 1.0 if status == "Critical" else 0.0
    metric, op, thr, *_ = THRESHOLDS[signal]
    val = metrics.get(metric)
    if val is None:
        return None
    lo = ONSETS[signal]
    span = (thr - lo) if op == ">=" else (lo - thr)
    over = (val - lo) if op == ">=" else (lo - val)
    return round(max(0.0, min(1.0, over / span)), 3)


def derive_strengths(metrics: dict, status: str | None, domain: str | None = None) -> dict[str, float]:
    """Graded strength of every *known* signal (missing metrics are left out, never zero)."""
    wanted = DOMAIN_SIGNALS[domain] if domain else ALL_SIGNALS
    out = {}
    for sig in wanted:
        g = graded(sig, metrics, status)
        if g is not None:
            out[sig] = g
    return out


def is_degraded(dev: dict) -> bool:
    present, _ = derive_signals(dev["metrics"], dev.get("status"))
    return bool(present) or dev.get("status") in BAD_STATUSES


def evidence_for(signal: str, device_id: str, metrics: dict, status: str | None) -> Evidence:
    if signal == "device_critical":
        return Evidence(metric="status", value=status, device_id=device_id, strength=1.0,
                        interpretation="Device reports Critical status")
    metric, op, thr, unit, text = THRESHOLDS[signal]
    g = graded(signal, metrics, status)
    if g is not None and g < 1:
        text = f"{text}: elevated, {g:.0%} of the way from warning onset ({ONSETS[signal]:g}) to alarm"
    return Evidence(metric=metric, value=metrics.get(metric), device_id=device_id,
                    unit=METRICS[metric][0], threshold=f"{op} {thr:g} {unit}", strength=g,
                    interpretation=text)


def signal_strength(signal: str, metrics: dict, status: str | None) -> dict:
    """Graded view of one signal for the challenge round: value, threshold, onset, state and strength.
    Tells 'barely over' from 'far over' and 'just under' from 'nowhere near'."""
    g = graded(signal, metrics, status)
    if signal == "device_critical":
        return {"metric": "status", "value": status, "threshold": "== Critical", "onset": None,
                "state": "unknown" if g is None else ("present" if g == 1 else "absent"), "strength": g}
    metric, op, thr, unit, _ = THRESHOLDS[signal]
    val = metrics.get(metric)
    state = "unknown" if val is None else ("present" if _OPS[op](val, thr) else
                                           "elevated" if g and g > 0 else "absent")
    return {"metric": metric, "value": val, "threshold": f"{op} {thr:g} {unit}",
            "onset": f"{ONSETS[signal]:g} {unit}", "state": state, "strength": g}
