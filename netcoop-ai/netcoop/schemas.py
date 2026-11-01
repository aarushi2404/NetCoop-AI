"""Export machine-readable protocol artefacts and validate messages against the protocol."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from .orchestrator import Orchestrator
from .protocol import (METRICS, PAYLOAD_REQUIRED, PROTOCOL_VERSION, AgentCard, Envelope, Evidence,
                       Finding)
from .signals import ONSETS, THRESHOLDS


def export_schemas(out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    (out / "agent_cards").mkdir(parents=True, exist_ok=True)
    files = {
        "envelope.schema.json": Envelope.model_json_schema(),
        "finding.schema.json": Finding.model_json_schema(),
        "evidence.schema.json": Evidence.model_json_schema(),
        "agent_card.schema.json": AgentCard.model_json_schema(),
        "payload_requirements.json": {"protocol_version": PROTOCOL_VERSION, "required_payload_fields": PAYLOAD_REQUIRED},
        "metrics.json": {k: {"unit": u, "min": lo, "max": hi} for k, (u, lo, hi) in METRICS.items()},
        "signal_thresholds.json": {k: {"metric": m, "op": op, "threshold": t, "onset": ONSETS[k], "unit": u, "meaning": txt}
                                   for k, (m, op, t, u, txt) in THRESHOLDS.items()},
    }
    orch = Orchestrator()
    for name, agent in orch.bus.agents.items():
        if hasattr(agent, "card"):
            files[f"agent_cards/{name}.json"] = agent.card()
    paths = []
    for rel, doc in files.items():
        p = out / rel
        p.write_text(json.dumps(doc, indent=2))
        paths.append(p)
    return paths


def validate_file(path: str | Path) -> tuple[int, list[str]]:
    """Validate a JSON message or a JSONL message log. Returns (n_valid, errors)."""
    text = Path(path).read_text()
    docs: list = []
    try:
        data = json.loads(text)
        docs = data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        for i, line in enumerate(text.splitlines(), 1):
            if line.strip():
                try:
                    docs.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    return 0, [f"line {i}: not valid JSON ({exc.msg})"]
    ok, errors = 0, []
    for i, d in enumerate(docs, 1):
        try:
            Envelope.model_validate(d)
            ok += 1
        except ValidationError as exc:
            errors.append(f"message {i}: " + "; ".join(e["msg"] for e in exc.errors()))
    return ok, errors


def replay_log(path: str | Path) -> dict:
    """Deterministic replay: feed every logged orchestrator->agent request to fresh agents and check
    that each reply is identical to the logged one. Proves incidents are reproducible from the message log."""
    from .protocol import Envelope as Env
    orch = Orchestrator()
    log = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    matched = mismatched = skipped = 0
    details = []
    for i, m in enumerate(log[:-1]):
        nxt = log[i + 1]
        if m["sender"] != "orchestrator" or nxt["recipient"] != "orchestrator":
            continue
        if nxt["msg_type"] == "error" or m["recipient"] not in orch.bus.agents or m["recipient"] == "orchestrator":
            skipped += 1
            continue
        agent = orch.bus.agents[m["recipient"]]
        try:
            reply = agent.handle(Env.model_validate(m)).payload
        except Exception as exc:  # noqa: BLE001
            mismatched += 1
            details.append(f"msg {i + 1} ({m['msg_type']}): replay raised {exc}")
            continue
        same = json.dumps(reply, sort_keys=True, default=str) == json.dumps(nxt["payload"], sort_keys=True, default=str)
        matched += same
        if not same:
            mismatched += 1
            details.append(f"msg {i + 1} ({m['msg_type']} -> {m['recipient']}): reply differs from log")
    return {"requests_replayed": matched + mismatched, "identical_replies": matched, "mismatched": mismatched,
            "skipped": skipped, "deterministic": mismatched == 0, "details": details}
