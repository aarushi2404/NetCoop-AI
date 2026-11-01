import { useState } from "react";
import {
  AlertTriangle, BrainCircuit, Cable, CheckCircle2, CircleDashed, Cpu, Database, FileText, GitMerge, Layers3,
  Monitor, Network, ShieldCheck, Wifi, XCircle,
} from "lucide-react";
import type { AgentTrace, Diagnosis } from "../types";
import { cn, fmt, headline, pct, pretty } from "../util";
import { Bar, Modal, Panel } from "./ui";

export const HYP_ICON: Record<string, typeof Cpu> = {
  hardware_failure: Cpu, device_overload: Layers3, link_congestion: Network, interface_fault: Cable,
  weak_wifi: Wifi, dns_failure: Database, dhcp_failure: GitMerge,
};

export function IncidentHeader({ d }: { d: Diagnosis }) {
  const h = headline(d);
  const badge = {
    alarm: "border-alarm-500/60 bg-alarm-500/10 text-alarm-400 shadow-[0_0_24px_-6px_rgba(239,59,51,.8)]",
    ember: "border-ember-500/60 bg-ember-500/10 text-ember-300", teal: "border-teal-400/50 bg-teal-400/10 text-teal-300",
    slate: "border-slate-400/40 bg-white/5 text-slate-300",
  }[h.tone];
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <div className="eyebrow">Incident&nbsp;&nbsp;{d.report.incident_id}</div>
        <h1 className="mt-2 text-[34px] font-semibold leading-tight tracking-tight text-white">
          {h.title} <span className={cn(h.tone === "teal" ? "text-teal-300" : h.tone === "slate" ? "text-slate-400" : "text-ember-500")}>{h.accent}</span>
        </h1>
        <p className="mt-1 text-[15px] text-slate-400">
          Automated multi-agent diagnosis with verifiable evidence · <span className="text-slate-300">{d.incident.data_origin}</span>
        </p>
      </div>
      <div className={cn("mt-6 flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-bold tracking-wider", badge)}>
        <AlertTriangle size={17} /> {h.severity}
      </div>
    </div>
  );
}

export function KpiStrip({ d }: { d: Diagnosis }) {
  const r = d.report;
  const parents = new Set(r.affected_devices.map((x) => d.devices[x]?.parent ?? x));
  const items = [
    { icon: Layers3, n: r.affected_devices.length ? parents.size : 0, label: "Affected Segments" },
    { icon: Monitor, n: r.affected_devices.length, label: "Affected Devices" },
    { icon: FileText, n: d.prooftrace.evidence?.length ?? 0, label: "Evidence Points" },
    { icon: ShieldCheck, n: pct(r.confidence), label: `Confidence (${pretty(r.confidence_category)})` },
  ];
  return (
    <div className="panel grid grid-cols-2 divide-white/[0.06] md:grid-cols-4 md:divide-x">
      {items.map(({ icon: I, n, label }, i) => (
        <div key={label} className="flex items-center gap-4 px-6 py-4">
          <div className={cn("rounded-xl border p-2.5", i === 3 ? "border-violet-400/20 bg-violet-400/10 text-violet-300" : i === 2 ? "border-teal-400/20 bg-teal-400/10 text-teal-300" : "border-ember-500/25 bg-ember-500/10 text-ember-400")}>
            <I size={22} />
          </div>
          <div>
            <div className="text-2xl font-semibold text-white">{n}</div>
            <div className="text-[13px] text-slate-400">{label}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

const AGENT_ICON: Record<string, typeof Cpu> = {
  performance_agent: Network, infrastructure_agent: Cpu, connectivity_agent: Wifi,
  correlation_agent: GitMerge, reporting_agent: BrainCircuit,
};

export function AgentsPanel({ d }: { d: Diagnosis }) {
  const [open, setOpen] = useState<AgentTrace | null>(null);
  const agents = d.prooftrace.agents ?? Object.keys(d.cards).map((a) => ({
    agent: a, transport: d.cards[a].transport, health: d.report.agent_health[a]?.status ?? "ok",
  } as AgentTrace));
  const health = d.report.agent_health;
  const active = Object.keys(d.cards).filter((a) => (health[a]?.status ?? "ok") !== "failed" && health[a]?.status !== "incompatible").length;
  return (
    <Panel title="Multi-Agent Investigation"
      right={<span className="chip border-teal-400/30 bg-teal-400/10 text-teal-300"><span className="h-1.5 w-1.5 rounded-full bg-teal-400" />{active} Agents Active</span>}>
      <div className="relative flex items-start justify-between gap-2">
        <div className="absolute left-8 right-8 top-8 h-px bg-gradient-to-r from-teal-400/30 via-white/10 to-ember-500/30" />
        {agents.map((a) => {
          const I = AGENT_ICON[a.agent] ?? BrainCircuit;
          const st = health[a.agent]?.status ?? a.health ?? "ok";
          const ok = st === "ok" || st === "recovered";
          const contrib = a.leave_one_out?.contribution;
          return (
            <button key={a.agent} onClick={() => setOpen(a)} className="group relative z-10 flex w-24 flex-col items-center gap-2 text-center">
              <div className={cn("flex h-16 w-16 items-center justify-center rounded-full border-2 bg-ink-900 transition group-hover:scale-105",
                !ok ? "border-alarm-500/70 text-alarm-400" : contrib === "decisive" ? "border-ember-500 text-ember-300 shadow-ember"
                  : "border-teal-400/60 text-teal-300 shadow-[0_0_18px_-4px_rgba(52,214,196,.6)]")}>
                <I size={26} />
              </div>
              <div className="text-[13px] font-medium leading-tight text-slate-200">{pretty(a.agent)}<br />Agent</div>
              {ok ? <CheckCircle2 size={15} className="text-teal-400" /> : <XCircle size={15} className="text-alarm-400" />}
              {contrib && <span className="text-[10px] uppercase tracking-wider text-slate-500">{contrib.split(" ")[0]}</span>}
              {a.transport === "http" && <span className="chip border-violet-400/30 text-violet-300">HTTP</span>}
            </button>
          );
        })}
      </div>
      <Modal open={!!open} onClose={() => setOpen(null)}>
        {open && <AgentDetail d={d} a={open} />}
      </Modal>
    </Panel>
  );
}

export function AgentDetail({ d, a }: { d: Diagnosis; a: AgentTrace }) {
  const card = d.cards[a.agent];
  const h = d.report.agent_health[a.agent];
  return (
    <div className="space-y-4 text-sm">
      <div>
        <div className="eyebrow">{a.transport} agent</div>
        <h3 className="mt-1 text-xl font-semibold text-white">{a.agent}</h3>
        <p className="mt-1 text-slate-400">{card?.description}</p>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Info k="Health" v={`${h?.status ?? a.health} (${h?.attempts ?? 1} attempt(s))`} />
        <Info k="Protocol" v={card?.protocol_versions.join(", ") || "none"} />
        <Info k="Accepts" v={card?.accepts.join(", ")} />
        <Info k="Produces" v={card?.produces.join(", ")} />
        {a.on_root_device?.top_vote && <Info k="Its top vote on the blamed device" v={`${a.on_root_device.top_vote.hypothesis} ${a.on_root_device.top_vote.vote.toFixed(2)}`} />}
        {a.leave_one_out && <Info k="Without it (leave-one-out)" v={`${a.leave_one_out.status} / ${a.leave_one_out.hypothesis ?? "-"} ${a.leave_one_out.confidence.toFixed(2)} → ${a.leave_one_out.contribution}`} />}
      </div>
      {h?.error && <div className="rounded-lg border border-alarm-500/30 bg-alarm-500/10 p-3 text-alarm-400">{h.error}</div>}
      {a.on_root_device && Object.keys(a.on_root_device.signals).length > 0 && (
        <div>
          <div className="eyebrow mb-2">Signals it observed on the blamed device</div>
          {Object.entries(a.on_root_device.signals).map(([s, v]) => (
            <div key={s} className="mb-1.5 flex items-center gap-3"><span className="w-36 text-slate-300">{s}</span><Bar value={v} /><span className="mono w-10 text-right">{v.toFixed(2)}</span></div>
          ))}
        </div>
      )}
      {card?.negotiation && (
        <div><div className="eyebrow mb-2">Format negotiation</div>
          <pre className="mono max-h-56 overflow-auto rounded-lg bg-black/40 p-3 text-slate-300">{JSON.stringify(card.negotiation, null, 2)}</pre></div>
      )}
    </div>
  );
}

export const Info = ({ k, v }: { k: string; v: unknown }) => (
  <div className="panel-inner p-3"><div className="text-[11px] uppercase tracking-wider text-slate-500">{k}</div><div className="mt-1 text-slate-200">{fmt(v)}</div></div>
);

export function HypothesesPanel({ d, selected, onSelect, limit = 3 }: {
  d: Diagnosis; selected: string | null; onSelect: (h: string) => void; limit?: number;
}) {
  const hyps = (d.prooftrace.hypotheses ?? []).filter((h) => h.score > 0 || h.verdict === "selected").slice(0, limit);
  return (
    <Panel title="Competing Hypotheses" right={<span className="text-xs text-slate-500">click to inspect</span>}>
      {hyps.length === 0 ? <div className="text-sm text-slate-400">{d.report.status === "healthy" ? "No fault: no hypothesis was raised." : "No agent raised a hypothesis."}</div> : (
        <div className="space-y-1.5">
          {hyps.map((h, i) => {
            const I = HYP_ICON[h.hypothesis] ?? CircleDashed;
            const top = i === 0;
            return (
              <button key={h.hypothesis} onClick={() => onSelect(h.hypothesis)}
                className={cn("flex w-full items-center gap-4 rounded-xl border px-4 py-3 text-left transition",
                  top ? "border-ember-500/60 bg-ember-500/[0.08] shadow-ember" : "border-transparent hover:border-white/10 hover:bg-white/[0.03]",
                  selected === h.hypothesis && !top && "border-white/20 bg-white/[0.05]")}>
                <I size={22} className={top ? "text-ember-400" : "text-slate-300"} />
                <div className="w-40 text-[14px] text-slate-100">{pretty(h.hypothesis)}</div>
                <Bar value={h.score} tone={top ? "ember" : "slate"} className="flex-1" />
                <div className="mono w-12 text-right text-slate-200">{h.score.toFixed(2)}</div>
              </button>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
