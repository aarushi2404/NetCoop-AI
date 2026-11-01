import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, BarChart3, Bell, ChevronDown, FileCheck2, Loader2, Network, Search, Settings2, ShieldCheck, Upload, Users, X,
} from "lucide-react";
import { api } from "./api";
import type { Catalog, Diagnosis, FaultMode, IncidentSpec } from "./types";
import { cn, pretty } from "./util";
import TopologyMap from "./components/TopologyMap";
import SidePanel from "./components/SidePanel";
import { AgentsPanel, HypothesesPanel, IncidentHeader, KpiStrip } from "./components/Investigation";
import { Modal } from "./components/ui";
import ProofTraceView from "./views/ProofTraceView";
import AgentsView from "./views/AgentsView";
import BenchmarksView from "./views/BenchmarksView";
import TrustGuardView from "./views/TrustGuardView";

type View = "investigation" | "topology" | "agents" | "trustguard" | "prooftrace" | "benchmarks";
const NAV: { id: View; label: string; icon: typeof Activity }[] = [
  { id: "investigation", label: "Investigation", icon: Activity }, { id: "topology", label: "Topology", icon: Network },
  { id: "agents", label: "Agents", icon: Users }, { id: "trustguard", label: "TrustGuard", icon: ShieldCheck },
  { id: "prooftrace", label: "ProofTrace", icon: FileCheck2 },
  { id: "benchmarks", label: "Benchmarks", icon: BarChart3 },
];

function Logo() {
  return (
    <svg width="30" height="30" viewBox="0 0 32 32" className="glow-ember">
      <defs><linearGradient id="lg" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stopColor="#ffb07a" /><stop offset="1" stopColor="#e5530a" /></linearGradient></defs>
      <path d="M5 26V7l10 12.5V7h4v19L9 13.5V26z" fill="url(#lg)" />
      <circle cx="25" cy="8" r="3" fill="#ff6a1a" /><path d="M19 12l5-3" stroke="#ff6a1a" strokeWidth="2" />
    </svg>
  );
}

export default function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [spec, setSpec] = useState<IncidentSpec>({ source: "scenario", name: "hardware_failure", seed: 42, faults: {} });
  const [d, setD] = useState<Diagnosis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("investigation");
  const [device, setDevice] = useState<string | null>(null);
  const [focusHyp, setFocusHyp] = useState<string | null>(null);
  const [picker, setPicker] = useState(false);
  const [settings, setSettings] = useState(false);
  const [alerts, setAlerts] = useState(false);

  useEffect(() => { api.catalog().then(setCatalog).catch((e) => setError(String(e.message ?? e))); }, []);
  const run = useCallback(async (s: IncidentSpec) => {
    setLoading(true); setError(null);
    try { setD(await api.diagnose(s)); setDevice(null); setFocusHyp(null); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { run(spec); }, [spec, run]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPicker(true); } };
    window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k);
  }, []);

  const alertItems = useMemo(() => {
    if (!d) return [];
    const out: { tone: "alarm" | "ember"; text: string }[] = [];
    for (const [a, h] of Object.entries(d.report.agent_health)) if (h.status !== "ok") out.push({ tone: h.status === "recovered" ? "ember" : "alarm", text: `${pretty(a)} agent ${h.status}${h.error ? `: ${h.error}` : ""}` });
    for (const [dev, fl] of Object.entries(d.prooftrace.data_quality.quality_flags)) fl.forEach((f) => out.push({ tone: "ember", text: `${dev}: ${f.message}` }));
    for (const s of d.prooftrace.data_quality.stale_devices) out.push({ tone: "ember", text: `${s}: all telemetry stale, treated as silent` });
    if ((d.report.data_quality.records_rejected ?? 0) > 0) out.push({ tone: "ember", text: `${d.report.data_quality.records_rejected} input record(s) rejected as invalid` });
    const tg = d.report.trustguard;
    if (tg?.status === "unavailable") out.push({ tone: "alarm", text: `TrustGuard unavailable: findings not audited (${tg.reason})` });
    for (const f of tg?.flagged ?? []) out.push({ tone: "alarm", text: `TrustGuard flagged ${pretty(f.agent)}: ${f.subject} = ${f.reported} on ${f.device_id ?? "-"} (${f.reason_codes.join(", ")})` });
    if (!d.prooftrace.checks.verified) out.push({ tone: "alarm", text: "ProofTrace verification failed" });
    return out;
  }, [d]);

  const openProofTrace = (h?: string) => { setFocusHyp(h ?? null); setView("prooftrace"); };

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-ink-950/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1680px] items-center gap-3 px-4 py-3 xl:gap-6 xl:px-6">
          <div className="flex items-center gap-2.5"><Logo /><span className="text-[19px] font-semibold text-white">NetCoop AI</span></div>
          <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto xl:ml-6">
            {NAV.map(({ id, label, icon: I }) => (
              <button key={id} onClick={() => setView(id)} title={label} aria-label={label}
                className={cn("flex items-center gap-2 rounded-xl shrink-0 px-3 py-2 text-sm xl:px-4 font-medium transition",
                  view === id ? "bg-ember-500/15 text-white shadow-ember" : "text-slate-400 hover:bg-white/[0.04] hover:text-slate-200")}>
                <I size={17} className={view === id ? "text-ember-400" : ""} /><span className="hidden xl:inline">{label}</span>
              </button>
            ))}
          </nav>
          <button onClick={() => setPicker(true)} className="hidden items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-1.5 text-sm text-slate-300 hover:bg-white/[0.06] lg:flex">
            <span className="text-slate-500">{spec.source === "organizer" ? "organizer" : spec.source === "upload" ? "upload" : "scenario"}</span>
            <span className="max-w-[180px] truncate">{spec.name}</span><ChevronDown size={14} />
          </button>
          <button aria-label="Choose incident" title="Choose incident (Ctrl+K)" onClick={() => setPicker(true)} className="rounded-xl p-2 text-slate-300 hover:bg-white/10"><Search size={20} /></button>
          <div className="relative">
            <button aria-label="Alerts" onClick={() => setAlerts((a) => !a)} className="relative rounded-xl p-2 text-slate-300 hover:bg-white/10">
              <Bell size={20} />{alertItems.length > 0 && <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-ember-500 shadow-[0_0_8px_#ff6a1a]" />}
            </button>
            {alerts && (
              <div className="panel absolute right-0 top-12 w-96 animate-fadein p-3">
                <div className="mb-2 flex justify-between text-sm font-semibold text-slate-200">Alerts<span className="text-slate-500">{alertItems.length}</span></div>
                {alertItems.length === 0 ? <div className="py-3 text-sm text-slate-400">No agent failures or telemetry issues for this incident.</div> :
                  <div className="max-h-80 space-y-1.5 overflow-auto">{alertItems.map((a, i) => (
                    <div key={i} className={cn("rounded-lg border px-3 py-2 text-[12px]", a.tone === "alarm" ? "border-alarm-500/30 text-alarm-400" : "border-ember-500/25 text-ember-300")}>{a.text}</div>))}</div>}
              </div>
            )}
          </div>
          <button aria-label="Run settings" title="Run settings: seed, agent fault injection, remote agent" onClick={() => setSettings(true)}
            className="flex h-10 w-10 items-center justify-center rounded-full border border-white/10 bg-ink-800 text-slate-200 hover:border-ember-500/50">
            <Settings2 size={18} />
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-[1680px] px-6 py-6">
        {error && (
          <div className="mb-5 rounded-xl border border-alarm-500/40 bg-alarm-500/10 p-4 text-sm text-alarm-400">
            {error}. Is the API running? Start it with <code className="mono">python -m netcoop serve-api</code>.
          </div>
        )}
        {!d ? (
          <div className="flex h-[60vh] items-center justify-center text-slate-400">{loading ? <Loader2 className="animate-spin" size={28} /> : "No incident loaded."}</div>
        ) : (
          <div className={cn("transition-opacity", loading && "pointer-events-none opacity-60")}>
            {view === "investigation" && (
              <div className="grid gap-6 xl:grid-cols-[1fr_440px]">
                <div className="min-w-0 space-y-5">
                  <IncidentHeader d={d} />
                  <TopologyMap d={d} selected={device} onSelect={setDevice} height={420} />
                  <KpiStrip d={d} />
                  <div className="grid gap-5 lg:grid-cols-2">
                    <AgentsPanel d={d} />
                    <HypothesesPanel d={d} selected={focusHyp} onSelect={(h) => openProofTrace(h)} />
                  </div>
                </div>
                <div className="xl:sticky xl:top-24 xl:max-h-[calc(100vh-7.5rem)] xl:self-start xl:overflow-y-auto xl:rounded-2xl">
                  <SidePanel d={d} spec={spec} device={device} onCloseDevice={() => setDevice(null)} onOpenProofTrace={() => openProofTrace()} />
                </div>
              </div>
            )}
            {view === "topology" && (
              <div className="grid gap-6 xl:grid-cols-[1fr_440px]">
                <div className="panel min-w-0 p-2"><TopologyMap d={d} selected={device} onSelect={setDevice} height={680} /></div>
                <div className="xl:sticky xl:top-24 xl:max-h-[calc(100vh-7.5rem)] xl:self-start xl:overflow-y-auto xl:rounded-2xl">
                  <SidePanel d={d} spec={spec} device={device} onCloseDevice={() => setDevice(null)} onOpenProofTrace={() => openProofTrace()} />
                </div>
              </div>
            )}
            {view === "agents" && <AgentsView d={d} />}
            {view === "trustguard" && (
              <TrustGuardView d={d} enabled={spec.trustguard !== false} onOpenProofTrace={() => openProofTrace()}
                onToggle={(on) => setSpec({ ...spec, trustguard: on })}
                onDemo={() => setSpec({ source: "scenario", name: "adversarial_agent", seed: 42, faults: {}, trustguard: true, remote: spec.remote })} />)}
            {view === "prooftrace" && <ProofTraceView d={d} focus={focusHyp} />}
            {view === "benchmarks" && <BenchmarksView />}
          </div>
        )}
        {loading && d && <div className="fixed bottom-6 right-6 flex items-center gap-2 rounded-xl border border-white/10 bg-ink-900/90 px-4 py-2 text-sm text-slate-300"><Loader2 size={16} className="animate-spin" />Agents diagnosing…</div>}
      </main>

      <IncidentPicker open={picker} onClose={() => setPicker(false)} catalog={catalog} current={spec}
        onPick={(s) => { setSpec({ ...s, faults: spec.faults, remote: spec.remote, seed: s.seed ?? spec.seed, trustguard: spec.trustguard }); setPicker(false); }} />
      <SettingsModal open={settings} onClose={() => setSettings(false)} spec={spec} agents={catalog?.agents ?? []}
        onApply={(s) => { setSpec(s); setSettings(false); }} truth={d?.incident.ground_truth ?? null} />
    </div>
  );
}

function IncidentPicker({ open, onClose, catalog, current, onPick }: {
  open: boolean; onClose: () => void; catalog: Catalog | null; current: IncidentSpec; onPick: (s: IncidentSpec) => void;
}) {
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<"scenario" | "organizer">(current.source === "organizer" ? "organizer" : "scenario");
  const file = useRef<HTMLInputElement>(null);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const items = tab === "scenario"
    ? (catalog?.scenarios ?? []).map((s) => ({ name: s.name, sub: s.description }))
    : (catalog?.organizer ?? []).map((o) => ({ name: o.name, sub: `${o.devices} devices · ${o.records} records · label hidden from agents` }));
  const shown = items.filter((i) => (i.name + i.sub).toLowerCase().includes(q.toLowerCase()));
  return (
    <Modal open={open} onClose={onClose}>
      <div className="mb-3 flex items-center gap-2">
        <Search size={18} className="text-slate-500" />
        <input autoFocus className="flex-1 bg-transparent text-[15px] text-white outline-none placeholder:text-slate-500" placeholder="Search incidents…" value={q} onChange={(e) => setQ(e.target.value)} />
        <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-white/10"><X size={18} /></button>
      </div>
      <div className="mb-3 flex gap-2">
        {(["scenario", "organizer"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={cn("chip", tab === t ? "border-ember-500/60 bg-ember-500/10 text-ember-200" : "border-white/10 text-slate-400")}>
            {t === "scenario" ? "Internal scenarios" : "Organizer data"}</button>))}
        <button onClick={() => file.current?.click()} className="chip ml-auto border-white/10 text-slate-300 hover:border-white/30"><Upload size={12} />Upload JSON</button>
        <input ref={file} type="file" accept=".json,application/json" hidden onChange={async (e) => {
          const f = e.target.files?.[0]; if (!f) return;
          try { onPick({ source: "upload", name: f.name, raw: JSON.parse(await f.text()) }); setUploadErr(null); }
          catch (err) { setUploadErr(`Not valid JSON: ${err instanceof Error ? err.message : err}`); }
          e.target.value = "";
        }} />
      </div>
      {uploadErr && <div className="mb-2 text-sm text-alarm-400">{uploadErr}</div>}
      <div className="space-y-1">
        {shown.map((i) => (
          <button key={i.name} onClick={() => onPick({ source: tab, name: i.name })}
            className={cn("flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-left hover:bg-white/[0.05]", current.name === i.name && "bg-ember-500/10")}>
            <span className="text-sm text-slate-100">{i.name}</span><span className="ml-4 truncate text-xs text-slate-500">{i.sub}</span>
          </button>))}
        {shown.length === 0 && <div className="p-4 text-center text-sm text-slate-500">{tab === "organizer" ? "No organizer incidents. Run `python -m netcoop organizer-eval`." : "No match."}</div>}
      </div>
    </Modal>
  );
}

function SettingsModal({ open, onClose, spec, agents, onApply, truth }: {
  open: boolean; onClose: () => void; spec: IncidentSpec; agents: string[]; onApply: (s: IncidentSpec) => void; truth: Record<string, unknown> | null;
}) {
  const [s, setS] = useState(spec);
  const [reveal, setReveal] = useState(false);
  useEffect(() => { if (open) { setS(spec); setReveal(false); } }, [open, spec]);
  return (
    <Modal open={open} onClose={onClose}>
      <h3 className="text-lg font-semibold text-white">Run settings</h3>
      <p className="mb-4 text-sm text-slate-400">Re-runs the full multi-agent pipeline on the server.</p>
      <div className="space-y-4 text-sm">
        {s.source === "scenario" && s.name === "adversarial_agent" && (
          <div className="rounded-lg border border-ember-500/30 bg-ember-500/[0.07] px-3 py-2 text-[12px] text-ember-200">
            This scenario sets the performance agent to <b>adversarial</b> by itself (its simulation block).</div>)}
        {s.source === "scenario" && (
          <label className="block"><span className="eyebrow">Random seed</span>
            <input type="number" className="input mt-1" value={s.seed ?? 42} onChange={(e) => setS({ ...s, seed: +e.target.value })} /></label>)}
        <div>
          <span className="eyebrow">Agent fault injection (resilience demo)</span>
          {agents.map((a) => (
            <div key={a} className="mt-2 flex items-center gap-3">
              <span className="w-40 text-slate-300">{pretty(a)}</span>
              {(["healthy", "transient", "permanent", "adversarial"] as FaultMode[]).map((m) => (
                <button key={m} onClick={() => setS({ ...s, faults: { ...s.faults, [a]: m } })}
                  className={cn("chip", (s.faults?.[a] ?? "healthy") === m ? (m === "healthy" ? "border-teal-400/50 text-teal-300" : "border-alarm-500/50 text-alarm-400") : "border-white/10 text-slate-500")}>{m}</button>))}
            </div>))}
        </div>
        <label className="flex items-center gap-2 text-slate-300">
          <input type="checkbox" className="accent-orange-500" checked={s.trustguard !== false} onChange={(e) => setS({ ...s, trustguard: e.target.checked })} />
          TrustGuard: audit specialist findings before correlation</label>
        <label className="block"><span className="eyebrow">Remote connectivity agent URL (optional)</span>
          <input className="input mt-1" placeholder="http://127.0.0.1:8765  (python -m netcoop serve-remote)" value={s.remote ?? ""} onChange={(e) => setS({ ...s, remote: e.target.value })} /></label>
        {truth && (
          <div className="panel-inner p-3">
            <button className="text-xs text-ember-300 underline-offset-2 hover:underline" onClick={() => setReveal((r) => !r)}>{reveal ? "Hide" : "Reveal"} ground truth (never shown to the agents)</button>
            {reveal && <pre className="mono mt-2 text-slate-300">{JSON.stringify(truth, null, 2)}</pre>}
          </div>)}
        <div className="flex justify-end gap-2 pt-2">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-ember" onClick={() => onApply(s)}>Re-run diagnosis</button>
        </div>
      </div>
    </Modal>
  );
}
