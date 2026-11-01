// Shapes returned by `python -m netcoop serve-api` (see netcoop/api.py). Only fields the UI reads are typed.

export type Status = "healthy" | "diagnosed" | "tentative" | "insufficient_evidence" | "error";
export type FaultMode = "healthy" | "transient" | "permanent" | "adversarial";

export interface IncidentSpec {
  source: "scenario" | "organizer" | "upload";
  name: string;
  seed?: number;
  raw?: unknown;
  faults?: Record<string, FaultMode>;
  remote?: string;
  trustguard?: boolean;
  simulation?: boolean;
}

// ---- TrustGuard (netcoop/trustguard.py)
export type TgDecision = "trusted" | "flagged" | "unverifiable";
export interface TgBrief { record_id: string; agent: string; device_id: string | null; kind: string; subject: string;
  reported: unknown; reason_codes: string[]; explanation: string }
export interface TgSummary { checked: number; accepted: number; flagged: number; unverifiable: number;
  votes_checked: number; votes_flagged: number; votes_unverifiable: number }
export interface TgView { status: string; root_cause_type: string | null; leading_hypothesis: string | null;
  root_cause_devices: string[]; confidence: number }
export interface TgBeforeAfter { computed: boolean; engine?: string; reason?: string; before: TgView; after: TgView;
  diagnosis_changed: boolean; confidence_delta: number; sufficient_evidence_after?: boolean }
export interface TgAgentStats { checked: number; trusted: number; flagged: number; unverifiable: number }
export interface TgReport { status: "audited" | "unavailable"; reason?: string; audit_message_id?: string;
  summary: TgSummary; flagged: TgBrief[]; unverifiable: TgBrief[]; agents: Record<string, TgAgentStats>;
  before_after?: TgBeforeAfter }
export interface TgRecord {
  record_id: string; kind: string; agent: string; device_id: string | null; finding_id: string | null;
  message_id: string | null; subject: string; reported: unknown; decision: TgDecision; reason_codes: string[];
  explanation: string; finding_sha256: string | null; timestamp: string; audit_version: string; effect: string;
  expected: { ceiling?: number | null; specific_support?: number | null; ceiling_tolerance?: number; strength?: number | null;
    value?: unknown; degraded?: string[] };
  telemetry_refs: { signal?: string; metric: string; value: unknown; strength?: number | null; record_indexes: number[] }[];
  original_finding?: { votes: Record<string, number>; signal_strength: Record<string, number> } | null;
}
export interface TgTrace { audit_message_id: string; request_message_id: string | null; audit_version: string;
  summary: TgSummary; agents: Record<string, TgAgentStats>; parameters: Record<string, number>;
  before_after: TgBeforeAfter | null; records: TgRecord[]; note: string }

export interface Catalog {
  scenarios: { name: string; description: string }[];
  organizer: { name: string; devices: number; records: number }[];
  fixes: Record<string, string>;
  agents: string[];
}

export interface QualityFlag { code: string; metric: string | null; message: string }

export interface Device {
  metrics: Record<string, number>;
  status: string;
  samples: number;
  role: string | null;
  parent: string | null;
  completeness: number;
  trends: Record<string, { first: number; last: number }>;
  quality: QualityFlag[];
}

export interface Gate { gate: string; value: unknown; need: string; passed: boolean; explanation: string }

export interface Abstention {
  why_not_committed: string[];
  leading_hypothesis: string | null;
  summary: string;
  required_measurements: { device_id: string; metric: string; signal: string; status: string; decides: string[] }[];
}

export interface RankEntry { hypothesis: string; score: number; base_vote: number; coverage: number; voters: string[] }

export interface Report {
  incident_id: string;
  status: Status;
  suspected_root_cause: string;
  root_cause_type?: string | null;
  leading_hypothesis?: string | null;
  confidence: number;
  confidence_category: string;
  affected_devices: string[];
  root_cause_devices?: string[];
  downstream_affected?: string[];
  supporting_evidence: { metric: string; value: unknown; device_id: string; interpretation: string }[];
  alternative_causes: string[];
  recommended_actions: string[];
  limitations: string[];
  hypothesis_ranking?: RankEntry[];
  conflicts_resolved?: { agent: string; agent_hypothesis: string; resolution: string }[];
  secondary_findings?: { device_id: string; hypothesis: string; score: number; suspected_cause: string }[];
  decision_gates?: Gate[];
  confidence_breakdown?: Record<string, number>;
  abstention?: Abstention;
  hedge?: Abstention;
  challenge_round?: { device_id: string; margin_before: number; margin_after: number; winner_changed: boolean } | null;
  data_quality: { completeness: number; records_accepted?: number; records_rejected?: number;
    issues: { level: string; device_id: string | null; message: string }[] };
  agent_health: Record<string, { status: string; attempts: number; error?: string }>;
  protocol?: { messages_exchanged: number };
  trustguard?: TgReport;
}

export interface RawSample { record_index: number; path: (string | number)[]; raw: unknown; value: unknown; timestamp: string | null }

export interface Evidence {
  id: string; device_id: string; signal: string; metric: string; value: unknown; unit: string | null;
  threshold: string; onset: string | null; strength: number; state: string; aggregation: string;
  raw_samples: RawSample[]; observed_by: { agent: string; message_id: string; source_message_id?: string | null;
    finding_id: string; strength: number }[];
  explains: string[]; expected_by: string[]; rules_out: string[];
}

export interface ExpectedSignal { signal: string; metric: string; value: unknown; strength: number | null; state: string; threshold: string }

export interface Hypothesis {
  hypothesis: string;
  verdict: "selected" | "leading (not committed)" | "rejected" | "not supported";
  score: number; base_vote: number; coverage: number; graded_support: number | null;
  votes: { agent: string; vote: number; message_id: string; weight: number }[];
  supporting_evidence: string[]; unexplained_evidence: string[];
  expected_signals: ExpectedSignal[];
  contradicting: { signal: string; metric: string; why: string }[];
  missing: ExpectedSignal[];
  rejection_reasons: string[]; why_selected: string[];
  excluded_by_trustguard?: { record_id: string; agent: string; reported: number; decision: TgDecision; reason_codes: string[] }[];
}

export interface AgentTrace {
  agent: string; transport: string; domain: string | null; health: string; card_message_id: string | null;
  messages_sent: number; message_types: string[]; findings_message_id?: string; devices_flagged?: string[];
  remote_endpoint?: string;
  on_root_device?: { votes: Record<string, number>; signals: Record<string, number>;
    top_vote: { hypothesis: string; vote: number } | null; notes: string[] };
  agrees_with_conclusion?: boolean;
  leave_one_out?: { status: string; hypothesis: string | null; confidence: number; conclusion_changed: boolean;
    confidence_delta: number; contribution: string };
}

export interface WhatIfScenario {
  kind: string; signal: string; metric: string; device_id: string; from: unknown; to: unknown; change: string;
  result: { status: string; hypothesis: string | null; confidence: number }; flips_conclusion: boolean;
}

export interface Check { check: string; target: string; ok: boolean; detail: string }
export interface Checks { passed: number; failed: number; total: number; verified: boolean; failures: Check[]; checks: Check[] }

export interface ProofTrace {
  trace_version: string;
  incident_id: string;
  conclusion: { status: Status; hypothesis: string | null; root_cause_devices: string[]; confidence: number; summary: string };
  integrity: { message_count: number; chain_sha256: string;
    messages: { i: number; message_id: string; msg_type: string; sender: string; recipient: string; sha256: string }[] };
  data_quality: { completeness: number; stale_devices: string[]; quality_flags: Record<string, QualityFlag[]>; records_rejected: number };
  primary_device?: string;
  evidence?: Evidence[];
  hypotheses?: Hypothesis[];
  agents?: AgentTrace[];
  conflicts?: { agent: string; agent_hypothesis: string; resolution: string }[];
  sensitivity?: { baseline_reproduced: boolean; scenarios: WhatIfScenario[]; decisive: string[] };
  missing_information?: { device_id: string; metric: string; decides: string[]; status?: string }[];
  remediation_check?: { compared: boolean; selected?: string; resolving?: string[]; verdict?: string;
    results?: Record<string, { action: string; outcome: string; after_status: string; residual_signals: string[] }> };
  healthy_check?: { device_id: string; max_signal: [string, number] }[];
  checks: Checks;
  note?: string;
  trustguard?: TgTrace;
}

export interface BusMessage {
  message_id: string; correlation_id: string; sender: string; recipient: string; msg_type: string;
  timestamp: string; payload: Record<string, unknown>;
}

export interface Diagnosis {
  incident: { source: string; name: string; seed: number | null; description: string; data_origin: string;
    ground_truth: Record<string, unknown> | null;
    simulation?: { faults: Record<string, string>; applied: boolean; note: string | null } | null;
    faults_applied?: Record<string, string> };
  report: Report;
  prooftrace: ProofTrace;
  devices: Record<string, Device>;
  topology: { devices: { id: string; role: string | null; parent: string | null }[] };
  cards: Record<string, { agent: string; transport: string; protocol_versions: string[]; accepts: string[];
    produces: string[]; hypotheses: string[]; signals: string[]; description: string; negotiation?: Record<string, unknown> }>;
  log: BusMessage[];
  health: Record<string, DeviceHealth>;
}

export interface DeviceHealth { status: string; active_signals: string[]; elevated_signals: Record<string, number>; health_index: number }

export interface Remediation {
  simulated: boolean; reason?: string; hypothesis: string; action: string; efficacy: number;
  before: { status: string; cause: string; confidence: number };
  after: { status: string; cause: string; confidence: number };
  devices: { device_id: string; role: string; before: DeviceHealth; after: DeviceHealth;
    metrics_changed: Record<string, { before: number; after: number }> }[];
  expected_improvements: { device_id: string; signal: string; metric: string; before: unknown; after: unknown; expected?: string; achieved: boolean }[];
  residual_signals: string[]; outcome: "resolved" | "partially_resolved" | "unresolved"; explanation: string; note: string;
}

export interface WhatIfResult {
  device: string; metric: string; from: unknown; to: unknown; changed: boolean;
  before: Partial<Report>; after: Partial<Report>;
}

export interface VerifyResult extends Checks { tamper: string; what: string }
