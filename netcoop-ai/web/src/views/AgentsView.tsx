import { useState } from "react";
import type { BusMessage, Diagnosis } from "../types";
import { cn, pretty } from "../util";
import { AgentDetail } from "../components/Investigation";
import { Panel } from "../components/ui";

const LANES = ["orchestrator", "performance_agent", "infrastructure_agent", "connectivity_agent", "correlation_agent", "reporting_agent"];
const PHASE: Record<string, string> = {
  capability: "#8b93a1", analyze: "#34d6c4", finding: "#34d6c4", challenge: "#ff8a3d", correlate: "#7ab8ff",
  diagnosis: "#7ab8ff", verify: "#a879ff", verification: "#a879ff", report: "#ff6a1a", error: "#ef3b33",
};

export default function AgentsView({ d }: { d: Diagnosis }) {
  const [sel, setSel] = useState<number>(0);
  const [agent, setAgent] = useState<string>(Object.keys(d.cards)[0] ?? "");
  const lanes = LANES.filter((l) => d.log.some((m) => m.sender === l || m.recipient === l));
  const colW = 150, rowH = 30, top = 44;
  const w = colW * lanes.length, h = top + rowH * d.log.length + 10;
  const msg: BusMessage | undefined = d.log[sel];
  const trace = d.prooftrace.agents?.find((a) => a.agent === agent);
  return (
    <div className="grid gap-5 xl:grid-cols-5 animate-fadein">
      <Panel className="xl:col-span-3" title="Agent conversation" right={<span className="text-xs text-slate-500">{d.log.length} validated protocol messages · click one</span>}>
        <div className="flex flex-wrap gap-3 pb-3 text-[11px] text-slate-400">
          {[["capability", "discovery"], ["analyze", "analysis"], ["challenge", "challenge round"], ["correlate", "fusion"], ["verify", "verification"], ["report", "report"], ["error", "error"]].map(([k, l]) => (
            <span key={k} className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: PHASE[k] }} />{l}</span>))}
        </div>
        <div className="max-h-[640px] overflow-auto">
          <svg width={w} height={h} className="min-w-full">
            {lanes.map((l, i) => (
              <g key={l}>
                <text x={i * colW + colW / 2} y={18} textAnchor="middle" className="fill-slate-300 text-[12px] font-medium">{pretty(l)}</text>
                <line x1={i * colW + colW / 2} x2={i * colW + colW / 2} y1={28} y2={h} stroke="#ffffff14" strokeDasharray="3 4" />
              </g>
            ))}
            {d.log.map((m, i) => {
              const a = lanes.indexOf(m.sender), b = lanes.indexOf(m.recipient);
              if (a < 0 || b < 0) return null;
              const y = top + i * rowH, x1 = a * colW + colW / 2, x2 = b * colW + colW / 2;
              const col = PHASE[m.msg_type.split("_")[0]] ?? "#999";
              const dir = x2 > x1 ? 1 : -1;
              return (
                <g key={m.message_id} className="cursor-pointer" onClick={() => setSel(i)} opacity={sel === i ? 1 : 0.85}>
                  <rect x={Math.min(x1, x2)} y={y - 13} width={Math.abs(x2 - x1)} height={22} fill={sel === i ? "#ffffff10" : "transparent"} rx={6} />
                  <line x1={x1} x2={x2 - dir * 6} y1={y} y2={y} stroke={col} strokeWidth={sel === i ? 2.4 : 1.6} />
                  <path d={`M${x2},${y} l${-dir * 8},-4 v8 z`} fill={col} />
                  <text x={(x1 + x2) / 2} y={y - 4} textAnchor="middle" className="text-[10px]" fill={col}>{i + 1}. {m.msg_type}</text>
                </g>
              );
            })}
          </svg>
        </div>
      </Panel>
      <div className="space-y-5 xl:col-span-2">
        <Panel title={msg ? `Message ${sel + 1}: ${msg.msg_type}` : "Message"}>
          {msg && (<>
            <div className="mb-2 text-xs text-slate-400">{pretty(msg.sender)} → {pretty(msg.recipient)} · <span className="mono">{msg.message_id}</span> · sha256 <span className="mono">{d.prooftrace.integrity.messages[sel]?.sha256.slice(0, 12)}…</span></div>
            <pre className="mono max-h-80 overflow-auto rounded-lg bg-black/40 p-3 text-slate-300">{JSON.stringify(msg.payload, null, 2).slice(0, 12000)}</pre>
          </>)}
        </Panel>
        <Panel title="Agent cards (discovered at handshake)">
          <div className="mb-3 flex flex-wrap gap-2">
            {Object.keys(d.cards).map((a) => (
              <button key={a} onClick={() => setAgent(a)} className={cn("chip", agent === a ? "border-ember-500/60 bg-ember-500/10 text-ember-200" : "border-white/10 text-slate-300")}>{pretty(a)}</button>))}
          </div>
          {trace ? <AgentDetail d={d} a={trace} /> : <div className="text-sm text-slate-400">No trace for this agent.</div>}
        </Panel>
      </div>
    </div>
  );
}
