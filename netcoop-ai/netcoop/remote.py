"""A *foreign* agent: an independent HTTP service with its own (legacy) data model, plus the
adapter that lets it take part in a NetCoop diagnosis.

The foreign service ("WirelessOps analyzer") knows nothing about NetCoop envelopes. It speaks its own
format family `wlo-N`:

  GET  /about     -> {"name", "vendor", "formats": ["wlo-1"], "causes": [...], "observes": [...]}
  POST /analyze   {"format": "wlo-1", "hosts": [{"name", "rssi", "retry_rate", "dns_fail_ratio", "dhcp_fail_ratio"}]}
                  -> {"format": "wlo-1", "results": [{"host", "hints": [{"cause", "strength", "facts"}], "observed": [tags]}]}

with fractions instead of percentages, its own field names and its own cause vocabulary (WEAK_WIRELESS /
DNS_OUTAGE / DHCP_OUTAGE, plus CO_CHANNEL_INTERFERENCE, which NetCoop has no hypothesis for).

`RemoteConnectivityAgent` is the protocol-side adapter. It
  1. discovers the service (GET /about), validates the descriptor and negotiates a format both sides
     support. No common format -> the agent advertises no protocol version and the orchestrator marks it
     `incompatible` with the reason, instead of failing mid-diagnosis;
  2. builds its NetCoop Agent Card from what the service actually advertises (mapped causes -> hypotheses);
  3. translates requests canonical -> wlo, validates every reply item (types, ranges, known hosts,
     known vocabulary), drops invalid items with a note, rejects replies that are not wlo at all;
  4. translates accepted items into protocol-conformant findings, recording the SHA-256 of the raw reply
     so ProofTrace can cite exactly what the remote said.

    python -m netcoop serve-remote --port 8765 [--mode ok|incompatible|malformed|partial|slow|flaky]
    python -m netcoop run data/scenarios/weak_wifi.json --remote-connectivity http://127.0.0.1:8765
    python -m netcoop interop-demo
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .agents import ConnectivityAgent, noisy_or
from .protocol import Envelope, Evidence, Finding
from .signals import derive_signals

ADAPTER_FORMATS = ("wlo-1",)          # foreign formats this adapter can translate
CAUSE_TO_HYPOTHESIS = {"WEAK_WIRELESS": "weak_wifi", "DNS_OUTAGE": "dns_failure", "DHCP_OUTAGE": "dhcp_failure"}
TAG_TO_SIGNAL = {"LOW_RSSI": "weak_signal", "HIGH_RETRY": "retransmissions",
                 "DNS_FAIL": "dns_failures", "DHCP_FAIL": "dhcp_failures"}
TAG_TO_EVIDENCE = {
    "LOW_RSSI": ("wifi_rssi_dbm", "rssi", 1, "Weak Wi-Fi signal strength (remote analyzer)"),
    "HIGH_RETRY": ("retransmission_pct", "retry_rate", 100, "High wireless retransmission rate (remote analyzer)"),
    "DNS_FAIL": ("dns_failure_pct", "dns_fail_ratio", 100, "High DNS failure rate (remote analyzer)"),
    "DHCP_FAIL": ("dhcp_failure_pct", "dhcp_fail_ratio", 100, "High DHCP failure rate (remote analyzer)"),
}
SERVER_MODES = ("ok", "incompatible", "malformed", "partial", "slow", "flaky")


class NegotiationError(Exception):
    """The remote service is reachable but cannot be used (bad descriptor or no common format)."""


# ----------------------------------------------------------------------------- foreign service
def legacy_analyze(hosts: list[dict]) -> list[dict]:
    """The foreign analyzer's own logic and vocabulary."""
    results = []
    for h in hosts:
        hints, observed = [], []
        rssi, retry = h.get("rssi"), h.get("retry_rate")
        ws = []
        if rssi is not None and rssi <= -75:
            observed.append("LOW_RSSI"); ws.append(0.55)
        if retry is not None and retry >= 0.15:
            observed.append("HIGH_RETRY"); ws.append(0.5)
        if ws:
            hints.append({"cause": "WEAK_WIRELESS", "strength": noisy_or(ws),
                          "facts": {"rssi": rssi, "retry_rate": retry}})
        if retry is not None and retry >= 0.15 and (rssi is None or rssi > -75):
            hints.append({"cause": "CO_CHANNEL_INTERFERENCE", "strength": 0.4, "facts": {"retry_rate": retry}})
        if (h.get("dns_fail_ratio") or 0) >= 0.2:
            observed.append("DNS_FAIL")
            hints.append({"cause": "DNS_OUTAGE", "strength": 0.85, "facts": {"dns_fail_ratio": h["dns_fail_ratio"]}})
        if (h.get("dhcp_fail_ratio") or 0) >= 0.2:
            observed.append("DHCP_FAIL")
            hints.append({"cause": "DHCP_OUTAGE", "strength": 0.85, "facts": {"dhcp_fail_ratio": h["dhcp_fail_ratio"]}})
        results.append({"host": h["name"], "hints": hints, "observed": observed})
    return results


def make_server(port: int = 0, mode: str = "ok") -> ThreadingHTTPServer:
    """mode: ok | incompatible (only speaks wlo-2) | malformed (garbage body) | partial (some invalid
    items) | slow (answers after 5 s) | flaky (first /analyze call fails with 503)."""
    if mode not in SERVER_MODES:
        raise ValueError(f"unknown mode {mode!r}; choose from {SERVER_MODES}")
    formats = ["wlo-2"] if mode == "incompatible" else ["wlo-1"]
    state = {"analyze_calls": 0}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict | str) -> None:
            data = (body if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            if self.path == "/about":
                self._send(200, {"name": "WirelessOps analyzer", "vendor": "WirelessOps", "formats": formats,
                                 "endpoints": ["GET /about", "POST /analyze"],
                                 "causes": [*CAUSE_TO_HYPOTHESIS, "CO_CHANNEL_INTERFERENCE"],
                                 "observes": list(TAG_TO_SIGNAL)})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path != "/analyze":
                return self._send(404, {"error": "not found"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                hosts = body["hosts"]
                assert isinstance(hosts, list)
            except (json.JSONDecodeError, KeyError, AssertionError):
                return self._send(422, {"error": "expected {'format': ..., 'hosts': [...]}"})
            if body.get("format") not in formats:
                return self._send(415, {"error": f"unsupported format {body.get('format')!r}", "formats": formats})
            state["analyze_calls"] += 1
            if mode == "flaky" and state["analyze_calls"] == 1:
                return self._send(503, {"error": "warming up"})
            if mode == "slow":
                time.sleep(5)
            if mode == "malformed":
                return self._send(200, "<<not json>>")
            results = legacy_analyze(hosts)
            if mode == "partial" and results:
                results[0]["hints"].append({"cause": "WEAK_WIRELESS", "strength": 7})         # out of range
                results[0]["observed"].append("SOLAR_FLARE")                                   # unknown tag
                results.append({"host": "NOT_A_REQUESTED_HOST", "hints": [], "observed": []})  # unknown host
                results.append("garbage")                                                      # not an object
            self._send(200, {"format": body["format"], "results": results})

        def log_message(self, *a):  # silence default logging
            pass

    class Server(ThreadingHTTPServer):
        def handle_error(self, request, client_address):  # client gave up (e.g. timeout): not our problem
            pass

    return Server(("127.0.0.1", port), Handler)


def start_in_thread(mode: str = "ok") -> tuple[ThreadingHTTPServer, str]:
    srv = make_server(0, mode)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def serve(port: int = 8765, mode: str = "ok") -> None:
    srv = make_server(port, mode)
    print(f"WirelessOps analyzer (foreign agent, mode={mode}) listening on http://127.0.0.1:{port}  "
          "[GET /about, POST /analyze]")
    srv.serve_forever()


# ----------------------------------------------------------------------------- validation
def validate_descriptor(desc: object) -> dict:
    if not isinstance(desc, dict):
        raise NegotiationError("descriptor is not a JSON object")
    problems = [f"'{k}' must be a list of strings" for k in ("formats", "causes")
                if not (isinstance(desc.get(k), list) and all(isinstance(x, str) for x in desc[k]))]
    if not isinstance(desc.get("name"), str):
        problems.append("'name' must be a string")
    if problems:
        raise NegotiationError("invalid descriptor: " + "; ".join(problems))
    return desc


def validate_results(resp: object, requested: set[str]) -> tuple[dict[str, dict], list[str]]:
    """Strictly validate a wlo-1 reply. Returns (accepted results by host, problems). Raises ValueError if
    the reply is not a wlo reply at all."""
    if not isinstance(resp, dict) or not isinstance(resp.get("results"), list):
        raise ValueError("remote agent response missing 'results' list")
    accepted, problems = {}, []
    for i, r in enumerate(resp["results"]):
        if not isinstance(r, dict) or not isinstance(r.get("host"), str):
            problems.append(f"result #{i} rejected: not an object with a 'host' string")
            continue
        if r["host"] not in requested:
            problems.append(f"result for unrequested host '{r['host']}' rejected")
            continue
        hints, observed = [], []
        for h in r.get("hints", []) if isinstance(r.get("hints"), list) else []:
            s = h.get("strength") if isinstance(h, dict) else None
            if not (isinstance(s, (int, float)) and not isinstance(s, bool) and 0 <= s <= 1):
                problems.append(f"{r['host']}: hint {h!r} rejected (strength must be a number in [0, 1])")
                continue
            if h.get("cause") not in CAUSE_TO_HYPOTHESIS:
                problems.append(f"{r['host']}: cause '{h.get('cause')}' has no NetCoop hypothesis; ignored")
                continue
            hints.append(h)
        for t in r.get("observed", []) if isinstance(r.get("observed"), list) else []:
            (observed.append(t) if t in TAG_TO_SIGNAL else problems.append(f"{r['host']}: unknown tag {t!r} ignored"))
        accepted[r["host"]] = {"hints": hints, "observed": observed}
    return accepted, problems


# ----------------------------------------------------------------------------- adapter
class RemoteConnectivityAgent(ConnectivityAgent):
    """Protocol-side adapter: drop-in replacement for the local connectivity agent."""

    description = "Remote WirelessOps analyzer (HTTP, wlo format) behind a protocol adapter; topology scope stays local."

    def __init__(self, url: str, fault: str | None = None, timeout: float = 3.0):
        super().__init__(fault)
        self.url, self.timeout = url.rstrip("/"), timeout
        self.negotiation: dict | None = None

    # -- transport
    def _http(self, method: str, path: str, body: dict | None = None) -> tuple[object, str]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"remote agent returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise RuntimeError(f"remote agent unreachable or timed out at {self.url}: {exc}") from exc
        try:
            return json.loads(raw), hashlib.sha256(raw).hexdigest()
        except json.JSONDecodeError as exc:
            raise ValueError("remote agent returned malformed JSON") from exc

    def _post(self, path: str, body: dict) -> dict:  # kept for backwards compatibility
        return self._http("POST", path, body)[0]

    # -- discovery + negotiation
    def negotiate(self) -> dict:
        desc = validate_descriptor(self._http("GET", "/about")[0])
        common = [f for f in ADAPTER_FORMATS if f in desc["formats"]]
        mapped = sorted({CAUSE_TO_HYPOTHESIS[c] for c in desc["causes"] if c in CAUSE_TO_HYPOTHESIS})
        self.negotiation = {
            "remote": {k: desc.get(k) for k in ("name", "vendor", "formats", "causes", "observes")},
            "adapter_formats": list(ADAPTER_FORMATS), "format": common[-1] if common else None,
            "status": "compatible" if common and mapped else "incompatible",
            "mapped_hypotheses": mapped,
            "unmapped_causes": [c for c in desc["causes"] if c not in CAUSE_TO_HYPOTHESIS],
            "reason": None if common and mapped else (
                f"no common format: remote speaks {desc['formats']}, adapter speaks {list(ADAPTER_FORMATS)}"
                if not common else "remote advertises no cause NetCoop can use")}
        return self.negotiation

    def card(self) -> dict:
        neg = self.negotiate()   # raises when unreachable -> orchestrator treats the agent as unavailable
        base = super().card() | {"transport": "http", "description": self.description + f" [{self.url}]",
                                 "negotiation": neg}
        if neg["status"] != "compatible":
            return base | {"protocol_versions": [], "hypotheses": []}
        return base | {"hypotheses": neg["mapped_hypotheses"],
                       "signals": sorted({TAG_TO_SIGNAL[t] for t in neg["remote"].get("observes") or []
                                          if t in TAG_TO_SIGNAL})}

    # -- work
    def _handle(self, env: Envelope) -> Envelope:
        if env.msg_type != "analyze_request":
            return super()._handle(env)           # challenges are answered from local data
        if not self.negotiation or self.negotiation["status"] != "compatible":
            self.negotiate()
            if self.negotiation["status"] != "compatible":
                raise NegotiationError(self.negotiation["reason"])
        devices = env.payload["devices"]
        hosts = []
        for did, dev in devices.items():          # canonical -> wlo-1
            m = dev["metrics"]
            host = {"name": did}
            if "wifi_rssi_dbm" in m: host["rssi"] = m["wifi_rssi_dbm"]
            if "retransmission_pct" in m: host["retry_rate"] = round(m["retransmission_pct"] / 100, 4)
            if "dns_failure_pct" in m: host["dns_fail_ratio"] = round(m["dns_failure_pct"] / 100, 4)
            if "dhcp_failure_pct" in m: host["dhcp_fail_ratio"] = round(m["dhcp_failure_pct"] / 100, 4)
            hosts.append(host)
        resp, digest = self._http("POST", "/analyze", {"format": self.negotiation["format"], "hosts": hosts})
        by_host, problems = validate_results(resp, set(devices))

        findings = []
        for did, dev in devices.items():          # wlo-1 -> protocol
            r = by_host.get(did)
            _, unknown = derive_signals(dev["metrics"], dev["status"], self.domain)
            notes = ["analysed by remote agent over HTTP"]
            if r is None:
                r = {"hints": [], "observed": []}
                notes.append("remote returned no valid result for this device; no remote evidence used")
            votes = {}
            for hint in r["hints"]:
                hyp = CAUSE_TO_HYPOTHESIS[hint["cause"]]
                votes[hyp] = max(votes.get(hyp, 0.0), float(hint["strength"]))
            present = sorted({TAG_TO_SIGNAL[t] for t in r["observed"]})
            # what the remote could judge (metric sent) but did not flag counts as measured-and-absent
            strength = {TAG_TO_SIGNAL[t]: 0.0 for t, (metric, *_x) in TAG_TO_EVIDENCE.items()
                        if metric in dev["metrics"]} | {s: 1.0 for s in present}
            evidence = []
            for tag in r["observed"]:
                metric, _, _, text = TAG_TO_EVIDENCE[tag]
                evidence.append(Evidence(metric=metric, value=dev["metrics"].get(metric), device_id=did,
                                         strength=1.0, interpretation=text))
            findings.append(Finding(
                finding_id=f"{self.name}:{did}", agent=self.name, domain="connectivity", device_id=did,
                votes=votes, signals_present=present, signals_unknown=sorted(unknown), signal_strength=strength,
                evidence=evidence, notes=notes).model_dump())
        payload = {"agent": self.name, "domain": self.domain, "findings": findings,
                   **self.extra(devices, env.payload.get("topology", {})), "remote": self.url,
                   "remote_format": self.negotiation["format"], "remote_response_sha256": digest,
                   "remote_validation": {"accepted_results": len(by_host), "problems": problems}}
        return self._reply(env, "finding_batch", payload)


def interop_demo() -> list[dict]:
    """Run the same incident against foreign agents in every failure mode; returns one row per case."""
    from .generator import generate
    from .orchestrator import Orchestrator
    cases = [("compatible service", "ok", None), ("only speaks wlo-2 (no common format)", "incompatible", None),
             ("returns non-JSON garbage", "malformed", None), ("some reply items invalid", "partial", None),
             ("first call 503, then ok", "flaky", None), ("too slow (5 s > 1 s timeout)", "slow", 1.0),
             ("service down", None, None)]
    rows = []
    for label, mode, timeout in cases:
        srv = None
        if mode:
            srv, url = start_in_thread(mode)
        else:
            url = "http://127.0.0.1:9"
        try:
            orch = Orchestrator(remote_connectivity=url)
            if timeout:
                orch.bus.agents["connectivity_agent"].timeout = timeout
            rep = orch.run(generate("weak_wifi"))
            agent = orch.bus.agents["connectivity_agent"]
            batch = next((m["payload"] for m in orch.bus.log if m["msg_type"] == "finding_batch"
                          and m["sender"] == "connectivity_agent"), {})
            contrib = next((a.get("leave_one_out", {}).get("contribution") for a in rep["prooftrace"].get("agents", [])
                            if a["agent"] == "connectivity_agent"), None)
            h = rep["agent_health"].get("connectivity_agent", {})
            rows.append({"case": label, "negotiation": (agent.negotiation or {}).get("status", "unreachable"),
                         "format": (agent.negotiation or {}).get("format"),
                         "agent_health": h.get("status"), "error": h.get("error"),
                         "validation_problems": len(batch.get("remote_validation", {}).get("problems", [])),
                         "status": rep["status"], "cause": rep.get("root_cause_type"),
                         "confidence": rep["confidence"], "remote_contribution": contrib,
                         "prooftrace_verified": rep["prooftrace"]["checks"]["verified"]})
        finally:
            if srv:
                srv.shutdown()
    return rows
