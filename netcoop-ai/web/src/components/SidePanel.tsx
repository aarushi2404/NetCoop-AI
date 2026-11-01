import { useEffect, useState } from "react";
import {
  AlertTriangle, ArrowRight, Check, CheckCircle2, CircleDashed, Database, Fingerprint, Layers3, Loader2, Network,
  ShieldAlert, ShieldCheck, ThumbsDown, ThumbsUp, Wrench, X,
} from "lucide-react";
import { api } from "../api";
import type { Diagnosis, IncidentSpec, Remediation, VerifyResult, WhatIfResult } from "../types";
import { cn, fmt, pct, pretty } from "../util";
import { HYP_ICON } from "./Investigation";
import { Bar, Ring, Tabs } from "./ui";

type Tab = "investigation" | "prooftrace" | "remediation";

export default function SidePanel({ d, spec, device, onCloseDevice, onOpenProofTrace }: {
  d: Diagnosis; spec: IncidentSpec; device: string | null; onCloseDevice: () => void; onOpenProofTrace: () => void;
}) {
  const [tab, setTab] = useState<Tab>("investigation");
  return (
    <aside className="panel flex flex-col gap-4 p-4">
      <Tabs value={tab} onChange={setTab} items={[
        { id: "investigation", label: "Investigation" }, { id: "prooftrace", label: "ProofTrace" },
        { id: "remediation", label: "Remediation" }]} />
      {device ? <DeviceCard d={d} spec={spec} id={device} onClose={onCloseDevice} />
        : tab === "investigation" ? <InvestigationTab d={d} onOpen={onOpenProofTrace} />
          : tab === "prooftrace" ? <VerifyTab d={d} spec={spec} onOpen={onOpenProofTrace} />
            : <RemediationTab d={d} spec={spec} />}
    </aside>
  );
}

function Step({ icon: I, title, detail, state, last }: { icon: typeof Database; title: string; detail: string; state: "ok" | "warn" | "fail"; last?: boolean }) {
  return (
    <div className="relative flex gap-3">
      {!last && <div className={cn("absolute left-[21px] top-12 h-[calc(100%-36px)] w-px", state === "ok" ? "bg-ember-500/50" : "bg-white/10")} />}
      <div className={cn("z-10 flex h-11 w-11 shrink-0 items-center justify-center rounded-full border bg-ink-900",
        last ? (state === "ok" ? "border-ember-500 text-ember-400 shadow-ember" : "border-slate-500 text-slate-300") : "border-white/10 text-slate-300")}>
        {last && state === "ok" ? <CheckCircle2 size={22} /> : <I size={20} />}
      </div>
      <div className="panel-inner mb-2 flex flex-1 items-center justify-between gap-2 px-4 py-3">
        <div>
          <div className="text-[14px] font-medium text-slate-100">{title}</div>
          <div className={cn("text-[12px]", last && state === "ok" ? "text-ember-400" : "text-slate-400")}>{detail}</div>
        </div>
        {state === "ok" ? <Check size={18} className="text-teal-400" /> : state === "warn"
          ? <AlertTriangle size={17} className="text-ember-400" /> : <X size={17} className="text-alarm-400" />}
      </div>
    </div>
  );
}

function InvestigationTab({ d, onOpen }: { d: Diagnosis; onOpen: () => void }) {
  const r = d.report, t = d.prooftrace;
  const sel = t.hypotheses?.find((h) => h.verdict === "selected" || h.verdict === "leading (not committed)");
  const I = (sel && HYP_ICON[sel.hypothesis]) || CircleDashed;
  const key = sel?.expected_signals.find((e) => e.state === "present") ?? null;
  const contra = sel?.contradicting.length ?? 0;
  const specialists = (t.agents ?? []).filter((a) => a.findings_message_id);
  const voters = new Set(sel?.votes.map((v) => v.agent));
  const failed = Object.entries(r.agent_health).filter(([, h]) => h.status === "failed" || h.status === "incompatible");
  const committed = r.status === "diagnosed" || r.status === "tentative";
  const why = r.abstention ?? r.hedge;
  return (
    <div className="flex flex-col gap-4 animate-fadein">
      <div>
        <h3 className="mb-3 text-[15px] font-semibold text-slate-100">Diagnostic Conclusion</h3>
        <div className="panel-inner flex items-center gap-4 p-4">
          <div className="rounded-xl border border-ember-500/30 bg-ember-500/10 p-2.5 text-ember-400"><I size={26} /></div>
          <div className="flex-1 text-[15px] font-medium leading-snug text-white">{r.suspected_root_cause}</div>
          <Ring value={r.confidence} tone={r.status === "healthy" ? "#34d6c4" : r.status === "insufficient_evidence" ? "#8b93a1" : "#ff6a1a"} />
        </div>
      </div>
      <div>
        <h3 className="mb-3 text-[15px] font-semibold text-slate-100">Evidence Trace</h3>
        <Step icon={Database} title="Telemetry"
          detail={key ? `${pretty(key.signal)} (${fmt(key.value)}) · ${r.data_quality.records_accepted ?? 0} records`
            : `${r.data_quality.records_accepted ?? 0} records accepted, ${r.data_quality.records_rejected ?? 0} rejected`}
          state={(r.data_quality.records_rejected ?? 0) > 0 ? "warn" : "ok"} />
        <Step icon={Network} title="Agent Findings"
          detail={failed.length ? `${failed.map(([a]) => pretty(a)).join(", ")} unavailable` :
            `Correlated by ${specialists.length} specialist agents${voters.size ? `, ${voters.size} supporting` : ""}${r.conflicts_resolved?.length ? `, ${r.conflicts_resolved.length} conflict resolved` : ""}`}
          state={failed.length ? "warn" : "ok"} />
        <Step icon={Layers3} title="Evidence Correlation"
          detail={`Consistent across ${t.evidence?.length ?? 0} signals, ${contra} contradiction${contra === 1 ? "" : "s"}`}
          state={contra ? "warn" : "ok"} />
        <Step icon={ShieldCheck} last
          title={committed ? "Diagnosis Verified" : r.status === "healthy" ? "Healthy Verified" : "Not Committed"}
          detail={`${t.checks.passed}/${t.checks.total} ProofTrace checks · ${committed ? `Root cause: ${pretty(r.root_cause_type)}` : r.status === "healthy" ? "no fault" : "insufficient evidence"}`}
          state={t.checks.verified && (committed || r.status === "healthy") ? "ok" : t.checks.verified ? "warn" : "fail"} />
      </div>
      {why && (
        <div className="rounded-xl border border-ember-500/25 bg-ember-500/[0.06] p-3 text-[13px]">
          <div className="mb-1 font-medium text-ember-300">Why the system does not fully commit</div>
          <p className="text-slate-300">{why.summary}</p>
        </div>
      )}
      <button className="btn-ember w-full py-3 text-[15px]" onClick={onOpen}>View Full ProofTrace <ArrowRight size={17} /></button>
    </div>
  );
}

const TAMPER = [
  { id: "none", label: "Untouched" }, { id: "raw", label: "Alter a raw value" },
  { id: "vote", label: "Change a vote" }, { id: "drop", label: "Delete a message" },
  { id: "audit", label: "Alter a TrustGuard record" },
] as const;

function VerifyTab({ d, spec, onOpen }: { d: Diagnosis; spec: IncidentSpec; onOpen: () => void }) {
  const [res, setRes] = useState<VerifyResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (t: (typeof TAMPER)[number]["id"]) => {
    setBusy(t);
    try { setRes(await api.verify(spec, t)); } finally { setBusy(null); }
  };
  const c = res ?? { ...d.prooftrace.checks, tamper: "none", what: "nothing changed" };
  const s = d.prooftrace.sensitivity;
  return (
    <div className="flex flex-col gap-4 animate-fadein">
      <div className={cn("rounded-xl border p-4", c.verified ? "border-teal-400/30 bg-teal-400/[0.06]" : "border-alarm-500/40 bg-alarm-500/10")}>
        <div className="flex items-center gap-3">
          {c.verified ? <ShieldCheck className="text-teal-300" /> : <ShieldAlert className="text-alarm-400" />}
          <div>
            <div className="text-lg font-semibold text-white">{c.passed}/{c.total} checks {c.verified ? "VERIFIED" : "FAILED"}</div>
            <div className="text-xs text-slate-400">Tampered: {c.what}</div>
          </div>
        </div>
        {!c.verified && (
          <ul className="mt-3 space-y-1 text-[12px] text-alarm-400">
            {c.failures.slice(0, 5).map((f, i) => <li key={i}>✗ {f.check} [{f.target}] {f.detail}</li>)}
          </ul>
        )}
      </div>
      <div>
        <div className="eyebrow mb-2">Tamper and re-verify (runs on the server)</div>
        <div className="grid grid-cols-2 gap-2">
          {TAMPER.map((t) => (
            <button key={t.id} className={cn("btn-ghost text-xs", c.tamper === t.id && "border-ember-500/60 text-ember-300")} onClick={() => run(t.id)}>
              {busy === t.id && <Loader2 size={14} className="animate-spin" />}{t.label}
            </button>
          ))}
        </div>
      </div>
      <div className="panel-inner p-3 text-xs">
        <div className="flex items-center gap-2 text-slate-300"><Fingerprint size={15} /> Log chain SHA-256</div>
        <div className="mono mt-1 break-all text-slate-400">{d.prooftrace.integrity.chain_sha256}</div>
        <div className="mt-1 text-slate-500">{d.prooftrace.integrity.message_count} protocol messages hashed</div>
      </div>
      {s && (
        <div>
          <div className="eyebrow mb-2">Decisive measurements ({s.decisive.length})</div>
          {s.decisive.length === 0 ? <div className="text-xs text-slate-400">No single-measurement change flips this conclusion.</div> :
            s.decisive.map((x) => <div key={x} className="mb-1.5 rounded-lg border border-ember-500/20 bg-ember-500/[0.05] px-3 py-2 text-[12px] text-slate-300">{x}</div>)}
        </div>
      )}
      <button className="btn-ember w-full" onClick={onOpen}>Open full ProofTrace <ArrowRight size={16} /></button>
    </div>
  );
}

function RemediationTab({ d, spec }: { d: Diagnosis; spec: IncidentSpec }) {
  const r = d.report;
  const ranked = (r.hypothesis_ranking ?? []).map((x) => x.hypothesis);
  const [hyp, setHyp] = useState<string>(r.root_cause_type ?? ranked[0] ?? "");
  const [eff, setEff] = useState(1);
  const [res, setRes] = useState<Remediation | null>(null);
  const [busy, setBusy] = useState(false);
  const [decisions, setDecisions] = useState<Record<number, "approved" | "rejected">>({});
  useEffect(() => { setRes(null); setDecisions({}); setHyp(r.root_cause_type ?? ranked[0] ?? ""); }, [d]); // eslint-disable-line react-hooks/exhaustive-deps
  const rc = d.prooftrace.remediation_check;
  const apply = async () => { setBusy(true); try { setRes(await api.remediate(spec, hyp || null, eff)); } finally { setBusy(false); } };
  const tone = res && { resolved: "border-teal-400/40 bg-teal-400/[0.07] text-teal-300",
    partially_resolved: "border-ember-500/40 bg-ember-500/[0.07] text-ember-300",
    unresolved: "border-alarm-500/40 bg-alarm-500/10 text-alarm-400" }[res.outcome];
  return (
    <div className="flex flex-col gap-4 animate-fadein text-sm">
      <div>
        <div className="eyebrow mb-2">Recommended actions (human review)</div>
        {r.recommended_actions.map((a, i) => (
          <div key={i} className="mb-1.5 flex items-start gap-2 rounded-lg bg-white/[0.03] p-2.5">
            <span className="flex-1 text-[13px] text-slate-300">{a}</span>
            <button title="Approve" onClick={() => setDecisions({ ...decisions, [i]: "approved" })}
              className={cn("rounded-md p-1.5", decisions[i] === "approved" ? "bg-teal-400/20 text-teal-300" : "text-slate-500 hover:text-teal-300")}><ThumbsUp size={14} /></button>
            <button title="Reject" onClick={() => setDecisions({ ...decisions, [i]: "rejected" })}
              className={cn("rounded-md p-1.5", decisions[i] === "rejected" ? "bg-alarm-500/20 text-alarm-400" : "text-slate-500 hover:text-alarm-400")}><ThumbsDown size={14} /></button>
          </div>
        ))}
      </div>
      {rc?.compared && (
        <div className="panel-inner p-3 text-[12px]">
          <div className="mb-2 text-slate-300">{rc.verdict}</div>
          {Object.entries(rc.results ?? {}).map(([h, x]) => (
            <div key={h} className="flex items-center justify-between border-t border-white/5 py-1.5">
              <span className="text-slate-300">fix for {pretty(h)}</span>
              <span className={x.outcome === "resolved" ? "text-teal-300" : "text-alarm-400"}>{x.outcome.replace("_", " ")}</span>
            </div>
          ))}
        </div>
      )}
      <div className="space-y-3">
        <div className="eyebrow">Counterfactual fix (dry run)</div>
        <select className="input" value={hyp} onChange={(e) => setHyp(e.target.value)}>
          {Object.keys(d.prooftrace.remediation_check?.results ?? {}).concat(
            ["link_congestion", "interface_fault", "weak_wifi", "device_overload", "hardware_failure", "dns_failure", "dhcp_failure"])
            .filter((v, i, a) => a.indexOf(v) === i).map((h) => <option key={h} value={h}>{pretty(h)}{h === r.root_cause_type ? " (diagnosed)" : ""}</option>)}
        </select>
        <label className="flex items-center gap-3 text-xs text-slate-400">Efficacy
          <input type="range" min={0} max={1} step={0.1} value={eff} onChange={(e) => setEff(+e.target.value)} className="flex-1 accent-ember-500" />
          <span className="mono w-9 text-right text-slate-200">{eff.toFixed(1)}</span>
        </label>
        <button className="btn-ember w-full" onClick={apply} disabled={busy || !(r.affected_devices.length)}>
          {busy ? <Loader2 size={16} className="animate-spin" /> : <Wrench size={16} />} Apply fix & re-diagnose
        </button>
      </div>
      {res && !res.simulated && <div className="text-slate-400">{res.reason}</div>}
      {res?.simulated && (
        <div className="space-y-3 animate-fadein">
          <div className={cn("rounded-xl border p-3", tone)}>
            <div className="font-semibold uppercase tracking-wide">{res.outcome.replace("_", " ")}</div>
            <div className="mt-1 text-[12px] text-slate-300">{res.explanation}</div>
          </div>
          <div className="grid grid-cols-2 gap-2 text-center">
            <div className="panel-inner p-2"><div className="text-[11px] text-slate-500">Before</div><div className="text-slate-100">{pretty(res.before.status)}</div><div className="text-[11px] text-slate-500">{pct(res.before.confidence)}</div></div>
            <div className="panel-inner p-2"><div className="text-[11px] text-slate-500">After</div><div className="text-slate-100">{pretty(res.after.status)}</div><div className="text-[11px] text-slate-500">{pct(res.after.confidence)}</div></div>
          </div>
          {res.devices.map((x) => (
            <div key={x.device_id} className="panel-inner p-3">
              <div className="mb-1 flex justify-between text-[12px]"><span className="font-medium text-slate-200">{x.device_id}</span><span className="text-slate-500">{x.role}</span></div>
              <div className="flex items-center gap-2 text-[11px] text-slate-400"><span className="w-12">before</span><Bar value={x.before.health_index} tone="alarm" /><span className="mono w-9">{x.before.health_index.toFixed(2)}</span></div>
              <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-400"><span className="w-12">after</span><Bar value={x.after.health_index} tone="teal" /><span className="mono w-9">{x.after.health_index.toFixed(2)}</span></div>
              {x.after.active_signals.length > 0 && <div className="mt-1 text-[11px] text-alarm-400">still: {x.after.active_signals.join(", ")}</div>}
            </div>
          ))}
          <div>
            <div className="eyebrow mb-1.5">Expected improvement</div>
            {res.expected_improvements.map((e, i) => (
              <div key={i} className="flex items-center gap-2 py-0.5 text-[12px]">
                {e.achieved ? <Check size={14} className="text-teal-400" /> : <X size={14} className="text-alarm-400" />}
                <span className="text-slate-300">{e.metric}</span><span className="mono text-slate-500">{fmt(e.before)} → {fmt(e.after)}</span>
              </div>
            ))}
          </div>
          <div className="text-[11px] text-slate-500">{res.note}</div>
        </div>
      )}
    </div>
  );
}

const METRIC_CHOICES = ["cpu_utilization_pct", "memory_utilization_pct", "interface_errors", "link_flaps", "link_utilization_pct",
  "queue_drops", "latency_ms", "jitter_ms", "packet_loss_pct", "wifi_rssi_dbm", "retransmission_pct", "dns_failure_pct", "dhcp_failure_pct"];

function DeviceCard({ d, spec, id, onClose }: { d: Diagnosis; spec: IncidentSpec; id: string; onClose: () => void }) {
  const dev = d.devices[id];
  const h = d.health?.[id];
  const [metric, setMetric] = useState(METRIC_CHOICES.find((m) => dev?.metrics[m] !== undefined) ?? "latency_ms");
  const [val, setVal] = useState<string>("");
  const [res, setRes] = useState<WhatIfResult | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setRes(null); setVal(dev?.metrics[metric] !== undefined ? String(dev.metrics[metric]) : ""); }, [id, metric]); // eslint-disable-line react-hooks/exhaustive-deps
  const ev = (d.prooftrace.evidence ?? []).filter((e) => e.device_id === id);
  if (!dev) return (
    <div className="space-y-3 text-sm"><Head id={id} onClose={onClose} sub="no telemetry received" />
      <p className="text-slate-400">This device is in the topology but sent no (fresh) telemetry. It is listed as a possible silent outage.</p></div>);
  return (
    <div className="space-y-4 animate-fadein text-sm">
      <Head id={id} onClose={onClose} sub={`${dev.role ?? "device"} · ${dev.status} · parent ${dev.parent ?? "none"}`} />
      {h && (
        <div className="panel-inner p-3">
          <div className="mb-1 flex justify-between text-xs text-slate-400"><span>Health index</span><span className="mono text-slate-200">{h.health_index.toFixed(2)}</span></div>
          <Bar value={h.health_index} tone={h.health_index < 0.5 ? "alarm" : "teal"} />
          {h.active_signals.length > 0 && <div className="mt-2 text-xs text-alarm-400">Alarms: {h.active_signals.join(", ")}</div>}
          {Object.keys(h.elevated_signals).length > 0 && <div className="mt-1 text-xs text-ember-300">Elevated: {Object.entries(h.elevated_signals).map(([s, v]) => `${s} ${v.toFixed(2)}`).join(", ")}</div>}
        </div>
      )}
      <div>
        <div className="eyebrow mb-1.5">Telemetry (canonical, {dev.samples} samples)</div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1">
          {Object.entries(dev.metrics).map(([k, v]) => (
            <div key={k} className="flex justify-between border-b border-white/5 py-1 text-[12px]"><span className="text-slate-400">{k}</span><span className="mono text-slate-200">{fmt(v)}</span></div>
          ))}
        </div>
      </div>
      {dev.quality.length > 0 && (
        <div className="rounded-lg border border-ember-500/30 bg-ember-500/[0.06] p-2.5 text-[12px] text-ember-300">
          {dev.quality.map((q, i) => <div key={i}>⚠ {q.message}</div>)}
        </div>
      )}
      {ev.length > 0 && <div className="text-[12px] text-slate-400">{ev.length} evidence item(s) in the ProofTrace come from this device.</div>}
      <div className="space-y-2 border-t border-white/5 pt-3">
        <div className="eyebrow">What if… (re-runs all agents)</div>
        <div className="flex gap-2">
          <select className="input flex-1" value={metric} onChange={(e) => setMetric(e.target.value)}>
            {METRIC_CHOICES.map((m) => <option key={m}>{m}</option>)}
          </select>
          <input className="input w-24" value={val} onChange={(e) => setVal(e.target.value)} />
        </div>
        <button className="btn-ghost w-full" disabled={busy || val === ""} onClick={async () => {
          setBusy(true); try { setRes(await api.whatif(spec, id, metric, Number(val))); } finally { setBusy(false); }
        }}>{busy && <Loader2 size={14} className="animate-spin" />}Re-diagnose</button>
        {res && (
          <div className={cn("rounded-lg border p-3 text-[12px]", res.changed ? "border-ember-500/40 bg-ember-500/[0.07]" : "border-white/10")}>
            <div className="font-medium text-slate-200">{res.changed ? "Conclusion changes" : "Conclusion holds"}</div>
            <div className="mt-1 text-slate-400">{metric}: {fmt(res.from)} → {fmt(res.to)}</div>
            <div className="mt-1 text-slate-300">{res.after.suspected_root_cause} ({pct(res.after.confidence ?? 0)})</div>
          </div>
        )}
      </div>
    </div>
  );
}

const Head = ({ id, sub, onClose }: { id: string; sub: string; onClose: () => void }) => (
  <div className="flex items-start justify-between">
    <div><div className="eyebrow">Device</div><div className="text-lg font-semibold text-white">{id}</div><div className="text-xs text-slate-400">{sub}</div></div>
    <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10" aria-label="Close device"><X size={18} /></button>
  </div>
);
