import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Download, FileJson, Fingerprint, GitBranch, ShieldAlert, ShieldCheck } from "lucide-react";
import type { Diagnosis, Evidence, Hypothesis } from "../types";
import { cn, fmt, pct, pretty } from "../util";
import { Bar, Empty, Panel } from "../components/ui";

const VERDICT = {
  selected: "border-ember-500/50 bg-ember-500/10 text-ember-300",
  "leading (not committed)": "border-slate-400/40 bg-white/5 text-slate-200",
  rejected: "border-alarm-500/30 bg-alarm-500/[0.07] text-alarm-400",
  "not supported": "border-white/10 text-slate-500",
};

export default function ProofTraceView({ d, focus }: { d: Diagnosis; focus: string | null }) {
  const t = d.prooftrace;
  const hyps = t.hypotheses ?? [];
  const [open, setOpen] = useState<string | null>(focus ?? hyps[0]?.hypothesis ?? null);
  const [ev, setEv] = useState<string | null>(t.evidence?.[0]?.id ?? null);
  useEffect(() => { setOpen(focus ?? hyps[0]?.hypothesis ?? null); setEv(t.evidence?.[0]?.id ?? null); }, [d, focus]); // eslint-disable-line react-hooks/exhaustive-deps
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(t, null, 2)], { type: "application/json" }));
    Object.assign(document.createElement("a"), { href: url, download: `${t.incident_id}.prooftrace.json` }).click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="space-y-5 animate-fadein">
      <div className="panel flex flex-wrap items-center gap-6 p-5">
        <div className={cn("flex items-center gap-3", t.checks.verified ? "text-teal-300" : "text-alarm-400")}>
          {t.checks.verified ? <ShieldCheck size={34} /> : <ShieldAlert size={34} />}
          <div>
            <div className="text-xl font-semibold text-white">{t.checks.passed}/{t.checks.total} independent checks passed</div>
            <div className="text-sm text-slate-400">Re-derived from the raw input and the message log by <code className="mono">verify_prooftrace</code></div>
          </div>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-xs text-slate-400"><Fingerprint size={14} /> chain SHA-256 over {t.integrity.message_count} messages</div>
          <div className="mono truncate text-slate-300">{t.integrity.chain_sha256}</div>
        </div>
        <button className="btn-ghost" onClick={download}><Download size={16} /> ProofTrace JSON</button>
      </div>

      {hyps.length === 0 ? (
        <Panel title="Nothing to trace">
          <Empty>{t.note ?? (d.report.status === "healthy" ? "No fault was found: every device is below its warning onsets." : "No hypotheses were raised.")}</Empty>
          {t.healthy_check && (
            <table className="tbl mt-4"><thead><tr><th>Device</th><th>Strongest signal</th><th>Strength</th></tr></thead>
              <tbody>{t.healthy_check.map((h) => <tr key={h.device_id}><td>{h.device_id}</td><td>{h.max_signal[0]}</td><td className="mono">{h.max_signal[1].toFixed(2)}</td></tr>)}</tbody></table>
          )}
        </Panel>
      ) : (
        <>
          <div className="grid gap-5 xl:grid-cols-5">
            <Panel className="xl:col-span-3" title={<>Competing hypotheses on <span className="mono text-ember-300">{t.primary_device}</span></>}
              right={<span className="text-xs text-slate-500">all 7 causes · generated from logged votes</span>}>
              <div className="space-y-2">
                {hyps.map((h) => <HypRow key={h.hypothesis} h={h} open={open === h.hypothesis} onToggle={() => setOpen(open === h.hypothesis ? null : h.hypothesis)} />)}
              </div>
            </Panel>
            <Panel className="xl:col-span-2" title="Evidence × hypothesis" right={<span className="text-xs text-slate-500">click a cell</span>}>
              <Matrix t={t.evidence ?? []} hyps={hyps} primary={t.primary_device} onPick={(h, e) => { setOpen(h); if (e) setEv(e); }} />
            </Panel>
          </div>

          <Panel title="Evidence provenance: from raw bytes to verdict">
            <div className="mb-4 flex flex-wrap gap-2">
              {(t.evidence ?? []).map((e) => (
                <button key={e.id} onClick={() => setEv(e.id)}
                  className={cn("chip transition", ev === e.id ? "border-ember-500/60 bg-ember-500/15 text-ember-200" : "border-white/10 text-slate-300 hover:border-white/25")}>
                  <span className="mono text-slate-500">{e.id}</span>{e.signal}<span className="mono">{fmt(e.value)}</span>
                </button>
              ))}
            </div>
            {ev && <Provenance d={d} e={(t.evidence ?? []).find((x) => x.id === ev)!} />}
          </Panel>

          <div className="grid gap-5 xl:grid-cols-2">
            <Panel title="Agent contributions" right={<span className="text-xs text-slate-500">leave-one-out re-correlation</span>}>
              <table className="tbl"><thead><tr><th>Agent</th><th>Top vote</th><th>Without it</th><th>Contribution</th></tr></thead>
                <tbody>{(t.agents ?? []).filter((a) => a.findings_message_id).map((a) => (
                  <tr key={a.agent}>
                    <td><div className="text-slate-200">{pretty(a.agent)}</div><div className="text-[11px] text-slate-500">{a.transport} · {a.health}</div></td>
                    <td className="text-slate-300">{a.on_root_device?.top_vote ? `${pretty(a.on_root_device.top_vote.hypothesis)} ${a.on_root_device.top_vote.vote.toFixed(2)}` : "—"}</td>
                    <td className="text-slate-400">{a.leave_one_out ? `${pretty(a.leave_one_out.status)} / ${pretty(a.leave_one_out.hypothesis) || "—"} ${a.leave_one_out.confidence.toFixed(2)}` : "—"}</td>
                    <td><span className={cn("chip", a.leave_one_out?.contribution === "decisive" ? "border-ember-500/50 text-ember-300" : a.leave_one_out?.contribution?.startsWith("dissent") ? "border-alarm-500/40 text-alarm-400" : "border-white/10 text-slate-400")}>{a.leave_one_out?.contribution ?? "—"}</span></td>
                  </tr>))}</tbody></table>
              {(t.conflicts ?? []).map((c, i) => <div key={i} className="mt-3 rounded-lg bg-white/[0.03] p-3 text-[12px] text-slate-400"><span className="text-slate-200">{pretty(c.agent)}</span> favoured {pretty(c.agent_hypothesis)}: {c.resolution}</div>)}
            </Panel>
            <Panel title="What would change the diagnosis" right={t.sensitivity && <span className="text-xs text-slate-500">baseline reproduced: {t.sensitivity.baseline_reproduced ? "yes" : "NO"}</span>}>
              {!t.sensitivity ? <Empty>Not available.</Empty> : (
                <div className="space-y-1.5">
                  {t.sensitivity.scenarios.map((s, i) => (
                    <div key={i} className={cn("flex items-start gap-3 rounded-lg border px-3 py-2 text-[12px]", s.flips_conclusion ? "border-ember-500/40 bg-ember-500/[0.06]" : "border-white/[0.06]")}>
                      <GitBranch size={15} className={s.flips_conclusion ? "mt-0.5 text-ember-400" : "mt-0.5 text-slate-600"} />
                      <div className="flex-1"><div className="text-slate-300">{s.change}</div>
                        <div className="text-slate-500">→ {pretty(s.result.status)} {s.result.hypothesis ? `/ ${pretty(s.result.hypothesis)}` : ""} ({pct(s.result.confidence)})</div></div>
                      <span className={cn("text-[11px] font-semibold uppercase", s.flips_conclusion ? "text-ember-300" : "text-slate-600")}>{s.flips_conclusion ? "flips" : "holds"}</span>
                    </div>))}
                </div>)}
            </Panel>
          </div>

          {(d.report.abstention || d.report.hedge || (t.missing_information ?? []).length > 0) && (
            <Panel title="Missing information">
              {(d.report.abstention ?? d.report.hedge) && (
                <div className="mb-3 text-sm text-slate-300">{(d.report.abstention ?? d.report.hedge)!.summary}
                  <ul className="mt-2 list-disc pl-5 text-slate-400">{(d.report.abstention ?? d.report.hedge)!.why_not_committed.map((w) => <li key={w}>{w}</li>)}</ul></div>)}
              <table className="tbl"><thead><tr><th>Measure</th><th>On device</th><th>Status</th><th>Would decide</th></tr></thead>
                <tbody>{(t.missing_information ?? []).map((m, i) => <tr key={i}><td className="mono">{m.metric}</td><td>{m.device_id}</td><td className="text-slate-400">{m.status ?? "not measured"}</td><td>{m.decides.map(pretty).join(", ")}</td></tr>)}</tbody></table>
            </Panel>
          )}
        </>
      )}

      <Panel title="Decision gates and message integrity">
        <div className="grid gap-5 xl:grid-cols-2">
          <table className="tbl"><thead><tr><th>Gate</th><th>Need</th><th>Result</th></tr></thead>
            <tbody>{(d.report.decision_gates ?? []).map((g) => (
              <tr key={g.gate}><td className="text-slate-200">{g.gate}<div className="text-[11px] text-slate-500">{g.explanation}</div></td><td className="mono text-slate-400">{g.need}</td>
                <td className={g.passed ? "text-teal-300" : "text-ember-300"}>{g.passed ? "pass" : "fail"}</td></tr>))}</tbody></table>
          <div className="max-h-80 overflow-auto">
            <table className="tbl"><thead><tr><th>#</th><th>Message</th><th>SHA-256</th></tr></thead>
              <tbody>{t.integrity.messages.map((m) => (
                <tr key={m.i}><td className="mono text-slate-500">{m.i + 1}</td><td className="text-[12px]">{m.msg_type}<div className="text-slate-500">{pretty(m.sender)} → {pretty(m.recipient)}</div></td>
                  <td className="mono text-slate-500">{m.sha256.slice(0, 16)}…</td></tr>))}</tbody></table>
          </div>
        </div>
      </Panel>
    </div>
  );
}

function HypRow({ h, open, onToggle }: { h: Hypothesis; open: boolean; onToggle: () => void }) {
  return (
    <div className={cn("rounded-xl border transition", open ? "border-white/15 bg-white/[0.03]" : "border-white/[0.06]")}>
      <button onClick={onToggle} className="flex w-full items-center gap-3 px-4 py-3 text-left">
        <span className={cn("chip w-40 justify-center", VERDICT[h.verdict])}>{h.verdict}</span>
        <span className="w-36 text-sm text-slate-100">{pretty(h.hypothesis)}</span>
        <Bar value={h.score} tone={h.verdict === "selected" ? "ember" : "slate"} className="flex-1" />
        <span className="mono w-10 text-right">{h.score.toFixed(2)}</span>
        <ChevronDown size={16} className={cn("text-slate-500 transition", open && "rotate-180")} />
      </button>
      {open && (
        <div className="grid gap-4 border-t border-white/[0.06] p-4 text-[13px] lg:grid-cols-2 animate-fadein">
          <div className="space-y-3">
            {h.why_selected.map((w) => <div key={w} className="text-teal-300">✓ {w}</div>)}
            {h.rejection_reasons.map((w) => <div key={w} className="text-alarm-400">✗ {w}</div>)}
            <div className="flex flex-wrap gap-1.5">
              {h.votes.length === 0 && <span className="text-slate-500">no agent voted for it</span>}
              {h.votes.map((v) => <span key={v.agent} className="chip border-white/10 text-slate-300">{pretty(v.agent)} {v.vote.toFixed(2)}×{v.weight}<span className="mono text-slate-600">{v.message_id}</span></span>)}
              {(h.excluded_by_trustguard ?? []).map((x) => (
                <span key={x.record_id} title={x.reason_codes.join(", ")} className="chip border-alarm-500/40 text-alarm-400 line-through decoration-alarm-500/60">
                  {pretty(x.agent)} {x.reported.toFixed(2)} · TrustGuard {x.decision} ({x.record_id})</span>))}
            </div>
            <div className="text-slate-500">coverage {pct(h.coverage)} · base vote {h.base_vote.toFixed(2)}{h.graded_support != null && ` · challenge support ${h.graded_support.toFixed(2)}`}</div>
            {h.unexplained_evidence.length > 0 && <div className="text-slate-500">Cannot explain: {h.unexplained_evidence.join(", ")}</div>}
          </div>
          <table className="tbl"><thead><tr><th>Expected signal</th><th>State</th><th>Value</th><th>Alarm</th></tr></thead>
            <tbody>{h.expected_signals.map((e) => (
              <tr key={e.signal}><td>{e.signal}</td>
                <td className={{ present: "text-teal-300", elevated: "text-ember-300", absent: "text-alarm-400", unknown: "text-slate-500" }[e.state]}>{e.state}</td>
                <td className="mono">{fmt(e.value)}</td><td className="mono text-slate-500">{e.threshold}</td></tr>))}</tbody></table>
        </div>
      )}
    </div>
  );
}

function Matrix({ t, hyps, primary, onPick }: { t: Evidence[]; hyps: Hypothesis[]; primary?: string; onPick: (h: string, e?: string) => void }) {
  const cols = hyps.filter((h) => h.votes.length || h.verdict !== "not supported");
  const ev = t.filter((e) => e.device_id === primary);
  const rows = useMemo(() => [...new Set([...ev.map((e) => e.signal), ...cols.flatMap((h) => h.expected_signals.map((x) => x.signal))])], [ev, cols]);
  if (!cols.length) return <Empty>No hypotheses to compare.</Empty>;
  return (
    <div className="overflow-auto">
      <div className="grid gap-1 text-[11px]" style={{ gridTemplateColumns: `130px repeat(${cols.length}, minmax(64px,1fr))` }}>
        <div />
        {cols.map((h) => <div key={h.hypothesis} className={cn("px-1 pb-1 text-center", h.verdict === "selected" ? "text-ember-300" : "text-slate-400")}>{pretty(h.hypothesis)}</div>)}
        {rows.map((sig) => {
          const e = ev.find((x) => x.signal === sig);
          return [
            <div key={sig} className="truncate py-1.5 pr-2 text-slate-300">{sig}</div>,
            ...cols.map((h) => {
              const exp = h.expected_signals.find((x) => x.signal === sig);
              let cls = "bg-white/[0.02] text-transparent", label = "·";
              if (e && e.explains.includes(h.hypothesis)) { cls = e.strength >= 1 ? "bg-teal-500/70 text-white" : "bg-teal-500/30 text-teal-100"; label = e.strength.toFixed(2); }
              else if (exp?.state === "absent") { cls = "bg-alarm-500/60 text-white"; label = "absent"; }
              else if (exp?.state === "unknown") { cls = "bg-white/[0.06] text-slate-400"; label = "?"; }
              else if (e) { cls = "bg-alarm-500/15 text-alarm-400"; label = "unexpl."; }
              return <button key={sig + h.hypothesis} onClick={() => onPick(h.hypothesis, e?.id)}
                className={cn("rounded-md py-1.5 text-center font-medium transition hover:ring-1 hover:ring-white/30", cls)}>{label}</button>;
            }),
          ];
        })}
      </div>
      <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-slate-500">
        <span><span className="mr-1 inline-block h-2 w-3 rounded bg-teal-500/70" />explained</span>
        <span><span className="mr-1 inline-block h-2 w-3 rounded bg-alarm-500/60" />expected, absent</span>
        <span><span className="mr-1 inline-block h-2 w-3 rounded bg-white/10" />not measured</span>
        <span><span className="mr-1 inline-block h-2 w-3 rounded bg-alarm-500/15" />observed, unexplained</span>
      </div>
    </div>
  );
}

function Provenance({ d, e }: { d: Diagnosis; e: Evidence }) {
  const [cite, setCite] = useState(0);
  useEffect(() => setCite(0), [e]);
  const o = e.observed_by[cite];
  const msg = o && d.log.find((m) => m.message_id === o.message_id);
  // a citation points at the agent's finding_batch, or at TrustGuard's audited copy of it (audit_result)
  type Batch = { agent: string; findings: { device_id: string }[] };
  const batch = msg && (msg.msg_type === "audit_result"
    ? (msg.payload.audited_batches as Batch[]).find((b) => b.agent === o.agent)
    : (msg.payload as unknown as Batch));
  const finding = batch?.findings.find((f) => f.device_id === e.device_id);
  const steps = [
    { n: "1", t: "Raw input", v: `${e.raw_samples.length} sample(s) from records ${e.raw_samples.map((s) => "#" + s.record_index).slice(0, 4).join(", ")}` },
    { n: "2", t: "Aggregation", v: `${e.aggregation} → ${fmt(e.value)} ${e.unit ?? ""}` },
    { n: "3", t: "Graded signal", v: `onset ${e.onset ?? "—"}, alarm ${e.threshold} → ${e.strength.toFixed(2)} (${e.state})` },
    { n: "4", t: "Reported by", v: e.observed_by.map((o) => pretty(o.agent)).join(", ") },
    { n: "5", t: "Supports", v: e.explains.map(pretty).join(", ") || "—" },
  ];
  return (
    <div className="space-y-4">
      <div className="grid gap-2 md:grid-cols-5">
        {steps.map((s, i) => (
          <div key={s.n} className="relative panel-inner p-3">
            <div className="text-[11px] font-semibold text-ember-400">{s.n} · {s.t}</div>
            <div className="mt-1 text-[12px] text-slate-300">{s.v}</div>
            {i < steps.length - 1 && <div className="absolute -right-2 top-1/2 hidden h-px w-2 bg-ember-500/50 md:block" />}
          </div>
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <table className="tbl"><thead><tr><th>Record #</th><th>Field path</th><th>Raw value</th><th>Canonical</th><th>Timestamp</th></tr></thead>
          <tbody>{e.raw_samples.map((s, i) => (
            <tr key={i}><td className="mono">{s.record_index}</td><td className="mono text-slate-400">{s.path.join(".")}</td><td className="mono">{fmt(s.raw)}</td>
              <td className="mono">{fmt(s.value)}</td><td className="mono text-slate-500">{s.timestamp?.slice(11, 19) ?? "—"}</td></tr>))}</tbody></table>
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs text-slate-400"><FileJson size={14} /> Cited protocol message
            <select className="input w-auto py-1 text-xs" value={cite} onChange={(ev) => setCite(+ev.target.value)}>
              {e.observed_by.map((x, i) => <option key={i} value={i}>{x.message_id} ({pretty(x.agent)})</option>)}
            </select>
          </div>
          <pre className="mono max-h-64 overflow-auto rounded-lg bg-black/40 p-3 text-slate-300">
            {msg ? JSON.stringify({ message_id: msg.message_id, sender: msg.sender, recipient: msg.recipient, msg_type: msg.msg_type,
              timestamp: msg.timestamp, ...(o?.source_message_id ? { audited_copy_of: o.source_message_id } : {}), finding }, null, 2) : "message not found"}
          </pre>
        </div>
      </div>
    </div>
  );
}
