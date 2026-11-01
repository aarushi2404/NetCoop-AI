/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api } from "../api";
import { pct, pretty } from "../util";
import { Bar, Empty, Panel } from "../components/ui";

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="panel-inner p-4">
      <div className="text-2xl font-semibold text-white">{value}</div>
      <div className="text-[13px] text-slate-400">{label}</div>
      {sub && <div className="mt-1 text-[11px] text-slate-500">{sub}</div>}
    </div>
  );
}

function Reliability({ bins }: { bins: { bin: string; n: number; mean_confidence: number; accuracy: number }[] }) {
  const S = 220, p = 28;
  const X = (v: number) => p + v * (S - 2 * p), Y = (v: number) => S - p - v * (S - 2 * p);
  return (
    <svg viewBox={`0 0 ${S} ${S}`} className="w-full max-w-[260px]">
      <rect x={p} y={p} width={S - 2 * p} height={S - 2 * p} fill="none" stroke="#ffffff14" />
      <line x1={X(0)} y1={Y(0)} x2={X(1)} y2={Y(1)} stroke="#8b93a1" strokeDasharray="4 4" />
      <polyline fill="none" stroke="#ff6a1a" strokeWidth={2.5} points={bins.map((b) => `${X(b.mean_confidence)},${Y(b.accuracy)}`).join(" ")} />
      {bins.map((b) => <circle key={b.bin} cx={X(b.mean_confidence)} cy={Y(b.accuracy)} r={3 + Math.sqrt(b.n) / 2} fill="#ff6a1a" fillOpacity={0.7} />)}
      <text x={S / 2} y={S - 6} textAnchor="middle" className="fill-slate-500 text-[9px]">stated confidence</text>
      <text x={9} y={S / 2} textAnchor="middle" transform={`rotate(-90 9 ${S / 2})`} className="fill-slate-500 text-[9px]">actual accuracy</text>
    </svg>
  );
}

function MdTable({ md }: { md: string }) {
  const rows = md.split("\n").filter((l) => l.startsWith("|") && !/^\|[-| ]+\|$/.test(l)).map((l) => l.slice(1, -1).split("|").map((c) => c.trim()));
  if (!rows.length) return null;
  return (
    <table className="tbl"><thead><tr>{rows[0].map((c) => <th key={c}>{c}</th>)}</tr></thead>
      <tbody>{rows.slice(1).map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className={c.includes("verified") || c === "ok" || c === "compatible wlo-1" ? "text-teal-300" : c.includes("failed") || c.includes("incompatible") ? "text-alarm-400" : "text-slate-300"}>{c}</td>)}</tr>)}</tbody></table>
  );
}

export default function BenchmarksView() {
  const [b, setB] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.benchmarks().then(setB).catch((e) => setErr(String(e))); }, []);
  if (err) return <Empty>{err}</Empty>;
  if (!b) return <div className="flex justify-center p-20 text-slate-400"><Loader2 className="animate-spin" /></div>;
  const f = b.internal?.full, h = b.internal?.holdout, org = b.organizer;
  return (
    <div className="space-y-5 animate-fadein">
      {f ? (
        <Panel title="Internally generated data" right={<span className="chip border-white/10 text-slate-400">our generator · {b.internal.n} incidents · seed {b.internal.seed}</span>}>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Kpi label="Accuracy" value={pct(f.accuracy, 1)} sub="abstaining counts as wrong" />
            <Kpi label="When it commits" value={pct(f.selective_accuracy, 1)} />
            <Kpi label="Abstention" value={pct(f.abstention_rate, 1)} />
            <Kpi label="Confident & wrong" value={pct(f.confident_wrong_rate, 1)} />
            <Kpi label="Calibration error" value={b.internal.calibration.ece.toFixed(3)} sub="under-confident" />
            <Kpi label="ProofTrace verified" value={f.prooftrace_verified ?? "—"} />
          </div>
          {h && <div className="mt-3 rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 text-sm text-slate-300">
            Held-out set (seed {h.seed}, never used during development): accuracy <b>{pct(h.accuracy, 1)}</b>, selective {pct(h.selective_accuracy, 1)},
            abstains {pct(h.abstention_rate, 1)}, confident-wrong {pct(h.confident_wrong_rate, 1)}.</div>}
          <div className="mt-5 grid gap-6 xl:grid-cols-3">
            <div>
              <div className="eyebrow mb-3">Per scenario</div>
              {Object.entries(b.internal.per_scenario).map(([k, v]: [string, any]) => (
                <div key={k} className="mb-2 flex items-center gap-3 text-[12px]"><span className="w-40 truncate text-slate-300">{pretty(k)}</span><Bar value={v.accuracy} tone={v.accuracy < 0.8 ? "ember" : "teal"} /><span className="mono w-10 text-right">{pct(v.accuracy)}</span></div>))}
            </div>
            <div>
              <div className="eyebrow mb-3">Ablation: does multi-agent matter?</div>
              {Object.entries(b.internal.ablation ?? {}).map(([k, v]: [string, any]) => (
                <div key={k} className="mb-2 text-[12px]"><div className="mb-1 flex justify-between text-slate-300"><span>{k}</span><span className="mono">{pct(v.accuracy, 1)}</span></div><Bar value={v.accuracy} tone={k.startsWith("all") ? "ember" : "slate"} /></div>))}
            </div>
            <div>
              <div className="eyebrow mb-3">Reliability (ECE {b.internal.calibration.ece.toFixed(3)})</div>
              <Reliability bins={b.internal.calibration.bins} />
              <p className="mt-2 text-[11px] text-slate-500">Points above the diagonal = under-confident. Measures robustness on our synthetic data, not real-network accuracy.</p>
            </div>
          </div>
        </Panel>
      ) : <Empty>Run <code>python -m netcoop benchmark</code>.</Empty>}

      {org ? (
        <Panel title="Organizer-generated data" right={<span className="chip border-violet-400/30 text-violet-300">organizer notebook · {org.n} incidents · reported separately</span>}>
          <div className="grid gap-5 xl:grid-cols-2">
            {["clean", "stressed"].filter((k) => org[k]).map((k) => (
              <div key={k}>
                <div className="eyebrow mb-2">{k}{k === "stressed" ? " (20 % metrics dropped, stale sample, junk value)" : ""}</div>
                <div className="grid grid-cols-3 gap-2">
                  <Kpi label="Accuracy" value={pct(org[k].accuracy, 1)} />
                  <Kpi label="False diagnoses" value={pct(org[k].false_diagnosis_rate, 1)} />
                  <Kpi label="ProofTrace" value={org[k].prooftrace_verified} />
                </div>
                <table className="tbl mt-3"><thead><tr><th>Organizer label</th><th>n</th><th>Accuracy</th><th>Outcomes</th></tr></thead>
                  <tbody>{Object.entries(org[k].per_label).map(([l, v]: [string, any]) => (
                    <tr key={l}><td>{l}</td><td className="mono">{v.n}</td><td className="mono">{pct(v.accuracy)}</td><td className="text-slate-400">{Object.entries(v.outcomes).map(([a, n]) => `${a} ${n}`).join(", ")}</td></tr>))}</tbody></table>
              </div>))}
          </div>
          {org.sweep && (
            <div className="mt-4 flex flex-wrap gap-2 text-[12px] text-slate-400">Other seeds:
              {Object.entries(org.sweep).map(([s, v]: [string, any]) => <span key={s} className="chip border-white/10">seed {s}: {pct(v.accuracy, 1)}</span>)}</div>)}
          <p className="mt-3 text-[12px] text-slate-500">Mapping: normal → healthy, hardware_failure → hardware_failure, latency_spike → symptom only (correct = device flagged, no root cause committed). The organizer profiles are far apart, so this mainly shows schema compatibility and no over-claiming.</p>
        </Panel>
      ) : <Empty>Run <code>python -m netcoop organizer-eval</code>.</Empty>}

      {b.interop_markdown && (
        <Panel title="Interoperability: foreign HTTP agent" right={<span className="text-xs text-slate-500">python -m netcoop interop-demo</span>}>
          <MdTable md={b.interop_markdown} />
        </Panel>
      )}
    </div>
  );
}
