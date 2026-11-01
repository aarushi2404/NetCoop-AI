import type { Catalog, Diagnosis, IncidentSpec, Remediation, VerifyResult, WhatIfResult } from "./types";

async function call<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}: response was not JSON` }));
  if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
  return data as T;
}

export const api = {
  catalog: () => call<Catalog>("/api/catalog"),
  diagnose: (spec: IncidentSpec) => call<Diagnosis>("/api/diagnose", spec),
  whatif: (spec: IncidentSpec, device: string, metric: string, value: number | string) =>
    call<WhatIfResult>("/api/whatif", { ...spec, device, metric, value }),
  remediate: (spec: IncidentSpec, hypothesis: string | null, efficacy: number) =>
    call<Remediation>("/api/remediate", { ...spec, hypothesis, efficacy }),
  verify: (spec: IncidentSpec, tamper: "none" | "raw" | "vote" | "drop" | "audit") =>
    call<VerifyResult>("/api/verify", { ...spec, tamper }),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  benchmarks: () => call<{ internal: any; organizer: any; interop_markdown: string | null }>("/api/benchmarks"),
};
