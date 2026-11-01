"""In-process message bus. Every hop is serialised to JSON and re-validated, so agents can
only communicate through valid protocol envelopes. All traffic is kept in `log`."""
from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .protocol import Envelope, make_envelope


class MessageBus:
    def __init__(self) -> None:
        self.agents: dict[str, Any] = {}
        self.log: list[dict] = []

    def register(self, agent: Any) -> None:
        self.agents[agent.name] = agent

    def _record(self, wire: str, note: str | None = None) -> None:
        entry = json.loads(wire)
        if note:
            entry["bus_note"] = note
        self.log.append(entry)

    def request(self, env: Envelope) -> Envelope:
        """Deliver `env` to its recipient and return the (validated) reply."""
        wire = env.model_dump_json()
        self._record(wire)
        parsed = Envelope.model_validate_json(wire)
        if parsed.recipient not in self.agents:
            raise LookupError(f"no agent registered as '{parsed.recipient}'")
        try:
            reply = self.agents[parsed.recipient].handle(parsed)
        except Exception as exc:  # recorded on the bus, re-raised for the orchestrator's recovery logic
            err = make_envelope(parsed.recipient, parsed.sender, "error",
                                {"error": str(exc), "in_reply_to": parsed.message_id}, parsed.correlation_id)
            self._record(err.model_dump_json())
            raise
        wire2 = reply.model_dump_json()
        self._record(wire2)
        return Envelope.model_validate_json(wire2)

    def deliver_raw(self, raw: dict) -> Envelope:
        """Entry point for externally produced messages: invalid ones get an `error` reply."""
        try:
            env = Envelope.model_validate(raw)
        except ValidationError as exc:
            msgs = "; ".join(e["msg"] for e in exc.errors())
            err = make_envelope("bus", str(raw.get("sender", "unknown")), "error",
                                {"error": f"invalid message rejected: {msgs}"},
                                str(raw.get("correlation_id", "n/a")))
            self._record(err.model_dump_json(), note="rejected")
            return err
        return self.request(env)

    def trace(self) -> list[str]:
        return [f"{m['sender']} -> {m['recipient']} [{m['msg_type']}]" for m in self.log]
