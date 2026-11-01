import { useEffect, useMemo, useState } from "react";
import { ArrowRight, ChevronDown, Download, FileCheck2, ShieldAlert, ShieldCheck, ShieldQuestion, Swords } from "lucide-react";
import type { Diagnosis, TgDecision, TgRecord, TgView } from "../types";
import { cn, fmt, pretty } from "../util";
import { Empty, Panel } from "../components/ui";

const TONE: Record<TgDecision, string> = {
  trusted: "border-teal-400/40 text-teal-300",
  flagged: "border-alarm-500/50 bg-alarm-500/10 text-alarm-400",
  unverifiable: "border-ember-500/40 text-ember-300",
};
const ICON = { trusted: ShieldCheck, flagged: ShieldAlert, unverifiable: ShieldQuestion };

/** TrustGuard: every specialist claim audited against the telemetry before correlation.
 *  Everything shown comes from report.trustguard and prooftrace.trustguard (netcoop/trustguard.py). */
export default function TrustGuardView({ d, onDemo, onToggle, onOpenProofTrace, enabled }: {
  d: Diagnosis; onDemo: () => void; onToggle: (on: boolean) => void; onOpenProofTrace: () => void; enabled: boolean;
}) {
  const tg = d.prooftrace.trustguard;
  const rep = d.report.trustguard;
  const [filter, setFilter] = useState<"votes" | "attention" | "all">("votes");
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => setOpen(tg?.records.find((r) => r.decision !== "trusted")?.record_id ?? null), [d]); // eslint-disable-line react-hooks/exhaustive-deps
  const rows = useMemo(() => (tg?.records ?? []).filter((r) =>
    filter === "all" ? true : filter === "votes" ? r.kind === "vote" : r.decision !== "trusted"), [tg, filter]);
  const tgChecks = d.prooftrace.checks.checks.filter((c) => /audit|trustguard|findings unchanged|audited/i.test(c.check));
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(tg, null, 2)], { type: "application/json" }));
    Object.assign(document.createElement("a"), { href: url, download: `${d.report.incident_id}.trustguard.json` }).click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-5 animate-fadein">
      <div className="panel flex flex-wrap items-center gap-5 p-5">
        <ShieldCheck size={36} className="text-ember-400" />
        <div className="min-w-0 flex-1">
          <div className="eyebrow">TrustGuard · agent trust &amp; integrity</div>
          <div className="text-[13px] text-slate-400">Every specialist claim is re-checked against the normalised telemetry before
            correlation. Disagreeing with other agents is never a reason to flag; TrustGuard never diagnoses.</div>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={enabled} onChange={(e) => onToggle(e.target.checked)} className="accent-orange-500" />Audit enabled
        </label>
        <button className="btn-ember" onClick={onDemo}><Swords size={16} /> Run adversarial-agent demo</button>
        {d.incident.simulation?.applied && (
          <div className="w-full rounded-lg border border-ember-500/30 bg-ember-500/[0.07] px-3 py-2 text-[12px] text-ember-200">
            Simulation applied: {Object.entries(d.incident.simulation.faults).map(([a, m]) => `${pretty(a)} = ${m}`).join(", ")} · {d.incident.simulation.note}
          </div>)}
      </div>

      {!enabled ? <Empty>TrustGuard is switched off: findings go to correlation unaudited.</Empty>
        : rep?.status === "unavailable" ? <Empty>TrustGuard was unavailable ({rep.reason}); findings were not audited.</Empty>
        : !tg ? <Empty>No findings were audited for this input.</Empty> : (<>
          <div className="grid gap-4 md:grid-cols-4">
            {[["Claims checked", tg.summary.checked, `${tg.summary.votes_checked} hypothesis votes`, "text-white"],
              ["Accepted", tg.summary.accepted, "consistent with telemetry", "text-teal-300"],
              ["Flagged", tg.summary.flagged, "removed before correlation", "text-alarm-400"],
              ["Unverifiable", tg.summary.unverifiable, "telemetry missing: capped", "text-ember-300"]].map(([l, v, s, c]) => (
              <div key={l as string} className="panel p-4">
                <div className="text-xs text-slate-400">{l}</div>
                <div className={cn("mt-1 text-3xl font-semibold", c as string)}>{v}</div>
                <div className="text-[11px] text-slate-500">{s}</div>
              </div>))}
          </div>

          {tg.before_after && (
            <Panel title="Before and after the audit" right={<span className="text-xs text-slate-500">{tg.before_after.engine ?? tg.before_after.reason}</span>}>
              <div className="grid items-center gap-4 md:grid-cols-[1fr_auto_1fr_1fr]">
                <DiagCard title="Without TrustGuard" v={tg.before_after.before} />
                <ArrowRight className="hidden text-ember-400 md:block" />
                <DiagCard title="With TrustGuard" v={tg.before_after.after} highlight />
                <div className="space-y-1.5 text-sm">
                  <Fact k="Diagnosis changed" v={tg.before_after.diagnosis_changed ? "yes" : "no"} warn={tg.before_after.diagnosis_changed} />
                  <Fact k="Confidence change" v={`${tg.before_after.confidence_delta >= 0 ? "+" : ""}${tg.before_after.confidence_delta.toFixed(2)}`} />
                  <Fact k="Enough evidence left" v={tg.before_after.sufficient_evidence_after ? "yes" : "no"} />
                </div>
              </div>
            </Panel>)}

          <div className="grid gap-5 xl:grid-cols-[1fr_380px]">
            <Panel title="Agent audit" right={
              <div className="flex gap-1">{(["votes", "attention", "all"] as const).map((f) => (
                <button key={f} onClick={() => setFilter(f)} className={cn("chip", filter === f ? "border-ember-500/60 bg-ember-500/10 text-ember-200" : "border-white/10 text-slate-400")}>
                  {f === "votes" ? "Hypothesis votes" : f === "attention" ? "Flagged / unverifiable" : "Every claim"}</button>))}</div>}>
              {rows.length === 0 ? <Empty>Every claim in this view is consistent with the telemetry.</Empty> : (
                <div className="max-h-[560px] overflow-auto">
                  <table className="tbl">
                    <thead><tr><th>Agent</th><th>Device</th><th>Claim</th><th>Original</th><th>Audit</th><th>Reason</th><th /></tr></thead>
                    <tbody>{rows.map((r) => (<RecordRow key={r.record_id} r={r} open={open === r.record_id}
                      onToggle={() => setOpen(open === r.record_id ? null : r.record_id)} />))}</tbody>
                  </table>
                </div>)}
            </Panel>
            <div className="space-y-5">
              <Panel title="Per agent">
                <table className="tbl"><thead><tr><th>Agent</th><th>Checked</th><th>Trusted</th><th>Flagged</th><th>Unverif.</th></tr></thead>
                  <tbody>{Object.entries(tg.agents).map(([a, s]) => (
                    <tr key={a}><td>{pretty(a)}</td><td className="mono">{s.checked}</td><td className="mono text-teal-300">{s.trusted}</td>
                      <td className={cn("mono", s.flagged ? "text-alarm-400" : "text-slate-500")}>{s.flagged}</td>
                      <td className={cn("mono", s.unverifiable ? "text-ember-300" : "text-slate-500")}>{s.unverifiable}</td></tr>))}</tbody></table>
              </Panel>
              <Panel title="In ProofTrace" right={<button className="btn-ghost text-xs" onClick={onOpenProofTrace}><FileCheck2 size={14} /> Open</button>}>
                <div className="mb-2 text-[12px] text-slate-400">Audit message <span className="mono text-slate-300">{tg.audit_message_id}</span> is hashed into the
                  log chain; the verifier re-runs the audit from the raw input and the logged agent messages.</div>
                <div className="space-y-1">{tgChecks.map((c, i) => (
                  <div key={i} className="flex items-start gap-2 text-[12px]">
                    <span className={c.ok ? "text-teal-300" : "text-alarm-400"}>{c.ok ? "✓" : "✗"}</span>
                    <span className="text-slate-300">{c.check}</span></div>))}</div>
                <div className="mt-3 text-[11px] text-slate-500">{tg.note}</div>
                <button className="btn-ghost mt-3 text-xs" onClick={download}><Download size={14} /> Audit JSON</button>
              </Panel>
            </div>
          </div>
        </>)}
    </div>
  );
}

function DiagCard({ title, v, highlight }: { title: string; v: TgView; highlight?: boolean }) {
  return (
    <div className={cn("panel-inner p-4", highlight && "border border-ember-500/40")}>
      <div className="eyebrow">{title}</div>
      <div className="mt-1 text-lg font-semibold text-white">{pretty(v.root_cause_type ?? v.leading_hypothesis ?? v.status)}</div>
      <div className="text-[12px] text-slate-400">{pretty(v.status)} · {v.root_cause_devices.join(", ") || "no device"}</div>
      <div className="mt-1 mono text-ember-300">confidence {v.confidence.toFixed(2)}</div>
    </div>
  );
}

function Fact({ k, v, warn }: { k: string; v: string; warn?: boolean }) {
  return <div className="flex justify-between gap-3"><span className="text-slate-400">{k}</span><span className={cn("font-medium", warn ? "text-alarm-400" : "text-slate-100")}>{v}</span></div>;
}

function RecordRow({ r, open, onToggle }: { r: TgRecord; open: boolean; onToggle: () => void }) {
  const I = ICON[r.decision];
  const odd = r.decision !== "trusted";
  return (<>
    <tr className={cn(odd && "bg-alarm-500/[0.04]", "cursor-pointer")} onClick={onToggle}>
      <td>{pretty(r.agent)}</td><td className="mono text-slate-400">{r.device_id ?? "—"}</td>
      <td><span className="text-slate-500">{r.kind}</span> {pretty(r.subject)}</td>
      <td className="mono">{fmt(r.reported)}</td>
      <td><span className={cn("chip", TONE[r.decision])}><I size={12} />{r.decision}</span></td>
      <td className="mono text-[11px] text-slate-400">{r.reason_codes.join(", ")}</td>
      <td><ChevronDown size={14} className={cn("text-slate-500 transition", open && "rotate-180")} /></td>
    </tr>
    {open && (
      <tr><td colSpan={7} className="bg-black/20">
        <div className="space-y-3 p-2 text-[12px]">
          <div className="text-slate-200">{r.explanation}</div>
          <div className="grid gap-3 lg:grid-cols-2">
            <div>
              <div className="eyebrow mb-1">Original agent claim</div>
              <pre className="mono max-h-48 overflow-auto rounded-lg bg-black/40 p-2 text-slate-300">{JSON.stringify({
                [r.kind]: { [r.subject]: r.reported }, finding: r.finding_id,
                ...(r.original_finding ? { all_votes: r.original_finding.votes,
                  own_signal_strengths: Object.fromEntries(Object.entries(r.original_finding.signal_strength).filter(([, v]) => v > 0)) } : {}),
              }, null, 2)}</pre>
            </div>
            <div>
              <div className="eyebrow mb-1">Normalised telemetry (TrustGuard's own recomputation)</div>
              {r.telemetry_refs.length === 0 ? <div className="text-slate-500">—</div> : (
                <table className="tbl"><thead><tr><th>Signal</th><th>Metric</th><th>Value</th><th>Strength</th><th>Input records</th></tr></thead>
                  <tbody>{r.telemetry_refs.map((t, i) => (
                    <tr key={i}><td>{t.signal ?? "—"}</td><td className="mono text-slate-400">{t.metric}</td><td className="mono">{fmt(t.value)}</td>
                      <td className="mono">{t.strength == null ? "missing" : t.strength.toFixed(2)}</td>
                      <td className="mono text-slate-500">{t.record_indexes.slice(0, 5).map((x) => "#" + x).join(" ") || "—"}</td></tr>))}</tbody></table>)}
            </div>
          </div>
          {r.kind === "vote" && (
            <div className="text-slate-400">Expected support: strongest observable symptom <span className="mono text-slate-200">{fmt(r.expected.ceiling)}</span>
              {" "}(+{fmt(r.expected.ceiling_tolerance)}), cause-specific indicator <span className="mono text-slate-200">{fmt(r.expected.specific_support)}</span>
              {" "}· reported vote <span className="mono text-slate-200">{fmt(r.reported)}</span></div>)}
          {r.kind === "signal" && <div className="text-slate-400">Recomputed strength <span className="mono text-slate-200">{fmt(r.expected.strength)}</span> · reported <span className="mono text-slate-200">{fmt(r.reported)}</span></div>}
          <div className={cn("rounded-lg px-3 py-2", odd ? "bg-alarm-500/10 text-alarm-400" : "bg-teal-400/10 text-teal-300")}>Influence on the diagnosis: {r.effect}</div>
          <div className="mono text-[11px] text-slate-500">message {r.message_id ?? "—"} · finding sha256 {(r.finding_sha256 ?? "—").slice(0, 16)}… · {r.timestamp} · audit v{r.audit_version}</div>
        </div>
      </td></tr>)}
  </>);
}
