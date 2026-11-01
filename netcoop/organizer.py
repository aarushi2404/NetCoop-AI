"""Evaluation on ORGANIZER-generated data (kept strictly separate from our own synthetic benchmark).

Source: `data/organizer/mock-data-builder-netScoopAI.ipynb`, the mock-data builder supplied by the
organizers. We do not re-implement it: the notebook's own `generate_telemetry(fault_type)` function is
loaded from the .ipynb and called.

How the notebook is loaded
  * the code cells are parsed with `ast`; only `import` statements and function definitions are executed
    (the example `print(...)` at the bottom is skipped). Nothing is downloaded or installed.
  * supported fault types are discovered from the function itself (string constants compared with its
    `fault_type` argument, plus its default), not typed in by us.
  * for reproducibility the function's `random` is a seeded `random.Random` and `datetime.utcnow()` is a
    deterministic clock (one minute per sample). The value ranges and logic are untouched.

What the notebook produces and how we adapt it
  One record per call: {timestamp, device_id ("SW_CAMPUS_<1..10>", random), metrics, status}. This is
  already a schema our normalizer accepts (unversioned = legacy, field names are canonical), so no field
  mapping is needed. Two adaptations are needed to turn single records into incidents, and both are explicit:
    1. a device's samples must share one id, so each incident picks 2-5 distinct `SW_CAMPUS_n` names and
       calls the generator 3-5 times per device; the id the generator drew is kept in `generator_device_id`.
    2. one device per incident gets the incident's fault profile, the others get `normal`. The notebook
       provides no topology, so none is given to NetCoop (flat network, no downstream reasoning).

Ground truth (our mapping of the organizer labels; stated, not hidden)
  normal           -> healthy
  hardware_failure -> root cause hardware_failure on the faulty device
  latency_spike    -> a *symptom*, not a root cause: no CPU/interface/Wi-Fi/DNS evidence is generated.
                      Correct = the faulty device is detected AND no root cause is committed to
                      (insufficient_evidence). A tentative cause is counted as "hedged" (not correct, not a
                      confident error); a diagnosed cause is a false diagnosis.

    python -m netcoop organizer-eval --n 40 --seed 7
"""
from __future__ import annotations

import ast
import copy
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .benchmark import calibration
from .orchestrator import Orchestrator

ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK = ROOT / "data" / "organizer" / "mock-data-builder-netScoopAI.ipynb"
GENERATOR_FUNCTION = "generate_telemetry"
TRUTH = {"normal": "healthy", "hardware_failure": "hardware_failure", "latency_spike": "symptom_only"}


class _Clock:
    """Stands in for `datetime` inside the notebook: utcnow() advances one minute per call."""

    def __init__(self, start: datetime):
        self.t = start

    def utcnow(self) -> datetime:
        self.t += timedelta(minutes=1)
        return self.t


def load_generator(path: str | Path = NOTEBOOK) -> tuple[dict, dict]:
    """Return (namespace holding the notebook's generator, info about what was loaded)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"organizer notebook not found: {path}")
    nb = json.loads(path.read_text(encoding="utf-8"))
    code = "\n\n".join("".join(c["source"]) for c in nb.get("cells", []) if c.get("cell_type") == "code")
    tree = ast.parse(code)
    keep = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef))]
    skipped = [ast.unparse(n).splitlines()[0][:90] for n in tree.body if n not in keep]
    fn_node = next((n for n in keep if isinstance(n, ast.FunctionDef) and n.name == GENERATOR_FUNCTION), None)
    if fn_node is None:
        raise ValueError(f"notebook defines no function '{GENERATOR_FUNCTION}'")
    arg = fn_node.args.args[0].arg if fn_node.args.args else None
    types: set[str] = set()
    for node in ast.walk(fn_node):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == arg:
            types |= {c.value for c in node.comparators if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    default = fn_node.args.defaults[0].value if fn_node.args.defaults else None
    if isinstance(default, str):
        types.add(default)
    ns: dict[str, Any] = {"__name__": "organizer_notebook"}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(path), "exec"), ns)  # noqa: S102 (reviewed code)
    info = {"notebook": (path.relative_to(ROOT) if path.is_relative_to(ROOT) else path).as_posix(),
            "function": GENERATOR_FUNCTION, "fault_types": sorted(types), "skipped_statements": skipped,
            "cells": len(nb.get("cells", []))}
    return ns, info


def _seeded(ns: dict, seed: int) -> Callable[[str], dict]:
    ns["random"] = random.Random(seed)
    ns["datetime"] = _Clock(datetime(2026, 10, 31, 12, 0))
    return ns[GENERATOR_FUNCTION]


def build_incidents(n: int = 40, seed: int = 7, path: str | Path = NOTEBOOK) -> tuple[list[dict], dict]:
    ns, info = load_generator(path)
    gen = _seeded(ns, seed)
    rng = random.Random(f"assembly-{seed}")
    labels = info["fault_types"]
    incidents = []
    for i in range(n):
        label = labels[i % len(labels)]
        names = rng.sample([f"SW_CAMPUS_{k}" for k in range(1, 11)], rng.randint(2, 5))
        faulty = rng.choice(names) if label != "normal" else None
        records = []
        for name in names:
            for _ in range(rng.randint(3, 5)):
                rec = gen(label if name == faulty else "normal")
                rec["generator_device_id"] = rec["device_id"]
                rec["device_id"] = name
                records.append(rec)
        rng.shuffle(records)
        incidents.append({"incident_id": f"ORG-{seed}-{i:03d}", "source": "organizer notebook generator",
                          "label": label, "faulty_device": faulty, "devices": sorted(names), "records": records})
    return incidents, info


def _stress(inc: dict, rng: random.Random) -> dict:
    """Same incident with realistic collector damage: dropped metrics, a stale sample, a junk value."""
    doc = copy.deepcopy(inc)
    for r in doc["records"]:
        for k in list(r["metrics"]):
            if rng.random() < 0.2:
                del r["metrics"][k]
    victim = rng.choice(doc["records"])
    stale = copy.deepcopy(victim)
    stale["timestamp"] = "2026-10-30T08:00:00Z"
    stale["metrics"] = {k: v * 3 if isinstance(v, (int, float)) else v for k, v in stale["metrics"].items()}
    doc["records"].append(stale)
    rng.choice(doc["records"])["metrics"]["latency_ms"] = "n/a"
    return doc


def score(inc: dict, rep: dict) -> dict:
    label, faulty, status = inc["label"], inc["faulty_device"], rep["status"]
    roots = rep.get("root_cause_devices", [])
    committed = status in ("diagnosed", "tentative")
    if label == "normal":
        outcome = "correct" if status == "healthy" else ("false_diagnosis" if committed else "false_alarm")
        detected = None
    elif label == "hardware_failure":
        detected = status != "healthy" and faulty in roots
        if committed and rep.get("root_cause_type") == "hardware_failure" and faulty in roots:
            outcome = "correct"
        elif committed:
            outcome = "false_diagnosis"
        else:
            outcome = "missed" if status == "healthy" else "abstained"
    else:  # symptom-only label: the honest answer is "degraded, cause unknown"
        detected = status != "healthy" and faulty in roots
        if status == "insufficient_evidence" and detected:
            outcome = "correct"
        elif status == "tentative":
            outcome = "hedged"
        elif status == "diagnosed":
            outcome = "false_diagnosis"
        else:
            outcome = "missed" if status == "healthy" else "abstained"
    return {"incident": inc["incident_id"], "label": label, "faulty_device": faulty, "status": status,
            "predicted_cause": rep.get("root_cause_type") or rep.get("leading_hypothesis"),
            "root_cause_devices": roots, "confidence": rep["confidence"], "outcome": outcome,
            "detected": detected, "pred": "insufficient" if status == "insufficient_evidence" else "decided",
            "correct": outcome == "correct",
            "prooftrace_checks": (rep.get("prooftrace") or {}).get("checks", {}).get("total"),
            "prooftrace_verified": (rep.get("prooftrace") or {}).get("checks", {}).get("verified")}


def _summarise(rows: list[dict]) -> dict:
    n = len(rows)
    oc = Counter(r["outcome"] for r in rows)
    by_label: dict[str, list] = defaultdict(list)
    for r in rows:
        by_label[r["label"]].append(r)
    faults = [r for r in rows if r["label"] != "normal"]
    committed = [r for r in rows if r["status"] in ("diagnosed", "tentative")]
    cal_rows = [{"pred": "x", "correct": r["correct"], "confidence": r["confidence"]} for r in committed]
    return {
        "n": n, "accuracy": round(oc["correct"] / n, 3),
        "false_diagnosis_rate": round(oc["false_diagnosis"] / n, 3),
        "abstention_rate": round(sum(r["status"] == "insufficient_evidence" for r in rows) / n, 3),
        "detection_rate": round(sum(bool(r["detected"]) for r in faults) / max(1, len(faults)), 3),
        "false_alarm_rate_on_normal": round(sum(r["outcome"] != "correct" for r in by_label["normal"])
                                            / max(1, len(by_label["normal"])), 3),
        "outcomes": dict(oc),
        "per_label": {k: {"n": len(v), "accuracy": round(sum(x["correct"] for x in v) / len(v), 3),
                          "outcomes": dict(Counter(x["outcome"] for x in v)),
                          "status": dict(Counter(x["status"] for x in v))} for k, v in sorted(by_label.items())},
        "calibration_on_committed": calibration(cal_rows) if cal_rows else None,
        "prooftrace_verified": f"{sum(bool(r['prooftrace_verified']) for r in rows)}/{n}",
    }


def evaluate(n: int = 40, seed: int = 7, stress: bool = True, save_dir: str | Path | None = None,
             path: str | Path = NOTEBOOK) -> dict:
    incidents, info = build_incidents(n, seed, path)
    out: dict[str, Any] = {"source": info, "n": n, "seed": seed, "ground_truth_mapping": TRUTH,
                           "adaptations": [
                               "records grouped into incidents of 2-5 devices x 3-5 samples; device_id made "
                               "consistent per device (generator's random id kept as generator_device_id)",
                               "one faulty device per incident, the rest generated with fault_type='normal'",
                               "seeded random and a deterministic clock injected for reproducibility",
                               "no topology given (the notebook has none)"]}
    sets = {"clean": incidents}
    if stress:
        rng = random.Random(f"stress-{seed}")
        sets["stressed"] = [_stress(i, rng) for i in incidents]
    for name, docs in sets.items():
        rows = [score(doc, Orchestrator().run(doc)) for doc in docs]
        out[name] = {**_summarise(rows), "rows": rows}
    if save_dir:
        d = Path(save_dir)
        (d / "incidents").mkdir(parents=True, exist_ok=True)
        for inc in incidents:
            (d / "incidents" / f"{inc['incident_id']}.json").write_text(json.dumps(inc, indent=2))
    return out


def render_markdown(r: dict) -> str:
    L = ["# Evaluation on organizer-generated data", "",
         f"Generator: `{r['source']['notebook']}` -> `{r['source']['function']}()` "
         f"(fault types discovered from the notebook: {', '.join(r['source']['fault_types'])}). "
         f"{r['n']} incidents, seed {r['seed']}. **This data was not produced by our generator and was not used "
         "to tune NetCoop.**", "",
         "Adaptations: " + "; ".join(r["adaptations"]) + ".", "",
         "Ground truth mapping: `normal` -> healthy, `hardware_failure` -> hardware_failure on the faulty device, "
         "`latency_spike` -> symptom only: correct = faulty device detected and *no* root cause committed.", ""]
    for name in ("clean", "stressed"):
        if name not in r:
            continue
        x = r[name]
        L += [f"## {name.capitalize()} incidents" + (" (20 % metrics dropped, stale sample, junk value)"
                                                      if name == "stressed" else ""), "",
              "| Metric | Value |", "|---|---|",
              f"| Accuracy | {x['accuracy']:.1%} |",
              f"| False diagnoses (committed to a wrong cause/device, or a fault on a healthy network) | "
              f"{x['false_diagnosis_rate']:.1%} |",
              f"| Abstention rate | {x['abstention_rate']:.1%} |",
              f"| Faulty device detected (non-normal incidents) | {x['detection_rate']:.1%} |",
              f"| False alarms on normal incidents | {x['false_alarm_rate_on_normal']:.1%} |",
              f"| ProofTrace independently verified | {x['prooftrace_verified']} |", "",
              "| Organizer label | n | Accuracy | Outcomes | Status |", "|---|---|---|---|---|"]
        L += [f"| {k} | {v['n']} | {v['accuracy']:.0%} | "
              + ", ".join(f"{a} {b}" for a, b in v["outcomes"].items()) + " | "
              + ", ".join(f"{a} {b}" for a, b in v["status"].items()) + " |" for k, v in x["per_label"].items()]
        cal = x.get("calibration_on_committed")
        if cal:
            L += ["", f"Calibration on committed diagnoses (ECE {cal['ece']:.3f}): "
                  + "; ".join(f"{b['bin']}: n={b['n']}, conf {b['mean_confidence']:.2f}, acc {b['accuracy']:.2f}"
                              for b in cal["bins"])]
        L.append("")
    if r.get("sweep"):
        L += ["## Stability across independent seeds (clean incidents)", "",
              "| Seed | Accuracy | False diagnoses | Abstention | Detection | Outcomes | ProofTrace verified |",
              "|---|---|---|---|---|---|---|"]
        L += [f"| {sd} | {x['accuracy']:.1%} | {x['false_diagnosis_rate']:.1%} | {x['abstention_rate']:.1%} | "
              f"{x['detection_rate']:.1%} | " + ", ".join(f"{a} {b}" for a, b in x["outcomes"].items())
              + f" | {x['prooftrace_verified']} |" for sd, x in r["sweep"].items()]
        L.append("")
    L += ["## How to read this", "",
          "The organizer generator's profiles are far apart (hardware failure: CPU 99.9 %, latency 500-1000 ms, "
          "Critical status; latency_spike: no cause-specific signal at all), so high accuracy here mainly shows "
          "that NetCoop handles an external schema and does not over-claim a root cause for a bare latency "
          "symptom. It says little about hard borderline cases; those are covered by the internal benchmark, "
          "which varies fault severity down to 0.55x. Small n: one error moves accuracy by 2.5 points.", ""]
    return "\n".join(L) + "\n"


def save(r: dict, out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "organizer_eval.json").write_text(json.dumps(r, indent=2))
    (out / "organizer_eval.md").write_text(render_markdown(r))
    return [out / "organizer_eval.json", out / "organizer_eval.md"]
