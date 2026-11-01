import { useMemo, useRef, useState } from "react";
import { Crosshair, Layers, Minus, Plus } from "lucide-react";
import type { Diagnosis } from "../types";
import { cn, nodeRoles, type NodeRole } from "../util";

const W = 1000;
const H = 520;
const VIRTUAL = "__network__";

const PALETTE: Record<NodeRole, { top: string; left: string; right: string; line: string; glow: string; text: string }> = {
  root: { top: "#ff6b5f", left: "#b3221b", right: "#7f1612", line: "#ff4d42", glow: "glow-alarm", text: "#ffd3cf" },
  downstream: { top: "#ffb347", left: "#c56a0c", right: "#8f4a06", line: "#ff8a3d", glow: "glow-ember", text: "#ffe2c2" },
  secondary: { top: "#c39bff", left: "#6b3fc4", right: "#4b2a8c", line: "#a879ff", glow: "", text: "#e7dbff" },
  degraded: { top: "#ffd166", left: "#b8860b", right: "#7d5c06", line: "#ffc14d", glow: "glow-ember", text: "#fff0c9" },
  healthy: { top: "#5ff0dc", left: "#12988c", right: "#0b6a62", line: "#34d6c4", glow: "glow-teal", text: "#d8fffa" },
  silent: { top: "#5b636e", left: "#343a42", right: "#24282e", line: "#4b525c", glow: "", text: "#aab2bd" },
};

interface Pos { x: number; y: number }

function layout(d: Diagnosis): { pos: Record<string, Pos>; parent: Record<string, string | null>; flat: boolean } {
  const parent: Record<string, string | null> = {};
  for (const t of d.topology.devices) parent[t.id] = t.parent;
  for (const id of Object.keys(d.devices)) if (!(id in parent)) parent[id] = d.devices[id].parent ?? null;
  const ids = Object.keys(parent);
  const flat = ids.every((i) => !parent[i]) && ids.length > 1;
  if (flat) { // no topology given: hang everything off an explicit virtual node instead of inventing links
    for (const i of ids) parent[i] = VIRTUAL;
    parent[VIRTUAL] = null;
  }
  const kids: Record<string, string[]> = {};
  for (const [c, p] of Object.entries(parent)) {
    const k = p && p in parent ? p : "__root__";
    (kids[k] ??= []).push(c);
  }
  Object.values(kids).forEach((l) => l.sort());
  const depthOf: Record<string, number> = {};
  const xOf: Record<string, number> = {};
  let leaf = 0;
  const place = (n: string, depth: number): number => {
    depthOf[n] = depth;
    const ch = kids[n] ?? [];
    xOf[n] = ch.length ? ch.map((c) => place(c, depth + 1)).reduce((a, b) => a + b, 0) / ch.length : leaf++;
    return xOf[n];
  };
  (kids["__root__"] ?? []).forEach((r) => place(r, 0));
  const maxDepth = Math.max(0, ...Object.values(depthOf));
  const span = Math.max(1, leaf - 1);
  const pos: Record<string, Pos> = {};
  for (const n of Object.keys(depthOf)) {
    pos[n] = { x: leaf <= 1 ? W / 2 : 140 + (xOf[n] / span) * (W - 280),
      y: maxDepth === 0 ? H / 2 : 120 + (depthOf[n] / maxDepth) * (H - 250) };
  }
  return { pos, parent, flat };
}

function IsoBox({ x, y, role, scale = 1.3 }: { x: number; y: number; role: NodeRole; scale?: number }) {
  const c = PALETTE[role];
  const w = 88 * scale, h = 44 * scale, dz = 24 * scale;
  const top = `${x},${y - h / 2} ${x + w / 2},${y} ${x},${y + h / 2} ${x - w / 2},${y}`;
  const left = `${x - w / 2},${y} ${x},${y + h / 2} ${x},${y + h / 2 + dz} ${x - w / 2},${y + dz}`;
  const right = `${x + w / 2},${y} ${x},${y + h / 2} ${x},${y + h / 2 + dz} ${x + w / 2},${y + dz}`;
  const slits = [0.18, 0.36, 0.54, 0.72];
  return (
    <g className={c.glow}>
      <polygon points={left} fill={c.left} />
      <polygon points={right} fill={c.right} />
      {slits.map((t) => (
        <line key={t} x1={x - w / 2 + (w / 2) * t} y1={y + (h / 2) * t + dz * 0.35}
          x2={x - w / 2 + (w / 2) * t} y2={y + (h / 2) * t + dz * 0.75} stroke="#0008" strokeWidth={3 * scale} />
      ))}
      {slits.map((t) => (
        <line key={`r${t}`} x1={x + (w / 2) * t} y1={y + h / 2 - (h / 2) * t + dz * 0.35}
          x2={x + (w / 2) * t} y2={y + h / 2 - (h / 2) * t + dz * 0.75} stroke="#fff3" strokeWidth={2 * scale} />
      ))}
      <polygon points={top} fill={`url(#top-${role})`} stroke="#ffffff55" strokeWidth={1} />
      <polygon points={`${x},${y - h / 4} ${x + w / 4},${y} ${x},${y + h / 4} ${x - w / 4},${y}`}
        fill="none" stroke="#ffffff70" strokeWidth={1.2} />
    </g>
  );
}

function AccessPoint({ x, y, role }: { x: number; y: number; role: NodeRole }) {
  const c = PALETTE[role];
  return (
    <g className={c.glow}>
      <path d={`M${x - 38},${y} v13 a38,18 0 0 0 76,0 v-13`} fill={c.left} />
      <ellipse cx={x} cy={y} rx={38} ry={18} fill={`url(#top-${role})`} stroke="#ffffff55" />
      <g transform={`translate(${x},${y + 5}) scale(1.3,0.65)`} fill="none" stroke="#fff" strokeWidth={2.4} strokeLinecap="round">
        <path d="M-13,-6 a18,18 0 0 1 26,0" opacity={0.95} />
        <path d="M-8,-1 a11,11 0 0 1 16,0" />
        <circle cx={0} cy={4} r={1.8} fill="#fff" />
      </g>
    </g>
  );
}

// deterministic decorative campus blocks (background only)
const BUILDINGS = [[70, 190], [180, 120], [860, 150], [940, 260], [60, 420], [930, 430], [330, 70], [690, 90]];

export default function TopologyMap({ d, selected, onSelect, height = 430, compact = false }: {
  d: Diagnosis; selected: string | null; onSelect: (id: string | null) => void; height?: number; compact?: boolean;
}) {
  const { pos, parent, flat } = useMemo(() => layout(d), [d]);
  const roles = useMemo(() => nodeRoles(d), [d]);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [layers, setLayers] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(null);

  const vw = W / zoom, vh = H / zoom;
  const vx = (W - vw) / 2 - pan.x, vy = (H - vh) / 2 - pan.y;
  const ids = Object.keys(pos).filter((i) => i !== VIRTUAL);
  const tip = hover ? d.devices[hover] : null;

  return (
    <div className="relative h-full w-full select-none" style={{ height }}>
      <svg viewBox={`${vx} ${vy} ${vw} ${vh}`} className="h-full w-full cursor-grab active:cursor-grabbing"
        onWheel={(e) => setZoom((z) => Math.min(3, Math.max(0.6, z * (e.deltaY < 0 ? 1.1 : 0.9))))}
        onMouseDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y }; }}
        onMouseMove={(e) => {
          if (!drag.current) return;
          const k = (W / (e.currentTarget.clientWidth || W)) / zoom;
          setPan({ x: drag.current.px + (e.clientX - drag.current.x) * k, y: drag.current.py + (e.clientY - drag.current.y) * k });
        }}
        onMouseUp={() => { drag.current = null; }} onMouseLeave={() => { drag.current = null; }}
        onClick={(e) => { if (e.target === e.currentTarget) onSelect(null); }}>
        <defs>
          {(Object.keys(PALETTE) as NodeRole[]).map((r) => (
            <linearGradient key={r} id={`top-${r}`} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor={PALETTE[r].top} />
              <stop offset="1" stopColor={PALETTE[r].left} />
            </linearGradient>
          ))}
          <radialGradient id="ground" cx="50%" cy="55%" r="60%">
            <stop offset="0" stopColor="#1b2027" stopOpacity="0.9" />
            <stop offset="1" stopColor="#07080a" stopOpacity="0" />
          </radialGradient>
          <filter id="blur6"><feGaussianBlur stdDeviation="6" /></filter>
        </defs>

        <ellipse cx={W / 2} cy={H / 2 + 30} rx={W * 0.62} ry={H * 0.55} fill="url(#ground)" />
        {Array.from({ length: 14 }).map((_, i) => (
          <line key={i} x1={-200 + i * 100} y1={H + 40} x2={300 + i * 100} y2={-40} stroke="#ffffff06" />
        ))}
        {!compact && BUILDINGS.map(([bx, by], i) => (
          <g key={i} opacity={0.16}>
            <IsoBox x={bx} y={by} role="silent" scale={0.8 + (i % 3) * 0.15} />
            {[0, 1, 2].map((k) => <rect key={k} x={bx - 26 + k * 9} y={by + 14 + k * 4} width={4} height={5} fill="#ffb347" opacity={0.8} />)}
          </g>
        ))}

        {Object.entries(parent).map(([c, p]) => {
          if (!p || !pos[p] || !pos[c]) return null;
          const a = pos[p], b = pos[c];
          const role = roles[c] ?? "healthy";
          const bad = role !== "healthy" && role !== "silent";
          const col = bad ? PALETTE[role === "root" ? "root" : "downstream"].line : PALETTE.healthy.line;
          const path = `M${a.x},${a.y + 44} C${a.x},${(a.y + b.y) / 2 + 10} ${b.x},${(a.y + b.y) / 2 - 10} ${b.x},${b.y - 20}`;
          const dim = selected && selected !== c && selected !== p;
          return (
            <g key={c} opacity={dim ? 0.35 : 1}>
              <path d={path} fill="none" stroke={col} strokeWidth={7} opacity={0.35} filter="url(#blur6)" />
              <path d={path} fill="none" stroke={col} strokeWidth={2.2} strokeDasharray={p === VIRTUAL ? "4 6" : bad ? "8 4" : undefined}
                className={bad ? "animate-dash" : undefined} />
            </g>
          );
        })}

        {flat && pos[VIRTUAL] && (
          <g>
            <circle cx={pos[VIRTUAL].x} cy={pos[VIRTUAL].y} r={16} fill="none" stroke="#5b636e" strokeDasharray="3 4" />
            <text x={pos[VIRTUAL].x} y={pos[VIRTUAL].y - 26} textAnchor="middle" className="fill-slate-400 text-[12px]">
              no topology provided
            </text>
          </g>
        )}

        {ids.map((id) => {
          const p = pos[id];
          const role = roles[id] ?? "healthy";
          const ap = (d.devices[id]?.role ?? d.topology.devices.find((t) => t.id === id)?.role) === "access_point";
          const isSel = selected === id;
          const h = d.health?.[id];
          return (
            <g key={id} className="cursor-pointer" onClick={(e) => { e.stopPropagation(); onSelect(isSel ? null : id); }}
              onMouseEnter={() => setHover(id)} onMouseLeave={() => setHover(null)}
              opacity={selected && !isSel ? 0.75 : 1}>
              {role === "root" && [0, 0.8, 1.6].map((delay) => (
                <ellipse key={delay} cx={p.x} cy={p.y + 14} rx={88} ry={38} fill="none" stroke="#ff4d42" strokeWidth={2}
                  className="animate-pulsering" style={{ transformBox: "fill-box", transformOrigin: "center", animationDelay: `${delay}s` }} />
              ))}
              {isSel && <ellipse cx={p.x} cy={p.y + 14} rx={76} ry={33} fill="none" stroke="#ff8a3d" strokeWidth={2.5} strokeDasharray="5 4" />}
              {ap ? <AccessPoint x={p.x} y={p.y} role={role} /> : <IsoBox x={p.x} y={p.y} role={role} />}
              {role === "root" && (
                <g className="glow-alarm" transform={`translate(${p.x},${p.y - (ap ? 50 : 76)})`}>
                  <path d="M0,-22 L20,14 L-20,14 Z" fill="#ef3b33" stroke="#ffb3ad" strokeWidth={1.5} strokeLinejoin="round" />
                  <rect x={-2} y={-10} width={4} height={13} rx={2} fill="#fff" />
                  <circle cx={0} cy={8} r={2.4} fill="#fff" />
                </g>
              )}
              <g transform={`translate(${p.x},${p.y + (ap ? 50 : 70)})`}>
                <rect x={-(id.length * 4.6 + 14)} y={-13} width={id.length * 9.2 + 28} height={26} rx={7}
                  fill="#07080acc" stroke={isSel ? "#ff8a3d" : "#ffffff1a"} />
                <text textAnchor="middle" y={4.5} className="text-[14px] font-medium" fill={PALETTE[role].text}>{id}</text>
              </g>
              {layers && h && (
                <g transform={`translate(${p.x + 40},${p.y - 30})`}>
                  <rect x={-4} y={-13} width={64} height={20} rx={10} fill="#07080add" stroke="#ffffff22" />
                  <text x={28} y={1} textAnchor="middle" className="mono" fill={h.health_index < 0.5 ? "#ff8a80" : "#7ef0e0"}>
                    HI {h.health_index.toFixed(2)}
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </svg>

      {tip && hover && (
        <div className="pointer-events-none absolute left-4 top-4 w-64 animate-fadein rounded-xl border border-white/10 bg-ink-900/95 p-3 text-xs shadow-xl">
          <div className="mb-1 flex items-center justify-between">
            <span className="font-semibold text-slate-100">{hover}</span>
            <span className="text-slate-400">{tip.status}</span>
          </div>
          <div className="text-slate-400">{tip.role ?? "device"} · {tip.samples} sample(s) · completeness {Math.round(tip.completeness * 100)}%</div>
          {d.health?.[hover]?.active_signals.length ? (
            <div className="mt-1.5 text-alarm-400">alarms: {d.health[hover].active_signals.join(", ")}</div>
          ) : <div className="mt-1.5 text-teal-300">no alarm-level signal</div>}
          <div className="mt-1 text-slate-500">click for details</div>
        </div>
      )}

      <div className="absolute right-3 top-1/2 flex -translate-y-1/2 flex-col gap-1 rounded-xl border border-white/10 bg-ink-900/80 p-1.5 backdrop-blur">
        {[
          { icon: Crosshair, label: "Recenter", fn: () => { setZoom(1); setPan({ x: 0, y: 0 }); } },
          { icon: Plus, label: "Zoom in", fn: () => setZoom((z) => Math.min(3, z * 1.2)) },
          { icon: Minus, label: "Zoom out", fn: () => setZoom((z) => Math.max(0.6, z / 1.2)) },
          { icon: Layers, label: "Health overlay", fn: () => setLayers((l) => !l), active: layers },
        ].map(({ icon: I, label, fn, active }) => (
          <button key={label} title={label} aria-label={label} onClick={fn}
            className={cn("rounded-lg p-2 text-slate-300 transition hover:bg-white/10 hover:text-white", active && "bg-ember-500/20 text-ember-300")}>
            <I size={17} />
          </button>
        ))}
      </div>

      <div className="absolute bottom-2 left-3 flex flex-wrap gap-3 text-[11px] text-slate-400">
        {(["root", "downstream", "secondary", "degraded", "healthy", "silent"] as NodeRole[])
          .filter((r) => Object.values(roles).includes(r))
          .map((r) => (
            <span key={r} className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full" style={{ background: PALETTE[r].line }} />
              {r === "root" ? "root cause" : r === "silent" ? "no telemetry" : r}
            </span>
          ))}
      </div>
    </div>
  );
}
