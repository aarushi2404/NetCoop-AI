"""NetCoop wire protocol v1.0: message envelope, finding schema, metric catalogue.

Every inter-agent message is a JSON `Envelope`. Payload shapes are documented in
docs/PROTOCOL.md. Messages are serialised to JSON and re-parsed on every hop
(see bus.py), so anything that is not valid protocol is rejected at the boundary.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PROTOCOL_VERSION = "1.0"
SUPPORTED_PROTOCOL_VERSIONS = ("1.0",)

HYPOTHESES = (
    "link_congestion",
    "interface_fault",
    "weak_wifi",
    "device_overload",
    "hardware_failure",
    "dns_failure",
    "dhcp_failure",
)

MsgType = Literal[
    "capability_request",
    "capability_response",
    "analyze_request",
    "finding_batch",
    "challenge_request",
    "challenge_response",
    "correlate_request",
    "diagnosis",
    "verify_request",
    "verification_result",
    "report_request",
    "report",
    "audit_request",
    "audit_result",
    "error",
]

# canonical metric -> (unit, min, max). Single source of truth for units and ranges.
METRICS: dict[str, tuple[str, float, float]] = {
    "latency_ms": ("ms", 0, 600_000),
    "jitter_ms": ("ms", 0, 600_000),
    "packet_loss_pct": ("%", 0, 100),
    "throughput_mbps": ("Mbps", 0, 1e7),
    "bandwidth_mbps": ("Mbps", 0, 1e7),
    "link_utilization_pct": ("%", 0, 100),
    "cpu_utilization_pct": ("%", 0, 100),
    "memory_utilization_pct": ("%", 0, 100),
    "queue_drops": ("packets/interval", 0, 1e12),
    "interface_errors": ("errors/interval", 0, 1e12),
    "link_flaps": ("count/interval", 0, 1e9),
    "wifi_rssi_dbm": ("dBm", -120, 0),
    "retransmission_pct": ("%", 0, 100),
    "dns_failure_pct": ("%", 0, 100),
    "dhcp_failure_pct": ("%", 0, 100),
}

# metrics every device is expected to report (used for completeness scoring)
CORE_METRICS = (
    "latency_ms",
    "jitter_ms",
    "packet_loss_pct",
    "link_utilization_pct",
    "cpu_utilization_pct",
    "queue_drops",
    "interface_errors",
)


# required payload keys per message type: enforced at the protocol boundary
PAYLOAD_REQUIRED: dict[str, tuple[str, ...]] = {
    "capability_request": (),
    "capability_response": ("agent", "protocol_versions", "accepts", "produces"),
    "analyze_request": ("devices",),
    "finding_batch": ("agent", "domain", "findings"),
    "challenge_request": ("device_id", "signals", "devices"),
    "challenge_response": ("agent", "answers"),
    "correlate_request": ("devices", "batches"),
    "diagnosis": ("status",),
    "verify_request": ("diagnosis", "devices"),
    "verification_result": ("status", "confidence"),
    "report_request": ("meta",),
    "report": ("status", "suspected_root_cause"),
    "audit_request": ("devices", "batches"),
    "audit_result": ("audit", "audited_batches"),
    "error": ("error",),
}


class ProtocolError(Exception):
    """Raised when a message violates the protocol (bad version, bad shape)."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Envelope(BaseModel):
    protocol: Literal["netcoop"] = "netcoop"
    schema_version: str = PROTOCOL_VERSION
    message_id: str
    correlation_id: str
    sender: str = Field(min_length=1)
    recipient: str = Field(min_length=1)
    msg_type: MsgType
    timestamp: str = Field(default_factory=now_iso)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _version_supported(cls, v: str) -> str:
        if v not in SUPPORTED_PROTOCOL_VERSIONS:
            raise ValueError(
                f"unsupported protocol schema_version '{v}' "
                f"(supported: {', '.join(SUPPORTED_PROTOCOL_VERSIONS)})"
            )
        return v


    @model_validator(mode="after")
    def _payload_shape(self) -> "Envelope":
        missing = [k for k in PAYLOAD_REQUIRED[self.msg_type] if k not in self.payload]
        if missing:
            raise ValueError(f"payload of '{self.msg_type}' is missing required field(s): {', '.join(missing)}")
        if self.msg_type == "finding_batch":
            for f in self.payload["findings"]:
                Finding.model_validate(f)   # every finding must itself conform
        return self


def make_envelope(sender: str, recipient: str, msg_type: str, payload: dict,
                  correlation_id: str) -> Envelope:
    return Envelope(
        message_id=uuid.uuid4().hex[:12],
        correlation_id=correlation_id,
        sender=sender,
        recipient=recipient,
        msg_type=msg_type,  # type: ignore[arg-type]
        payload=payload,
    )


class Evidence(BaseModel):
    metric: str
    value: float | str | None = None
    device_id: str | None = None
    unit: str | None = None
    threshold: str | None = None
    strength: float | None = Field(default=None, ge=0.0, le=1.0)
    interpretation: str


class Finding(BaseModel):
    """One agent's view of one device. `votes` maps hypothesis -> support in [0, 1]."""

    finding_id: str
    agent: str
    domain: Literal["performance", "infrastructure", "connectivity"]
    device_id: str
    votes: dict[str, float] = Field(default_factory=dict)
    signals_present: list[str] = Field(default_factory=list)
    signals_unknown: list[str] = Field(default_factory=list)
    signal_strength: dict[str, float] = Field(default_factory=dict)   # graded strength of known signals
    evidence: list[Evidence] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("votes")
    @classmethod
    def _votes_valid(cls, v: dict[str, float]) -> dict[str, float]:
        for h, s in v.items():
            if h not in HYPOTHESES:
                raise ValueError(f"unknown hypothesis '{h}'")
            if not 0.0 <= s <= 1.0:
                raise ValueError(f"vote for '{h}' out of range [0,1]: {s}")
        return v

    @field_validator("signal_strength")
    @classmethod
    def _strength_valid(cls, v: dict[str, float]) -> dict[str, float]:
        for sig, s in v.items():
            if not 0.0 <= s <= 1.0:
                raise ValueError(f"signal strength for '{sig}' out of range [0,1]: {s}")
        return v


class AgentCard(BaseModel):
    """Self-description an agent publishes so peers can discover what it does (capability discovery)."""
    agent: str
    description: str
    domain: str | None = None
    version: str = "1.0"
    protocol_versions: list[str]
    accepts: list[str]
    produces: list[str]
    hypotheses: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    transport: Literal["in-process", "http"] = "in-process"
    negotiation: dict[str, Any] | None = None   # set by adapters for foreign agents (format negotiation)
