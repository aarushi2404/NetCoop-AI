"""CLI:  python -m netcoop {generate,run,demo,prooftrace,trustguard-demo,benchmark,...}"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agents import render_markdown
from .generator import SCENARIOS, generate, simulation_faults, write_all
from .orchestrator import Orchestrator


def _faults(items: list[str] | None) -> dict[str, str]:
    out = {}
    for it in items or []:
        agent, _, mode = it.partition(":")
        agent = agent if agent.endswith("_agent") or agent == "trustguard" else agent + "_agent"
        if mode not in ("transient", "permanent", "adversarial"):
            sys.exit(f"--inject-fault expects AGENT:transient|permanent|adversarial, got '{it}'")
        out[agent] = mode
    return out


def _orchestrator(a: argparse.Namespace) -> Orchestrator:
    """Faults from the command line, plus a demo scenario's own `simulation` block (announced on stderr)."""
    faults = _faults(a.inject_fault)
    if not a.no_simulation:
        try:
            sim = simulation_faults(json.loads(Path(a.input).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            sim = {}
        if sim:
            print("simulation from input file: " + ", ".join(f"{k}={v}" for k, v in sim.items())
                  + "  (disable with --no-simulation)", file=sys.stderr)
            faults = {**sim, **faults}
    return Orchestrator(inject_faults=faults, remote_connectivity=a.remote_connectivity,
                        trustguard=not a.no_trustguard)


def cmd_run(a: argparse.Namespace) -> int:
    orch = _orchestrator(a)
    rep = orch.run_file(a.input)
    if a.simulate_fix:
        from .remediation import simulate_fix
        rep["simulated_remediation"] = simulate_fix(json.loads(Path(a.input).read_text()), rep,
                                                    hypothesis=a.fix_hypothesis, efficacy=a.efficacy)
    if a.trace:
        print("--- agent message trace ---")
        for i, line in enumerate(orch.bus.trace(), 1):
            print(f"{i:>2}. {line}")
        print("---------------------------")
    if a.log:
        Path(a.log).parent.mkdir(parents=True, exist_ok=True)
        Path(a.log).write_text("\n".join(json.dumps(m) for m in orch.bus.log) + "\n")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(rep, indent=2))
    print(render_markdown(rep) if a.markdown else json.dumps(rep, indent=2))
    return 0 if rep["status"] != "error" else 2


def cmd_prooftrace(a: argparse.Namespace) -> int:
    """Diagnose and write the four artefacts a third party needs to check the result independently."""
    from .prooftrace import render_prooftrace_markdown
    orch = _orchestrator(a)
    rep = orch.run_file(a.input)
    trace = rep.pop("prooftrace", None) or {}
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(a.input).stem
    (out / f"{stem}.report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    (out / f"{stem}.prooftrace.json").write_text(json.dumps(trace, indent=2), encoding="utf-8")
    (out / f"{stem}.prooftrace.md").write_text(render_prooftrace_markdown(trace) if trace else "no trace\n",
                                               encoding="utf-8")
    (out / f"{stem}.messages.jsonl").write_text("\n".join(json.dumps(m) for m in orch.bus.log) + "\n",
                                                encoding="utf-8")
    print(render_prooftrace_markdown(trace) if trace else rep["suspected_root_cause"])
    print(f"wrote {stem}.report.json / .prooftrace.json / .prooftrace.md / .messages.jsonl to {out}/")
    print(f"re-check independently:  python -m netcoop verify-trace {out / (stem + '.prooftrace.json')} "
          f"--input {a.input} --log {out / (stem + '.messages.jsonl')}")
    return 0 if rep["status"] != "error" else 2


def cmd_verify_trace(a: argparse.Namespace) -> int:
    from .prooftrace import verify_prooftrace
    trace = json.loads(Path(a.trace).read_text(encoding="utf-8"))
    raw = json.loads(Path(a.input).read_text(encoding="utf-8"))
    log = [json.loads(line) for line in Path(a.log).read_text(encoding="utf-8").splitlines() if line.strip()]
    res = verify_prooftrace(trace, raw, log)
    print(f"{res['passed']}/{res['total']} checks passed -> {'VERIFIED' if res['verified'] else 'NOT VERIFIED'}")
    for c in res["failures"]:
        print(f"  FAIL {c['check']} [{c['target']}]: {c['detail']}")
    if a.verbose:
        for c in res["checks"]:
            print(f"  {'ok  ' if c['ok'] else 'FAIL'} {c['check']} [{c['target']}] {c['detail']}")
    return 0 if res["verified"] else 1


def cmd_organizer(a: argparse.Namespace) -> int:
    from .organizer import evaluate, render_markdown, save
    r = evaluate(a.n, a.seed, stress=not a.no_stress, save_dir=a.data_out)
    if a.sweep:
        r["sweep"] = {}
        for sd in range(1, a.sweep + 1):
            x = evaluate(a.n, sd, stress=False)["clean"]
            r["sweep"][sd] = {k: x[k] for k in ("accuracy", "false_diagnosis_rate", "abstention_rate",
                                                "detection_rate", "outcomes", "prooftrace_verified")}
    save(r, a.out)
    print(render_markdown(r))
    print(f"saved to {a.out}/ (organizer_eval.json, organizer_eval.md); incidents in {a.data_out}/incidents/")
    return 0


def cmd_interop(a: argparse.Namespace) -> int:
    from .remote import interop_demo
    rows = interop_demo()
    L = ["| Foreign agent behaviour | Negotiation | Agent health | Diagnosis | Confidence | Remote contribution | "
         "Reply items rejected | ProofTrace |", "|---|---|---|---|---|---|---|---|"]
    L += [f"| {r['case']} | {r['negotiation']} {r['format'] or ''} | {r['agent_health']} | {r['status']} "
          f"{r['cause'] or ''} | {r['confidence']:.2f} | {r['remote_contribution'] or '-'} | "
          f"{r['validation_problems']} | {'verified' if r['prooftrace_verified'] else 'FAILED'} |" for r in rows]
    L += ["", "Errors reported by the orchestrator:", ""]
    L += [f"- {r['case']}: {r['error']}" for r in rows if r["error"]]
    text = "\n".join(L) + "\n"
    print(text)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text("# Interoperability demo (weak_wifi incident, foreign HTTP connectivity agent)\n\n" + text)
    return 0


def cmd_trustguard_demo(a: argparse.Namespace) -> int:
    """The signature demo: an agent lies, TrustGuard catches it, ProofTrace records it."""
    from .agents import render_trustguard_markdown
    raw = generate("adversarial_agent")
    faults = simulation_faults(raw)
    orch = Orchestrator(inject_faults=faults)
    rep = orch.run(raw)
    tg, trace = rep["trustguard"], rep["prooftrace"]
    print("Scenario adversarial_agent: " + raw["simulation"]["note"])
    print(f"Faults injected: {faults}\n")
    print("\n".join(render_trustguard_markdown(tg)))
    print(f"Final: {rep['status']} {rep.get('root_cause_type')} on {', '.join(rep.get('root_cause_devices', []))} "
          f"(confidence {rep['confidence']:.2f})")
    from .prooftrace import TRUSTGUARD_CHECKS
    tgc = [c for c in trace["checks"]["checks"] if c["check"] in TRUSTGUARD_CHECKS]
    print(f"ProofTrace: {trace['checks']['passed']}/{trace['checks']['total']} checks passed "
          f"({sum(c['ok'] for c in tgc)}/{len(tgc)} TrustGuard-related); audit message {trace['trustguard']['audit_message_id']}")
    return 0 if tg["summary"]["flagged"] and trace["checks"]["verified"] else 1


def cmd_generate(a: argparse.Namespace) -> int:
    paths = write_all(a.out, a.seed)
    print(f"wrote {len(paths)} scenarios to {a.out}: " + ", ".join(p.stem for p in paths))
    return 0


def cmd_demo(a: argparse.Namespace) -> int:
    d = Path(a.dir)
    if not d.exists():
        write_all(d)
    rows = [("scenario", "status", "conf", "root cause devices", "TrustGuard", "diagnosis")]
    for name in SCENARIOS:
        path = d / f"{name}.json"
        sim = simulation_faults(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else {}
        rep = Orchestrator(inject_faults=sim).run_file(path)
        tg = (rep.get("trustguard") or {}).get("summary")
        rows.append((name, rep["status"], f"{rep['confidence']:.2f}",
                     ",".join(rep.get("root_cause_devices", [])) or "-",
                     f"{tg['flagged']} flagged/{tg['checked']}" if tg else "-", rep["suspected_root_cause"][:64]))
    w = [max(len(r[i]) for r in rows) for i in range(6)]
    for i, r in enumerate(rows):
        print("  ".join(c.ljust(w[j]) for j, c in enumerate(r)))
        if i == 0:
            print("  ".join("-" * x for x in w))
    return 0


def cmd_benchmark(a: argparse.Namespace) -> int:
    from .benchmark import render_markdown as bmd, run_benchmark, save_all
    b = run_benchmark(a.n, a.seed, ablation=not a.no_ablation, holdout_seed=a.holdout_seed,
                      stress_seed=a.stress_seed)
    save_all(b, a.out)
    print(bmd(b))
    print(f"saved to {a.out}/ (benchmark.json, benchmark.md, *.png)")
    return 0


def cmd_schemas(a: argparse.Namespace) -> int:
    from .schemas import export_schemas
    paths = export_schemas(a.out)
    print(f"wrote {len(paths)} protocol artefacts to {a.out}/")
    return 0


def cmd_validate(a: argparse.Namespace) -> int:
    from .schemas import validate_file
    ok, errors = validate_file(a.file)
    print(f"{ok} valid message(s), {len(errors)} invalid")
    for e in errors:
        print("  ✗", e)
    return 1 if errors else 0


def cmd_replay(a: argparse.Namespace) -> int:
    from .schemas import replay_log
    res = replay_log(a.log)
    print(json.dumps(res, indent=2))
    return 0 if res["deterministic"] else 1


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="netcoop", description="NetCoop AI multi-agent network diagnosis")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="write synthetic scenarios")
    g.add_argument("--out", default="data/scenarios")
    g.add_argument("--seed", type=int, default=42)
    g.set_defaults(fn=cmd_generate)
    r = sub.add_parser("run", help="diagnose one telemetry file")
    r.add_argument("input")
    r.add_argument("--markdown", action="store_true", help="print Markdown instead of JSON")
    r.add_argument("--trace", action="store_true", help="print the inter-agent message trace")
    r.add_argument("--log", help="write full message log (JSONL)")
    r.add_argument("--out", help="write JSON report to file")
    r.add_argument("--inject-fault", action="append", metavar="AGENT:MODE",
                   help="simulate an agent fault (MODE = transient | permanent | adversarial)")
    r.add_argument("--no-trustguard", action="store_true", help="skip the TrustGuard audit (comparison only)")
    r.add_argument("--no-simulation", action="store_true", help="ignore a demo scenario's simulation block")
    r.add_argument("--simulate-fix", action="store_true",
                   help="dry-run the recommended fix on the synthetic data and re-diagnose")
    r.add_argument("--remote-connectivity", metavar="URL",
                   help="use a foreign HTTP agent (see `serve-remote`) as the connectivity agent")
    r.add_argument("--fix-hypothesis", help="with --simulate-fix: apply the fix for this hypothesis instead")
    r.add_argument("--efficacy", type=float, default=1.0, help="with --simulate-fix: 0-1, how well the fix works")
    r.set_defaults(fn=cmd_run)
    pt = sub.add_parser("prooftrace", help="diagnose and write report + ProofTrace + message log for audit")
    pt.add_argument("input")
    pt.add_argument("--out-dir", default="out")
    pt.add_argument("--inject-fault", action="append", metavar="AGENT:MODE")
    pt.add_argument("--remote-connectivity", metavar="URL")
    pt.add_argument("--no-trustguard", action="store_true")
    pt.add_argument("--no-simulation", action="store_true")
    pt.set_defaults(fn=cmd_prooftrace)
    vt = sub.add_parser("verify-trace", help="independently re-check a ProofTrace against raw input and message log")
    vt.add_argument("trace")
    vt.add_argument("--input", required=True)
    vt.add_argument("--log", required=True)
    vt.add_argument("--verbose", action="store_true")
    vt.set_defaults(fn=cmd_verify_trace)
    og = sub.add_parser("organizer-eval", help="evaluate on incidents built with the organizer's notebook generator")
    og.add_argument("--n", type=int, default=40)
    og.add_argument("--seed", type=int, default=7)
    og.add_argument("--sweep", type=int, default=0, help="also evaluate seeds 1..N (clean) for stability")
    og.add_argument("--no-stress", action="store_true")
    og.add_argument("--out", default="benchmarks/organizer")
    og.add_argument("--data-out", default="data/organizer")
    og.set_defaults(fn=cmd_organizer)
    io = sub.add_parser("interop-demo", help="foreign HTTP agent: success, negotiation failure and failure modes")
    io.add_argument("--out", default="examples/interop_demo.md")
    io.set_defaults(fn=cmd_interop)
    sa = sub.add_parser("serve-api", help="JSON API + React web UI (web/dist) for the browser dashboard")
    sa.add_argument("--port", type=int, default=8000)
    sa.set_defaults(fn=lambda a: __import__("netcoop.api", fromlist=["serve"]).serve(a.port))
    sr = sub.add_parser("serve-remote", help="start the foreign WirelessOps analyzer (HTTP)")
    sr.add_argument("--port", type=int, default=8765)
    sr.add_argument("--mode", default="ok", help="ok | incompatible | malformed | partial | slow | flaky")
    sr.set_defaults(fn=lambda a: __import__("netcoop.remote", fromlist=["serve"]).serve(a.port, a.mode))
    tgd = sub.add_parser("trustguard-demo", help="adversarial agent -> TrustGuard flags it -> ProofTrace records it")
    tgd.set_defaults(fn=cmd_trustguard_demo)
    d = sub.add_parser("demo", help="run every scenario and print a summary table")
    d.add_argument("--dir", default="data/scenarios")
    d.set_defaults(fn=cmd_demo)
    b = sub.add_parser("benchmark", help="accuracy / calibration / ablation on randomised incidents")
    b.add_argument("--n", type=int, default=300)
    b.add_argument("--seed", type=int, default=1)
    b.add_argument("--out", default="benchmarks")
    b.add_argument("--no-ablation", action="store_true")
    b.add_argument("--holdout-seed", type=int, default=3, help="second incident set reported separately")
    b.add_argument("--stress-seed", type=int, default=4,
                   help="incident set with fainter faults / more noise than development, reported separately")
    b.set_defaults(fn=cmd_benchmark)
    sc = sub.add_parser("schemas", help="export JSON schemas, agent cards and threshold tables")
    sc.add_argument("--out", default="schemas")
    sc.set_defaults(fn=cmd_schemas)
    v = sub.add_parser("validate", help="validate a protocol message / JSONL message log")
    v.add_argument("file")
    v.set_defaults(fn=cmd_validate)
    rp = sub.add_parser("replay", help="replay a message log against fresh agents and check determinism")
    rp.add_argument("log")
    rp.set_defaults(fn=cmd_replay)
    a = p.parse_args(argv)
    sys.exit(a.fn(a))
