import type { Diagnosis, Status } from "./types";

const ACRONYM: Record<string, string> = { Dns: "DNS", Dhcp: "DHCP", Wifi: "Wi-Fi", Http: "HTTP", Cpu: "CPU", Trustguard: "TrustGuard" };
export const pretty = (s: string | null | undefined) =>
  (s ?? "").replace(/_agent$/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\b(Dns|Dhcp|Wifi|Http|Cpu|Trustguard)\b/g, (w) => ACRONYM[w]);

export const pct = (x: number, d = 0) => `${(x * 100).toFixed(d)}%`;

export const fmt = (v: unknown): string => {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) < 10 ? 2 : 1);
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
};

export const cn = (...xs: (string | false | null | undefined)[]) => xs.filter(Boolean).join(" ");

/** Headline + accent word, derived from the real report. */
export function headline(d: Diagnosis): { title: string; accent: string; severity: string; tone: "alarm" | "ember" | "teal" | "slate" } {
  const r = d.report;
  const cause = pretty(r.root_cause_type ?? r.leading_hypothesis ?? "");
  const critical = (r.root_cause_devices ?? []).some((x) => d.devices[x]?.status === "Critical");
  switch (r.status) {
    case "diagnosed": return { title: cause, accent: "Detected", severity: critical ? "CRITICAL" : "MAJOR", tone: "alarm" };
    case "tentative": return { title: `Possible ${cause}`, accent: "Suspected", severity: "WARNING", tone: "ember" };
    case "insufficient_evidence": return { title: "Root Cause", accent: "Undetermined", severity: "INCONCLUSIVE", tone: "slate" };
    case "healthy": return { title: "Network", accent: "Healthy", severity: "ALL CLEAR", tone: "teal" };
    default: return { title: "Diagnosis", accent: "Failed", severity: "ERROR", tone: "alarm" };
  }
}

export const STATUS_LABEL: Record<Status, string> = {
  healthy: "Healthy", diagnosed: "Diagnosed", tentative: "Tentative",
  insufficient_evidence: "Insufficient evidence", error: "Error",
};

export type NodeRole = "root" | "downstream" | "secondary" | "degraded" | "healthy" | "silent";

export function nodeRoles(d: Diagnosis): Record<string, NodeRole> {
  const r = d.report;
  const out: Record<string, NodeRole> = {};
  const ids = new Set([...d.topology.devices.map((x) => x.id), ...Object.keys(d.devices)]);
  for (const id of ids) out[id] = d.devices[id] ? "healthy" : "silent";
  for (const id of r.affected_devices ?? []) out[id] = "degraded";
  for (const id of r.downstream_affected ?? []) out[id] = "downstream";
  for (const f of r.secondary_findings ?? []) out[f.device_id] = "secondary";
  for (const id of r.root_cause_devices ?? []) if (r.status !== "healthy") out[id] = "root";
  return out;
}
