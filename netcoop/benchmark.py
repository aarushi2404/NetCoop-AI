"""Accuracy, calibration and multi-agent ablation benchmark on randomised labelled incidents.

    python -m netcoop benchmark --n 300 --seed 1 --out benchmarks

Each incident = a fault scenario with random severity, sensor noise and metric dropout.
Truth = (root-cause type, root-cause devices). "Abstaining" (insufficient_evidence) counts as
wrong in `accuracy`, and is excluded from `selective_accuracy`, so the trade-off is visible.
"""
from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from .generator import SCENARIO_TRUTH, generate
from .orchestrator import Orchestrator

# the adversarial demo scenario is a hardware failure plus an injected agent fault: evaluated separately
POOL = ["normal"] * 2 + [s for s in SCENARIO_TRUTH if s not in ("normal", "adversarial_agent")]
LABELS = ["healthy", "link_congestion", "interface_fault", "weak_wifi", "device_overload",
          "hardware_failure", "dns_failure", "dhcp_failure", "insufficient"]

ABLATIONS: dict[str, dict[str, str]] = {
    "all 3 specialists + correlation": {},
    "without performance_agent": {"performance_agent": "permanent"},
    "without infrastructure_agent": {"infrastructure_agent": "permanent"},
    "without connectivity_agent": {"connectivity_agent": "permanent"},
    "performance_agent only": {"infrastructure_agent": "permanent", "connectivity_agent": "permanent"},
    "infrastructure_agent only": {"performance_agent": "permanent", "connectivity_agent": "permanent"},
    "connectivity_agent only": {"performance_agent": "permanent", "infrastructure_agent": "permanent"},
}


# incident parameter ranges. "standard" is what development used; "stress" lies deliberately outside it
# (fainter faults, more noise, more missing metrics) and is reported separately, never tuned on.
PROFILES = {
    "standard": {"severity": (0.55, 1.25), "noise": (0.03, 0.20), "dropout": (0, 0, 0.05, 0.15, 0.3)},
    "stress": {"severity": (0.35, 0.60), "noise": (0.20, 0.35), "dropout": (0.15, 0.3, 0.45)},
}


def make_cases(n: int, seed: int, profile: str = "standard") -> list[dict]:
    rng = random.Random(seed)
    pr = PROFILES[profile]
    cases = []
    for i in range(n):
        name = rng.choice(POOL)
        truth_type, truth_devs = SCENARIO_TRUTH[name]
        params = {"severity": 1.0 if name == "normal" else round(rng.uniform(*pr["severity"]), 2),
                  "noise": round(rng.uniform(*pr["noise"]), 3), "dropout": round(rng.choice(pr["dropout"]), 2)}
        cases.append({"id": i, "scenario": name, "truth": truth_type, "devices": truth_devs, **params,
                      "doc": generate(name, seed=seed * 100_000 + i, **params)})
    return cases


def predict(rep: dict) -> str:
    if rep["status"] == "healthy":
        return "healthy"
    if rep["status"] in ("diagnosed", "tentative"):
        return rep["root_cause_type"]
    return "insufficient"


def is_correct(case: dict, rep: dict) -> bool:
    pred = predict(rep)
    if pred != case["truth"]:
        return False
    return pred == "healthy" or set(case["devices"]) <= set(rep.get("root_cause_devices", []))


def evaluate(cases: list[dict], faults: dict[str, str] | None = None, prooftrace: bool = False,
             trustguard: bool = True) -> dict:
    rows = []
    for c in cases:
        rep = Orchestrator(inject_faults=faults, max_retries=0 if faults else 1, prooftrace=prooftrace,
                           trustguard=trustguard).run(c["doc"])
        tg = rep.get("trustguard") or {}
        odd = (tg.get("flagged") or []) + (tg.get("unverifiable") or [])
        rows.append({"case": c["id"], "scenario": c["scenario"], "truth": c["truth"], "pred": predict(rep),
                     "correct": is_correct(c, rep), "confidence": rep["confidence"], "status": rep["status"],
                     "leading": "healthy" if rep["status"] == "healthy" else rep.get("leading_hypothesis"),
                     "prooftrace_verified": (rep.get("prooftrace") or {}).get("checks", {}).get("verified"),
                     "tg_checked": (tg.get("summary") or {}).get("checked", 0), "tg_not_trusted": len(odd),
                     "tg_votes_not_trusted": {f["agent"]: sum(1 for x in odd if x["agent"] == f["agent"]
                                                              and x["kind"] == "vote") for f in odd}})
    n = len(rows)
    decided = [r for r in rows if r["pred"] != "insufficient"]
    wrong_decided = [r for r in decided if not r["correct"]]
    return {
        "n": n, "accuracy": round(sum(r["correct"] for r in rows) / n, 3),
        "abstention_rate": round((n - len(decided)) / n, 3),
        "selective_accuracy": round(sum(r["correct"] for r in decided) / max(1, len(decided)), 3),
        "confident_wrong_rate": round(sum(1 for r in wrong_decided if r["confidence"] >= 0.65) / n, 3),
        "false_diagnosis_rate": round(len(wrong_decided) / n, 3),
        # when the system abstains, was its (uncommitted) leading hypothesis right? measures abstention quality
        "abstained_leading_correct": round(sum(r["leading"] == r["truth"] for r in rows if r["pred"] == "insufficient")
                                           / max(1, n - len(decided)), 3),
        "prooftrace_verified": (f"{sum(bool(r['prooftrace_verified']) for r in rows)}/{n}"
                                if prooftrace else None),
        "rows": rows,
    }


def per_class(rows: list[dict]) -> dict[str, dict]:
    """Recall (share of a cause's incidents diagnosed correctly), precision (share of committed predictions of a
    cause that were right) and abstention per true cause. Distinguishes "confused with another cause" from
    "declined to commit"."""
    out = {}
    for c in sorted({r["truth"] for r in rows}):
        mine = [r for r in rows if r["truth"] == c]
        predicted = [r for r in rows if r["pred"] == c]
        out[c] = {"n": len(mine), "recall": round(sum(r["correct"] for r in mine) / len(mine), 3),
                  "precision": round(sum(r["correct"] for r in predicted) / len(predicted), 3) if predicted else None,
                  "abstained": sum(r["pred"] == "insufficient" for r in mine),
                  "confused_with": dict(Counter(r["pred"] for r in mine if not r["correct"]
                                                and r["pred"] != "insufficient"))}
    return out


def confusion(rows: list[dict]) -> dict[str, dict[str, int]]:
    m: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        m[r["truth"]][r["pred"]] += 1
    return {t: dict(c) for t, c in m.items()}


def calibration(rows: list[dict], bins=((0.0, 0.45), (0.45, 0.65), (0.65, 0.8), (0.8, 0.9), (0.9, 1.01))) -> dict:
    """Reliability table over non-abstained predictions + expected calibration error (ECE)."""
    decided = [r for r in rows if r["pred"] != "insufficient"]
    table, ece = [], 0.0
    for lo, hi in bins:
        b = [r for r in decided if lo <= r["confidence"] < hi]
        if not b:
            continue
        conf = sum(r["confidence"] for r in b) / len(b)
        acc = sum(r["correct"] for r in b) / len(b)
        ece += len(b) / max(1, len(decided)) * abs(conf - acc)
        table.append({"bin": f"{lo:.2f}-{min(hi, 1.0):.2f}", "n": len(b), "mean_confidence": round(conf, 3),
                      "accuracy": round(acc, 3)})
    return {"ece": round(ece, 3), "bins": table}


def run_benchmark(n: int = 300, seed: int = 1, ablation: bool = True, holdout_seed: int | None = None,
                  prooftrace: bool = True, stress_seed: int | None = None) -> dict:
    cases = make_cases(n, seed)
    full = evaluate(cases, prooftrace=prooftrace)
    out = {"n": n, "seed": seed, "full": {k: v for k, v in full.items() if k != "rows"},
           "confusion": confusion(full["rows"]), "calibration": calibration(full["rows"]),
           "per_class": per_class(full["rows"]),
           "per_scenario": {}, "rows": full["rows"]}
    by_sc: dict[str, list] = defaultdict(list)
    for r in full["rows"]:
        by_sc[r["scenario"]].append(r)
    out["per_scenario"] = {s: {"n": len(v), "accuracy": round(sum(x["correct"] for x in v) / len(v), 3),
                               "abstained": sum(x["pred"] == "insufficient" for x in v)}
                           for s, v in sorted(by_sc.items())}
    if holdout_seed is not None:   # a second, independently drawn incident set nothing was developed on
        ho = evaluate(make_cases(n, holdout_seed))
        out["holdout"] = {"seed": holdout_seed, **{k: v for k, v in ho.items() if k != "rows"},
                          "calibration": calibration(ho["rows"])}
    if stress_seed is not None:    # out-of-range conditions: expected to be harder, reported as is
        st = evaluate(make_cases(n, stress_seed, "stress"))
        by: dict[str, list] = defaultdict(list)
        for r in st["rows"]:
            by[r["scenario"]].append(r)
        out["stress"] = {"seed": stress_seed, "profile": PROFILES["stress"],
                         **{k: v for k, v in st.items() if k != "rows"}, "calibration": calibration(st["rows"]),
                         "per_scenario": {sc: {"n": len(v), "accuracy": round(sum(x["correct"] for x in v) / len(v), 3),
                                               "abstained": sum(x["pred"] == "insufficient" for x in v)}
                                          for sc, v in sorted(by.items())}}
    out["trustguard"] = trustguard_eval(cases, full["rows"], seed, holdout_seed, stress_seed)
    if ablation:
        out["ablation"] = {}
        for name, faults in ABLATIONS.items():
            res = full if not faults else evaluate(cases, faults)
            out["ablation"][name] = {k: v for k, v in res.items() if k != "rows"}
    return out


def trustguard_eval(cases: list[dict], dev_rows: list[dict], seed: int, holdout_seed: int | None,
                    stress_seed: int | None) -> dict:
    """(1) false alarms: how many claims of *honest* agents TrustGuard rejects, on every incident set;
    (2) adversarial robustness: each specialist in turn submits one misleading vote per incident
    (the controlled `adversarial` fault mode); accuracy with and without TrustGuard on the same incidents."""
    sets = {f"dev (seed {seed})": dev_rows}
    if holdout_seed is not None:
        sets[f"held-out (seed {holdout_seed})"] = evaluate(make_cases(len(cases), holdout_seed))["rows"]
    if stress_seed is not None:
        sets[f"stress (seed {stress_seed})"] = evaluate(make_cases(len(cases), stress_seed, "stress"))["rows"]
    honest = {k: {"incidents": len(rs), "claims_checked": sum(r["tg_checked"] for r in rs),
                  "claims_not_trusted": sum(r["tg_not_trusted"] for r in rs),
                  "incidents_with_any_flag": sum(r["tg_not_trusted"] > 0 for r in rs)} for k, rs in sets.items()}
    adversarial = {}
    keep = ("accuracy", "abstention_rate", "false_diagnosis_rate", "confident_wrong_rate")
    for agent in ("performance_agent", "infrastructure_agent", "connectivity_agent"):
        faults = {agent: "adversarial"}
        without = evaluate(cases, faults, trustguard=False)
        with_tg = evaluate(cases, faults)
        caught = sum(r["tg_votes_not_trusted"].get(agent, 0) > 0 for r in with_tg["rows"])
        adversarial[agent] = {"without_trustguard": {k: without[k] for k in keep},
                              "with_trustguard": {k: with_tg[k] for k in keep},
                              "misleading_vote_flagged_or_capped": round(caught / len(cases), 3),
                              "corrupted_without": sum(a["correct"] and not b["correct"] for a, b in
                                                       zip(dev_rows, without["rows"])),
                              "corrupted_with": sum(a["correct"] and not b["correct"] for a, b in
                                                    zip(dev_rows, with_tg["rows"]))}
    return {"honest_agents": honest, "adversarial": adversarial}


def render_markdown(b: dict) -> str:
    f = b["full"]
    L = [f"# NetCoop benchmark ({b['n']} randomised incidents, seed {b['seed']})", "",
         "Each incident has random fault severity (0.55-1.25x), sensor noise (3-20 %) and metric dropout (0-30 %).", "",
         "| Metric | Value |", "|---|---|",
         f"| Accuracy (abstaining counts as wrong) | {f['accuracy']:.1%} |",
         f"| Selective accuracy (when the system commits) | {f['selective_accuracy']:.1%} |",
         f"| Abstention rate (insufficient evidence) | {f['abstention_rate']:.1%} |",
         f"| Confident-and-wrong rate (confidence >= 0.65) | {f['confident_wrong_rate']:.1%} |",
         f"| Expected calibration error | {b['calibration']['ece']:.3f} |",
         f"| Committed to a wrong cause/device (any confidence) | {f.get('false_diagnosis_rate', 0):.1%} |",
         f"| When abstaining, leading hypothesis was right | {f.get('abstained_leading_correct', 0):.1%} |",
         f"| ProofTrace independently verified | {f.get('prooftrace_verified') or 'not run'} |", "",
         "Data: **internally generated** (our own `netcoop/generator.py`). Organizer-generated data is evaluated "
         "separately in `benchmarks/organizer/`.", ""]
    if "holdout" in b:
        h = b["holdout"]
        L += [f"## Held-out incident set (seed {h['seed']}, not used during development)", "",
              "| Metric | Value |", "|---|---|", f"| Accuracy | {h['accuracy']:.1%} |",
              f"| Selective accuracy | {h['selective_accuracy']:.1%} |", f"| Abstention rate | {h['abstention_rate']:.1%} |",
              f"| Confident-and-wrong rate | {h['confident_wrong_rate']:.1%} |",
              f"| Expected calibration error | {h['calibration']['ece']:.3f} |", "",
              "Same generator and parameter ranges as above, different random draws: this guards against "
              "over-fitting to particular incidents, **not** against a different data distribution.", ""]
    if "stress" in b:
        t = b["stress"]
        p = t["profile"]
        L += [f"## Stress set (seed {t['seed']}, conditions outside the development range)", "",
              f"Fault severity {p['severity'][0]}-{p['severity'][1]}x, sensor noise {p['noise'][0]:.0%}-"
              f"{p['noise'][1]:.0%}, metric dropout {min(p['dropout']):.0%}-{max(p['dropout']):.0%}. "
              "Nothing was tuned on this set; lower numbers are expected and reported unchanged.", "",
              "| Metric | Value |", "|---|---|", f"| Accuracy | {t['accuracy']:.1%} |",
              f"| Selective accuracy | {t['selective_accuracy']:.1%} |", f"| Abstention rate | {t['abstention_rate']:.1%} |",
              f"| Confident-and-wrong rate | {t['confident_wrong_rate']:.1%} |",
              f"| Committed to a wrong cause/device | {t.get('false_diagnosis_rate', 0):.1%} |",
              f"| Expected calibration error | {t['calibration']['ece']:.3f} |", "",
              "| Scenario | n | Accuracy | Abstained |", "|---|---|---|---|"]
        L += [f"| {s} | {v['n']} | {v['accuracy']:.0%} | {v['abstained']} |" for s, v in t["per_scenario"].items()]
        L += [""]
    if "trustguard" in b:
        t = b["trustguard"]
        L += ["## TrustGuard", "", "**False alarms on honest agents** (no fault injected). Every claim of every "
              "specialist is audited; a rejected honest claim would be a false alarm.", "",
              "| Incident set | Incidents | Claims checked | Claims not trusted | Incidents with any flag |",
              "|---|---|---|---|---|"]
        L += [f"| {k} | {v['incidents']} | {v['claims_checked']} | {v['claims_not_trusted']} | "
              f"{v['incidents_with_any_flag']} |" for k, v in t["honest_agents"].items()]
        L += ["", f"**Adversarial robustness** (dev set, {b['n']} incidents). The named agent runs in the controlled "
              "`adversarial` mode: on the most degraded device it votes 0.99 for the hypothesis its own evidence "
              "supports least; its signals and evidence stay truthful. Same incidents with and without TrustGuard.", "",
              "| Adversarial agent | Accuracy without -> with | Wrong diagnoses without -> with | Correct answers "
              "corrupted without -> with | Misleading vote flagged or capped |", "|---|---|---|---|---|"]
        L += [f"| {a} | {v['without_trustguard']['accuracy']:.1%} -> {v['with_trustguard']['accuracy']:.1%} | "
              f"{v['without_trustguard']['false_diagnosis_rate']:.1%} -> {v['with_trustguard']['false_diagnosis_rate']:.1%} | "
              f"{v['corrupted_without']} -> {v['corrupted_with']} | {v['misleading_vote_flagged_or_capped']:.1%} |"
              for a, v in t["adversarial"].items()]
        L += ["", "A misleading vote that the telemetry does support (e.g. a strong symptom of the claimed cause is "
              "really present) is not flagged: TrustGuard checks claims against evidence, not against the truth "
              "label. This is a controlled simulation of one kind of unreliable agent, not proof of detecting every "
              "compromised agent.", ""]
    L += ["## Calibration", "", "| Confidence bin | n | Mean confidence | Actual accuracy |", "|---|---|---|---|"]
    L += [f"| {x['bin']} | {x['n']} | {x['mean_confidence']:.2f} | {x['accuracy']:.2f} |"
          for x in b["calibration"]["bins"]]
    if "per_class" in b:
        L += ["", "## Per class (true root cause)", "",
              "Recall = share of the cause's incidents diagnosed correctly; precision = share of committed "
              "predictions of that cause that were right; *confused with* lists wrong committed causes "
              "(abstentions are counted separately).", "",
              "| Cause | n | Recall | Precision | Abstained | Confused with |", "|---|---|---|---|---|---|"]
        L += [f"| {c} | {v['n']} | {v['recall']:.0%} | "
              f"{'-' if v['precision'] is None else format(v['precision'], '.0%')} | {v['abstained']} | "
              f"{', '.join(f'{k} ({n})' for k, n in v['confused_with'].items()) or 'none'} |"
              for c, v in b["per_class"].items()]
    L += ["", "## Per scenario", "", "| Scenario | n | Accuracy | Abstained |", "|---|---|---|---|"]
    L += [f"| {s} | {v['n']} | {v['accuracy']:.0%} | {v['abstained']} |" for s, v in b["per_scenario"].items()]
    if "ablation" in b:
        L += ["", "## Ablation: does the multi-agent design matter?", "",
              "| Configuration | Accuracy | Selective acc. | Abstain | Confident-wrong |", "|---|---|---|---|---|"]
        L += [f"| {k} | {v['accuracy']:.1%} | {v['selective_accuracy']:.1%} | {v['abstention_rate']:.1%} | "
              f"{v['confident_wrong_rate']:.1%} |" for k, v in b["ablation"].items()]
    return "\n".join(L) + "\n"


def save_plots(b: dict, out: Path) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    paths = []
    # confusion matrix
    truths = [t for t in LABELS if t in b["confusion"]]
    preds = [p for p in LABELS if any(p in b["confusion"][t] for t in truths)]
    mat = [[b["confusion"].get(t, {}).get(p, 0) for p in preds] for t in truths]
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.imshow(mat, cmap="Blues")
    ax.set_xticks(range(len(preds)), preds, rotation=40, ha="right")
    ax.set_yticks(range(len(truths)), truths)
    for i, row in enumerate(mat):
        for j, v in enumerate(row):
            if v:
                ax.text(j, i, v, ha="center", va="center", color="white" if v > max(map(max, mat)) / 2 else "black")
    ax.set_xlabel("predicted")
    ax.set_ylabel("true cause")
    ax.set_title("Confusion matrix")
    fig.tight_layout()
    paths.append(out / "confusion_matrix.png")
    fig.savefig(paths[-1], dpi=130)
    plt.close(fig)
    # reliability diagram
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color="grey", label="perfect calibration")
    bins = b["calibration"]["bins"]
    ax.plot([x["mean_confidence"] for x in bins], [x["accuracy"] for x in bins], "o-", label="NetCoop")
    for x in bins:
        ax.annotate(f"n={x['n']}", (x["mean_confidence"], x["accuracy"]), textcoords="offset points", xytext=(5, -12))
    ax.set_xlabel("stated confidence")
    ax.set_ylabel("actual accuracy")
    ax.set_title(f"Reliability (ECE {b['calibration']['ece']:.3f})")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.05)
    ax.legend()
    fig.tight_layout()
    paths.append(out / "calibration.png")
    fig.savefig(paths[-1], dpi=130)
    plt.close(fig)
    # ablation bars
    if "ablation" in b:
        names = list(b["ablation"])
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.barh(names[::-1], [b["ablation"][k]["accuracy"] * 100 for k in names[::-1]], color="#2a6fdb")
        ax.set_xlabel("accuracy (%)")
        ax.set_title("Multi-agent ablation")
        fig.tight_layout()
        paths.append(out / "ablation.png")
        fig.savefig(paths[-1], dpi=130)
        plt.close(fig)
    return paths


def save_all(b: dict, out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark.json").write_text(json.dumps(b, indent=2), encoding="utf-8")
    (out / "benchmark.md").write_text(render_markdown(b), encoding="utf-8")
    return [out / "benchmark.json", out / "benchmark.md", *save_plots(b, out)]
