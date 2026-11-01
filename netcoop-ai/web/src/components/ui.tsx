import type { ReactNode } from "react";
import { cn } from "../util";

export function Ring({ value, size = 104, label = "Confidence", tone = "#ff6a1a" }: { value: number; size?: number; label?: string; tone?: string }) {
  const r = size / 2 - 9;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="#ffffff12" strokeWidth={8} fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r} stroke={tone} strokeWidth={8} fill="none" strokeLinecap="round"
          strokeDasharray={`${c * value} ${c}`} style={{ filter: `drop-shadow(0 0 6px ${tone})`, transition: "stroke-dasharray .6s" }} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-semibold text-white">{Math.round(value * 100)}%</span>
        <span className="text-[10px] text-slate-400">{label}</span>
      </div>
    </div>
  );
}

export function Bar({ value, tone = "ember", className }: { value: number; tone?: "ember" | "slate" | "teal" | "alarm"; className?: string }) {
  const col = { ember: "from-ember-600 to-ember-400 shadow-[0_0_10px_rgba(255,106,26,.6)]", slate: "from-slate-500 to-slate-400",
    teal: "from-teal-500 to-teal-300", alarm: "from-alarm-600 to-alarm-400" }[tone];
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-white/[0.08]", className)}>
      <div className={cn("h-full rounded-full bg-gradient-to-r transition-all duration-500", col)} style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }} />
    </div>
  );
}

export function Panel({ title, right, children, className }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("panel p-5", className)}>
      {(title || right) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          <h3 className="text-[15px] font-semibold text-slate-100">{title}</h3>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Tabs<T extends string>({ value, onChange, items, className }: {
  value: T; onChange: (v: T) => void; items: { id: T; label: ReactNode }[]; className?: string;
}) {
  return (
    <div className={cn("flex gap-1 rounded-xl border border-white/[0.06] bg-black/20 p-1", className)}>
      {items.map((it) => (
        <button key={it.id} onClick={() => onChange(it.id)}
          className={cn("flex-1 rounded-lg px-3 py-2 text-sm font-medium transition",
            value === it.id ? "bg-ember-500/15 text-white shadow-ember" : "text-slate-400 hover:text-slate-200")}>
          {it.label}
        </button>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-white/10 p-6 text-center text-sm text-slate-400">{children}</div>;
}

export function Modal({ open, onClose, children, wide }: { open: boolean; onClose: () => void; children: ReactNode; wide?: boolean }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-6 pt-24 backdrop-blur-sm" onClick={onClose}>
      <div className={cn("panel max-h-[75vh] w-full animate-fadein overflow-auto p-5", wide ? "max-w-4xl" : "max-w-xl")}
        onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

export function StatusDot({ ok, warn }: { ok: boolean; warn?: boolean }) {
  return <span className={cn("inline-block h-2 w-2 rounded-full", ok ? "bg-teal-400 shadow-[0_0_8px_#34d6c4]" : warn ? "bg-ember-400" : "bg-alarm-500")} />;
}
