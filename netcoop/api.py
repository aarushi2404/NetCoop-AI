"""JSON API for the React web UI (stdlib only, no extra dependencies).

    python -m netcoop serve-api --port 8000        # API + built web UI (web/dist) on one port

Every endpoint is stateless and deterministic: the incident is regenerated from (source, name, seed) or taken
from the uploaded document, and the real multi-agent pipeline runs on every request. Nothing is cached or
pre-computed, so what the UI shows is what the engine produced.

  GET  /api/catalog                     scenarios + organizer incidents
  POST /api/diagnose   {incident}       report, ProofTrace, devices, topology, message log, agent cards
  POST /api/whatif     {incident, device, metric, value}
  POST /api/remediate  {incident, hypothesis?, efficacy?}
  POST /api/verify     {incident, tamper: none|raw|vote|drop|audit}
  GET  /api/benchmarks                  internal benchmark, organizer evaluation, interop demo

`incident` = {"source": "scenario"|"organizer"|"upload", "name", "seed", "raw", "faults", "remote",
              "trustguard": true|false, "simulation": true|false}.
A scenario's `simulation` block (e.g. the adversarial-agent demo) is applied unless "simulation": false.
"""
from __future__ import annotations

import copy
import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .generator import DESCRIPTIONS, SCENARIO_TRUTH, SCENARIOS, generate, simulation_faults
from .orchestrator import Orchestrator
from .prooftrace import verify_prooftrace
from .remediation import FIX, device_health, simulate_fix

ROOT = Path(__file__).resolve().parent.parent
ORG_DIR = ROOT / "data" / "organizer" / "incidents"
WEB_DIST = ROOT / "web" / "dist"
MAX_BODY = 5_000_000


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------------------------ incidents
def load_incident(spec: dict) -> tuple[Any, dict]:
    """Return (raw telemetry document, metadata shown in the UI)."""
    src = spec.get("source", "scenario")
    if src == "scenario":
        name = spec.get("name", "hardware_failure")
        if name not in SCENARIOS:
            raise ApiError(404, f"unknown scenario '{name}'")
        seed = int(spec.get("seed", 42))
        truth = SCENARIO_TRUTH.get(name)
        return generate(name, seed), {"source": "scenario", "name": name, "seed": seed,
                                      "description": DESCRIPTIONS.get(name, ""), "data_origin": "internal generator",
                                      "ground_truth": {"cause": truth[0], "devices": truth[1]} if truth else None}
    if src == "organizer":
        name = str(spec.get("name", ""))
        path = ORG_DIR / f"{name}.json"
        if not name or path.parent != ORG_DIR or not path.exists():
            raise ApiError(404, f"unknown organizer incident '{name}'")
        doc = json.loads(path.read_text())
        meta = {"source": "organizer", "name": name, "seed": None, "data_origin": "organizer notebook generator",
                "description": "Built with the organizer's mock-data notebook. The label is hidden from the agents.",
                "ground_truth": {"label": doc.get("label"), "faulty_device": doc.get("faulty_device")}}
        return {k: v for k, v in doc.items() if k not in ("label", "faulty_device")}, meta
    if src == "upload":
        if "raw" not in spec:
            raise ApiError(400, "upload needs a 'raw' telemetry document")
        return spec["raw"], {"source": "upload", "name": spec.get("name") or "uploaded.json", "seed": None,
                             "data_origin": "uploaded file", "description": "", "ground_truth": None}
    raise ApiError(400, f"unknown source '{src}'")


FAULT_MODES = ("transient", "permanent", "adversarial")


def _orchestrator(spec: dict, raw: Any = None, **kw) -> Orchestrator:
    faults = {a: m for a, m in (spec.get("faults") or {}).items() if m in FAULT_MODES}
    if spec.get("simulation", True):
        faults = {**simulation_faults(raw), **faults}
    return Orchestrator(inject_faults=faults, remote_connectivity=spec.get("remote") or None,
                        trustguard=bool(spec.get("trustguard", True)), **kw)


def _run(spec: dict) -> tuple[Any, dict, Orchestrator, dict]:
    raw, meta = load_incident(spec)
    orch = _orchestrator(spec, raw)
    rep = orch.run(raw)
    sim = simulation_faults(raw)
    meta["simulation"] = ({"faults": sim, "applied": bool(spec.get("simulation", True)),
                           "note": (raw.get("simulation") or {}).get("note")} if sim else None)
    meta["faults_applied"] = orch._faults
    return raw, meta, orch, rep


# ------------------------------------------------------------------------------------ endpoints
def catalog() -> dict:
    org = []
    if ORG_DIR.exists():
        for p in sorted(ORG_DIR.glob("*.json")):
            d = json.loads(p.read_text())
            org.append({"name": p.stem, "devices": len(d.get("devices", [])), "records": len(d.get("records", []))})
    return {"scenarios": [{"name": s, "description": DESCRIPTIONS.get(s, "")} for s in SCENARIOS],
            "organizer": org, "fixes": {h: a for h, (a, *_r) in FIX.items()},
            "agents": ["performance_agent", "infrastructure_agent", "connectivity_agent"],
            "fault_modes": list(FAULT_MODES)}


def diagnose(spec: dict) -> dict:
    raw, meta, orch, rep = _run(spec)
    trace = rep.pop("prooftrace", {})
    norm = orch.last_norm_result
    return {"incident": meta, "report": rep, "prooftrace": trace,
            "devices": norm.devices if norm else {}, "topology": norm.topology if norm else {"devices": []},
            "health": {d: device_health(v["metrics"], v["status"]) for d, v in (norm.devices if norm else {}).items()},
            "cards": orch.cards, "log": orch.bus.log}


def whatif(spec: dict) -> dict:
    raw, meta, orch, rep = _run(spec)
    device, metric = spec.get("device"), spec.get("metric")
    norm = orch.last_norm_result
    if not norm or device not in norm.devices:
        raise ApiError(400, f"unknown device '{device}'")
    n2 = copy.deepcopy(norm)
    before = n2.devices[device]["status"] if metric == "status" else n2.devices[device]["metrics"].get(metric)
    if metric == "status":
        n2.devices[device]["status"] = str(spec.get("value"))
    else:
        try:
            n2.devices[device]["metrics"][metric] = float(spec.get("value"))
        except (TypeError, ValueError):
            raise ApiError(400, "value must be a number")
    lost = {a: "permanent" for a, h in orch.health.items() if h["status"] in ("failed", "incompatible")}
    cfg = {**orch.config, "inject_faults": {**orch.config["inject_faults"], **lost}}
    after = Orchestrator(prooftrace=False, **cfg).run_normalized(n2, rep["incident_id"] + "-WHATIF")
    keep = ("status", "suspected_root_cause", "confidence", "root_cause_type", "leading_hypothesis",
            "root_cause_devices", "hypothesis_ranking")
    return {"device": device, "metric": metric, "from": before, "to": spec.get("value"),
            "before": {k: rep.get(k) for k in keep}, "after": {k: after.get(k) for k in keep},
            "changed": (after.get("leading_hypothesis") != rep.get("leading_hypothesis")
                        or after["status"] != rep["status"])}


def remediate(spec: dict) -> dict:
    raw, _, _, rep = _run(spec)
    hyp = spec.get("hypothesis") or None
    if hyp is not None and hyp not in FIX:
        raise ApiError(400, f"unknown hypothesis '{hyp}'")
    return simulate_fix(raw, rep, hypothesis=hyp, efficacy=float(spec.get("efficacy", 1.0)))


def verify(spec: dict) -> dict:
    raw, _, orch, rep = _run(spec)
    trace = rep.get("prooftrace") or {}
    raw2, log2 = copy.deepcopy(raw), copy.deepcopy(orch.bus.log)
    tamper, what = spec.get("tamper", "none"), "nothing changed"
    ev = trace.get("evidence") or []
    if tamper == "raw" and ev and ev[0]["raw_samples"]:
        s = ev[0]["raw_samples"][0]
        recs = raw2 if isinstance(raw2, list) else raw2["records"]
        node = recs[s["record_index"]]
        for k in s["path"][:-1]:
            node = node[k]
        old = node[s["path"][-1]]
        node[s["path"][-1]] = (old * 1.5 + 1) if isinstance(old, (int, float)) else "Healthy"
        what = f"input record #{s['record_index']} {'.'.join(map(str, s['path']))}: {old} -> {node[s['path'][-1]]}"
    elif tamper == "vote":
        m = next((x for x in log2 if x["msg_type"] == "finding_batch"
                  and any(f["votes"] for f in x["payload"]["findings"])), None)
        if m:
            f = next(f for f in m["payload"]["findings"] if f["votes"])
            k = next(iter(f["votes"]))
            old = f["votes"][k]
            f["votes"][k] = round(min(1.0, old + 0.3), 4)
            what = f"{m['sender']} vote for {k} on {f['device_id']} in message {m['message_id']}: {old} -> {f['votes'][k]}"
    elif tamper == "audit":
        m = next((x for x in log2 if x["msg_type"] == "audit_result"), None)
        if m and m["payload"]["audit"]["records"]:
            r = next((x for x in m["payload"]["audit"]["records"] if x["decision"] != "trusted"),
                     m["payload"]["audit"]["records"][0])
            old = r["decision"]
            r["decision"] = "trusted" if old != "trusted" else "flagged"
            what = f"TrustGuard record {r['record_id']} ({r['agent']} {r['subject']}) in message {m['message_id']}: " \
                   f"{old} -> {r['decision']}"
    elif tamper == "drop" and log2:
        gone = log2.pop(len(log2) // 2)
        what = f"deleted message {gone['message_id']} ({gone['msg_type']} {gone['sender']} -> {gone['recipient']})"
    res = verify_prooftrace(trace, raw2, log2)
    return {"tamper": tamper, "what": what, **res}


def benchmarks() -> dict:
    def load(p: Path):
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        d.pop("rows", None)
        for k in ("clean", "stressed"):
            if isinstance(d.get(k), dict):
                d[k].pop("rows", None)
        return d
    im = ROOT / "examples" / "interop_demo.md"
    return {"internal": load(ROOT / "benchmarks" / "benchmark.json"),
            "organizer": load(ROOT / "benchmarks" / "organizer" / "organizer_eval.json"),
            "interop_markdown": im.read_text() if im.exists() else None}


ROUTES = {("GET", "/api/catalog"): lambda b: catalog(), ("GET", "/api/benchmarks"): lambda b: benchmarks(),
          ("POST", "/api/diagnose"): diagnose, ("POST", "/api/whatif"): whatif,
          ("POST", "/api/remediate"): remediate, ("POST", "/api/verify"): verify}


# ------------------------------------------------------------------------------------ server
def make_server(port: int = 8000, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, data: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code: int, obj: Any) -> None:
            self._send(code, json.dumps(obj, default=str).encode())

        def _dispatch(self, method: str) -> None:
            path = self.path.split("?", 1)[0]
            fn = ROUTES.get((method, path))
            if fn is None:
                if method == "GET" and not path.startswith("/api/"):
                    return self._static(path)
                return self._json(404, {"error": f"no route {method} {path}"})
            try:
                body = {}
                if method == "POST":
                    n = int(self.headers.get("Content-Length", 0))
                    if n > MAX_BODY:
                        raise ApiError(413, "request too large")
                    body = json.loads(self.rfile.read(n) or b"{}")
                    if not isinstance(body, dict):
                        raise ApiError(400, "request body must be a JSON object")
                self._json(200, fn(body))
            except ApiError as exc:
                self._json(exc.status, {"error": str(exc)})
            except json.JSONDecodeError as exc:
                self._json(400, {"error": f"invalid JSON: {exc.msg}"})
            except Exception as exc:  # never leak a stack trace to the browser, but say what failed
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

        def _static(self, path: str) -> None:
            if not WEB_DIST.exists():
                return self._json(404, {"error": "web UI not built: run `npm run build` in web/"})
            f = (WEB_DIST / path.lstrip("/")).resolve()
            if not str(f).startswith(str(WEB_DIST.resolve())) or not f.is_file():
                f = WEB_DIST / "index.html"     # single-page app fallback
            self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")

        def do_GET(self):  # noqa: N802
            self._dispatch("GET")

        def do_POST(self):  # noqa: N802
            self._dispatch("POST")

        def log_message(self, *a):
            pass

    return ThreadingHTTPServer((host, port), Handler)


def start_in_thread() -> tuple[ThreadingHTTPServer, str]:
    srv = make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def serve(port: int = 8000, host: str = "0.0.0.0") -> None:
    srv = make_server(port, host=host)
    ui = "web UI + API" if WEB_DIST.exists() else "API only (build the UI with `npm run build` in web/)"
    print(f"NetCoop {ui} on http://{host}:{port}")
    srv.serve_forever()
