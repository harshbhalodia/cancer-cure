export interface Health {
  ok: boolean;
  llm: { reachable: boolean; model: string; model_available: boolean };
  emergency_number: string;
}
export type CaseData = Record<string, string>;
export interface CaseHistoryEntry {
  id: number;
  value: string;
  as_of: string;
  source: string;
  document_id: number | null;
  filename: string;
  quote: string;
  is_current: boolean;
}
export interface CaseFieldDetail {
  key: string;
  label: string;
  kind: "state" | "identity" | "cumulative";
  value: string;
  as_of: string;
  source: string;
  document_id: number | null;
  history: CaseHistoryEntry[];
}
export interface JourneyEvent {
  id: number;
  date: string;
  category: string;
  title: string;
  detail: string;
  source: string;
  document_id: number | null;
  filename: string;
  quote: string;
}
export interface JourneyItem {
  kind: "event" | "group";
  ids: number[];
  id?: number;
  date: string;
  category: string;
  title: string;
  detail: string;
  source?: string;
  document_id?: number | null;
  filename?: string;
  quote?: string;
  events?: JourneyItem[];
}
export interface JourneyPhase {
  id: string;
  kind: "workup" | "treatment" | "followup";
  title: string;
  subtitle: string;
  start: string;
  end: string;
  count: number;
  items: JourneyItem[];
}
export interface Journey {
  phases: JourneyPhase[];
  undated: JourneyItem[];
  milestones: { date: string; category: string; title: string }[];
  overview: string;
  total: number;
}
export interface CaseDetail {
  fields: Record<string, CaseFieldDetail>;
  journey: Journey;
  events: JourneyEvent[];
  summary: { text: string; generated_at: string; stale: boolean } | null;
}
export interface CaseProposal {
  fields: CaseData;
  as_of: string;
  events: { date: string; category: string; title: string; detail: string; quote: string }[];
  rejected: { item: string; reason: string }[];
}
export interface Doc {
  id: number;
  filename: string;
  doc_type: string;
  doc_date: string;
  page_count: number;
  status: string;
  text_source?: string;
  created_at: string;
  already_uploaded?: boolean;
}
export interface Citation {
  document_id: number;
  page: number;
  filename: string;
  doc_date: string;
}
export interface Flag {
  type: string;
  level?: string;
  reasons?: string[];
  rules?: string[];
  message?: string;
}
export interface Message {
  id?: number;
  ts?: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  flags: Flag[];
}
export interface JobsSummary {
  queued: number;
  running: number;
  done: number;
  failed: number;
  pending_review: number;
  current: { kind: string; filename: string; detail: string } | null;
}
export interface Job {
  id: number;
  kind: "ingest" | "analyze" | "ocr" | "journey" | "actions" | "plan";
  status: "queued" | "running" | "done" | "failed";
  filename: string;
  document_id: number | null;
  error: string;
  review_status: "none" | "pending" | "reviewed";
  skipped: string;
  progress: string;
  has_scan: boolean;
  has_case: boolean;
  created_at: string;
  finished_at: string | null;
}
export interface TimelineEvent {
  id: number;
  ts: string;
  kind: string;
  title: string;
  detail: string;
}
export interface ScanLesion {
  name: string;
  site: string;
  is_target: boolean;
  basis: string;
  size_mm_now: number | null;
  size_mm_prior: number | null;
  suv_max_now: number | null;
  quote: string;
}
export interface ScanFinding {
  text: string;
  category: string;
  certainty: string;
  quote: string;
}
export interface ScanProposal {
  study: { modality: string; date: string; comparator_modality: string; comparator_date: string };
  lesions: ScanLesion[];
  findings: ScanFinding[];
  reported_response: { label: string; criteria: string; sum_prior_mm: number | null; sum_now_mm: number | null; percent_change: number | null; quote: string };
  rejected: { item: string; reason: string }[];
}
export interface SeriesPoint {
  date: string;
  size_mm: number;
  suv_max: number | null;
  kind: "current" | "prior";
  document_id: number;
}
export interface Series {
  lesion: string;
  label: string;
  is_target: boolean;
  points: SeriesPoint[];
}
export interface ScanSummary {
  id: number;
  document_id: number;
  modality: string;
  date: string;
  comparator_date: string;
  comparator_modality: string;
  reported: { label: string; criteria: string; sum_prior: number | null; sum_now: number | null; pct: number | null; quote: string };
  computed: { sum_prior: number; sum_now: number; pct_change: number; category: string; category_label: string; lesions: string[]; caveat: string } | null;
  discrepancy: string | null;
  findings: { id: number; text: string; category: string; certainty: string; quote: string }[];
}
export interface Progress {
  series: Series[];
  scans: ScanSummary[];
}
export interface Requirement {
  key: string;
  label: string;
  group: string;
  why: string;
  ask: string;
  status: "present" | "negative" | "not_done" | "unknown";
  met: boolean;
  value: string;
  source: string;
  document_id: number | null;
  note: string;
}
export interface Decision {
  id: string;
  title: string;
  question: string;
  status: "ready" | "partial" | "blocked";
  met: string[];
  unmet: { key: string; label: string; status: string }[];
  blocked_by: string[];
}
export interface Insight {
  id: string;
  severity: "attention" | "question" | "info";
  title: string;
  detail: string;
  evidence: { document_id: number; quote: string }[];
}
export interface DoNextItem {
  id: string;
  rank: number;
  kind: "recommendation" | "finding" | "check";
  severity: "advice" | "attention" | "question" | "info" | "check";
  score: number;
  title: string;
  detail: string;
  ask?: string;
  notes: string[];
  possibly_done: boolean;
  rec_id?: number;
  nature?: "current" | "conditional" | "verify";
  urgency?: "" | "urgent" | "high";
  source?: string;
  gap_key?: string;
  evidence: { document_id: number | null; filename: string; quote: string }[];
}
export interface Rec {
  id: number;
  text: string;
  category: string;
  advisor: string;
  rec_date: string;
  target_date: string;
  timing: string;
  certainty: string;
  status: "open" | "done" | "dismissed";
  note: string;
  source: string;
  document_id: number | null;
  filename: string;
  quote: string;
  addressed_by: { date: string; title: string }[];
  age_days: number | null;
  nature: "current" | "conditional" | "verify";
  urgency: "" | "urgent" | "high";
  verified: string;
}
export interface PriorityTrack {
  id: string; priority: "urgent" | "high"; label: string; title: string; why: string; facts: string[]; asks: string[];
  evidence: { document_id: number | null; filename: string; quote: string }[]; go_now: string;
}
export interface PriorityQuestion {
  id: string; text: string; why: string; options: { value: string; label: string }[]; detail_label?: string;
}
export interface Priorities {
  tracks: PriorityTrack[]; questions: PriorityQuestion[]; message: { available: boolean; text: string; attach: string };
}
export interface PlanOut {
  id: number;
  pack_id: string;
  title: string;
  markdown: string;
  notes: { id: string; description: string; note: string }[];
  flags: string[];
  used_fallback: boolean;
  created_at: string;
  stale: boolean;
  model: string;
}
export interface PackInfo {
  id: string;
  name: string;
  publisher: string;
  version: string;
  kind: string;
  summary: string;
  examples: string[];
  follow_ups: string[];
  source: string;
  inputs: string[];
  scenarios: string[];
  latest: PlanOut | null;
  running: string | null;
}
export interface Readiness {
  profile: string;
  requirements: Requirement[];
  decisions: Decision[];
  gaps: (Requirement & { unlocks: string[]; blocks: string[]; score: number })[];
  insights: Insight[];
}

export interface Domain { id: string; label: string; icon: string; why: string }
export interface HabitItem {
  id: number; domain: string; title: string; detail: string; when: string; dose: string; prescriber: string; source: string;
  status: string; quote: string; document_id: number | null; filename: string; done: boolean; streak: number; week: boolean[];
}
export interface CheckIn {
  day: string; energy: number | null; mood: number | null; appetite: number | null; pain: number | null;
  sleep_hours: number | null; weight_kg: number | null; symptoms: string; note: string; intention: string; gratitude: string;
}
export interface TodayView {
  day: string; domains: Domain[]; when: string[]; habits: HabitItem[]; suggested_medicines: HabitItem[];
  done: number; total: number; checkin: CheckIn | null; vision: string; checkin_streak: number;
}
export interface Starter { key: string; domain: string; title: string; detail: string; when: string; added: boolean }
export interface TrendMetric {
  key: string; label: string; unit: string; series: { day: string; value: number }[]; this_week: number | null; last_week: number | null;
  n_this: number; n_last: number; verdict: "better" | "worse" | "steady" | "up" | "down" | null; lower_is_better: boolean;
}
export interface Trends {
  day: string; metrics: TrendMetric[]; headlines: { tone: "good" | "watch" | "calm"; text: string }[];
  adherence: { domain: string; label: string; icon: string; habits: number; this_week: number | null; last_week: number | null }[];
  checkin_days: number; checkin_streak: number;
}

export interface ConsultQuestion { key: string; text: string }
export interface ConsultSection { id: string; title: string; priority: "urgent" | "high"; context: string[]; questions: ConsultQuestion[] }
export interface Consult {
  day: string; status: "draft" | "saved"; sections: ConsultSection[]; mention: { id: string; text: string; note: string }[];
  leave_with: string[]; emergency: string; answers: Record<string, { asked: boolean; answer: string }>; advice: string;
  history: { day: string; answered: number; advice: string }[];
}

export interface WatchFlag { key: string; label: string; level: string }
export interface WatchReading {
  id: number; time: string; day: string; energy: number | null; mood: number | null; appetite: number | null; pain: number | null;
  temp_c: number | null; pulse: number | null; spo2: number | null; bp_sys: number | null; bp_dia: number | null; weight_kg: number | null;
  flags: string[]; note: string;
}
export interface WatchSignal {
  id: number; key: string; level: "emergency" | "urgent" | "watch" | "recovering" | "info"; domain: string; title: string; why: string;
  actions: { text: string; kind: "call" | "check" | "do" | "log" }[]; status: "open" | "ack" | "resolved"; ack_note: string;
  since: string; recheck_at: string | null; recheck_due: boolean; resolved_at: string | null;
}
export interface WatchSnapshot {
  active: WatchSignal[]; fresh: string[]; counts: Record<string, number>; highest: string | null; due: number;
  check_now?: string[]; history?: WatchSignal[];
}
export interface WatchTrends {
  metrics: { key: string; label: string; unit: string; series: { day: string; value: number }[]; latest: number; slope_per_day: number | null; lower_is_better: boolean | null }[];
  readings_logged: number; days_with_logs: number;
}
export interface WatchSummary { counts: Record<string, number>; highest: string | null; due: number; fresh: string[]; headline: string }

export interface VaxCandidate {
  id: string; gene: string; change: string; peptide: string; wt_peptide: string; length: number; allele: string; affinity_nM: number;
  presentation_pct: number; wt_affinity_nM: number; vaf: number | null; tpm: number | null; tier: "A" | "B" | "C"; score: number;
  hotspot: boolean; flags: string[]; components: Record<string, number>;
}
export interface VaxRun {
  id: number; dataset: string; created_at: string; pipeline_version: string; predictor: string; input_hash: string; result_hash: string;
  alleles_used: string[]; alleles_unsupported: string[]; warnings: string[]; stages: { name: string; in: number; out: number }[];
  rejected: { variant_id: number; gene: string; change: string; stage: string; reason: string }[]; candidates: VaxCandidate[]; selected: VaxCandidate[];
  tiers: Record<string, number>; params: Record<string, number | number[]>;
}
export interface VaxEval { predictor: string; passed: number; total: number; note: string; checks: { name: string; passed: boolean; detail: string; kind: string }[] }
export interface VaxData { variants: number; hla: string[]; with_normal: number; with_rna: number; need_reference: string[]; sources: string[] }
export interface CohortView {
  label: string; n: number; strong_p10: number; strong_median: number; strong_p90: number; selected_median: number;
  p_strong_ge: Record<string, number>; p_none: number; tierA_median: number; p_tierA_ge3: number; top_score_median: number; germline_selected_mean: number; median_genes: number;
}
export interface CohortSummary {
  complete: boolean; scenarios: number; views: Record<string, CohortView>;
  burden_bins: { label: string; n: number; full_strong_median: number; p_full_strong_ge3: number; p_full_none: number; p_panel_strong_ge1: number }[];
  alleles: { allele: string; n: number; mean_strong: number; delta_vs_all: number }[];
  paired: Record<string, number>; hash?: string; seconds?: number;
  meta?: { predictor: string; peptides: number; alleles: string[]; equivalence: { compared: number; same_best_allele: number; ok: boolean } } | null;
}
export interface AuditScore { true_flags: number; false_flags: number; missed: number; precision: number; recall: number; f1: number; cases_with_inherited_caught: number; clean_cases_with_false_alarm: number }
export interface Audit {
  status: { state: string; message?: string; done?: number; target?: number };
  summary: { cases: number; answered: number; failed: number; with_inherited: number; model: AuditScore; rule: AuditScore; median_secs: number; verdict: string; model_better_than_rule: boolean;
    memo?: { text: string; rejected_draft?: string; problems: string[]; passed: boolean } } | null;
}
export interface Cohort {
  audit: Audit;
  status: { state: string; message?: string; done?: number; target?: number; elapsed_s?: number; rate?: number };
  summary: CohortSummary | null; situation: string[];
  compare: { view_label: string; mutations: number; strong_variants: number; selected: number; percentile: number; median_similar: number; basis: string } | null;
}
export interface TreatmentOptions {
  first: string[]; note: string;
  options: { id: string; title: string; evidence: string; what: string; ask: string[]; records: string[] }[];
}
export interface TrialFinding { status: "ok" | "check" | "missing" | "routine"; text: string; ask: string; key: string }
export interface TrialAssessment {
  id: number; nct_id: string; title: string; status: string; phase: string; verified: string; last_update: string; url: string; fetched_at: string;
  counts: Record<string, number>; notes: string[]; letter: string; profile: Record<string, string>; log: { when: string; text: string }[];
  key_issues: { key: string; status: string; text: string; ask: string; criterion: string }[];
  criteria: { n: number; kind: string; text: string; status: string; findings: TrialFinding[] }[];
  central: { name: string; role: string; phone: string; email: string }[];
  officials: { name: string; affiliation: string; role: string }[];
  sites: { facility: string; city: string; country: string; status: string; contacts: { name: string; role: string; phone: string; email: string }[] }[];
}
export interface TrialBrief { id: number; nct_id: string; title: string; status: string; counts: Record<string, number> }
export interface TrialHit { nct_id: string; title: string; status: string; phase: string; countries: string[] }
export interface FastTrack {
  encouraging: { text: string; source: string }[];
  today: { id: string; title: string; minutes: number; why: string }[];
  steps: { when: string; title: string; detail: string }[];
  drafts: { id: string; title: string; to: string; text: string }[];
  findings: { key: string; text: string; document_id: number; filename: string }[];
  cautions: string[];
}
export interface Vaccine {
  predictor: { available: boolean; name: string };
  readiness: { status: string; unmet: { key: string; label: string; status: string }[]; blocked_by: string[] } | null;
  asks: { key: string; label: string; status: string; met: boolean; why: string; ask: string }[];
  patient: VaxData; synthetic: VaxData; case_hla: string[];
  runs: { id: number; dataset: string; created_at: string; selected: number; tiers: Record<string, number> | null; result_hash: string }[];
  latest: { patient: VaxRun | null; synthetic: VaxRun | null };
  eval: VaxEval | null; jobs: { id: number; kind: string; status: string; detail: string; error: string }[];
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => call<Health>("/health"),
  getCase: () => call<CaseData>("/case"),
  saveCase: (c: CaseData) => call<CaseData>("/case", json("PUT", c)),
  documents: () => call<Doc[]>("/documents"),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return call<Doc>("/documents", { method: "POST", body: form });
  },
  deleteDocument: (id: number) => call<void>(`/documents/${id}`, { method: "DELETE" }),
  extractCase: (id: number) => call<CaseProposal & { proposed: CaseData }>(`/documents/${id}/extract-case`, { method: "POST" }),
  caseDetail: () => call<CaseDetail>("/case/detail"),
  applyProposal: (documentId: number, proposal: { as_of: string; fields: CaseData; events: CaseProposal["events"] }) =>
    call<{ values: number; events: number }>("/case/apply", json("POST", { document_id: documentId, ...proposal })),
  addEntry: (field: string, value: string, as_of: string) => call<CaseDetail>("/case/entries", json("POST", { field, value, as_of })),
  deleteEntry: (id: number) => call<void>(`/case/entries/${id}`, { method: "DELETE" }),
  setEntryDate: (id: number, as_of: string) => call<CaseDetail>(`/case/entries/${id}`, json("PATCH", { as_of })),
  addEvent: (e: { date: string; category: string; title: string; detail?: string }) => call<CaseDetail>("/case/events", json("POST", e)),
  deleteEvent: (id: number) => call<void>(`/case/events/${id}`, { method: "DELETE" }),
  rebuildJourney: () => call<{ queued: number }>("/case/rebuild-journey", { method: "POST" }),
  editEvent: (id: number, patch: { date?: string; title?: string; category?: string; detail?: string }) =>
    call<CaseDetail>(`/case/events/${id}`, json("PATCH", patch)),
  generateSummary: () => call<CaseDetail["summary"]>("/case/summary", { method: "POST" }),
  history: () => call<Message[]>("/chat"),
  chat: (message: string, role: string) => call<Message>("/chat", json("POST", { message, role })),
  timeline: () => call<TimelineEvent[]>("/timeline"),
  bulkUpload: (files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    return call<{ queued: number; results: { filename: string; status: string; detail: string }[] }>("/documents/bulk", { method: "POST", body: form });
  },
  scanInbox: () => call<{ queued: number }>("/inbox/scan", { method: "POST" }),
  jobsSummary: () => call<JobsSummary>("/jobs/summary"),
  jobs: () => call<Job[]>("/jobs"),
  jobResult: (id: number) => call<{ scan: ScanProposal | null; case: CaseProposal | null; document_id: number | null }>(`/jobs/${id}/result`),
  resolveJob: (id: number, part: "scan" | "case") => call<Job>(`/jobs/${id}/resolve`, json("POST", { part })),
  retryFailed: () => call<{ requeued: number }>("/jobs/retry-failed", { method: "POST" }),
  retryJob: (id: number) => call<Job>(`/jobs/${id}/retry`, { method: "POST" }),
  extractScan: (id: number) => call<ScanProposal>(`/documents/${id}/extract-scan`, { method: "POST" }),
  saveScan: (id: number, body: unknown) => call<Progress>(`/documents/${id}/scan`, json("POST", body)),
  progress: () => call<Progress>("/progress"),
  readiness: () => call<Readiness>("/readiness"),
  nextSteps: () => call<{ do_next: DoNextItem[]; counts: { open_recommendations: number; findings: number; checks: number } }>("/nextsteps"),
  recommendations: () => call<Rec[]>("/recommendations"),
  addRecommendation: (r: { text: string; category: string; advisor: string; rec_date: string }) => call<Rec[]>("/recommendations", json("POST", r)),
  setRecStatus: (id: number, status: string, note?: string, verified?: string) => call<Rec[]>(`/recommendations/${id}`, json("PATCH", { status, note, verified })),
  priorities: () => call<Priorities>("/priorities"),
  consult: () => call<Consult>("/consult"),
  watchFlags: () => call<WatchFlag[]>("/watch/flags"),
  watchReadings: () => call<WatchReading[]>("/watch/readings"),
  logReading: (body: Record<string, unknown>) => call<{ reading: WatchReading; snapshot: WatchSnapshot; check_now: string[] }>("/watch/readings", json("POST", body)),
  deleteReading: (id: number) => call<void>(`/watch/readings/${id}`, { method: "DELETE" }),
  watchSignals: () => call<WatchSnapshot>("/watch/signals"),
  watchSummary: () => call<WatchSummary>("/watch/summary"),
  ackSignal: (id: number, note = "", recheck_minutes?: number) => call<WatchSnapshot>(`/watch/signals/${id}/ack`, json("POST", { note, recheck_minutes })),
  watchTrends: () => call<WatchTrends>("/watch/trends"),
  vaccine: () => call<Vaccine>("/vaccine"),
  fasttrack: () => call<FastTrack>("/vaccine/fasttrack"),
  trials: () => call<TrialBrief[]>("/trials"),
  trialSearch: (term: string, country: string) => call<TrialHit[]>(`/trials/search?term=${encodeURIComponent(term)}&country=${encodeURIComponent(country)}`),
  trialAdd: (nct_id: string) => call<TrialAssessment>("/trials", json("POST", { nct_id })),
  trial: (id: number) => call<TrialAssessment>(`/trials/${id}`),
  trialProfile: (id: number, body: Record<string, string>) => call<TrialAssessment>(`/trials/${id}/profile`, json("PUT", body)),
  trialRefresh: (id: number) => call<TrialAssessment>(`/trials/${id}/refresh`, { method: "POST" }),
  trialLog: (id: number, text: string) => call<TrialAssessment>(`/trials/${id}/log`, json("POST", { text })),
  trialDelete: (id: number) => call<void>(`/trials/${id}`, { method: "DELETE" }),
  treatmentOptions: () => call<TreatmentOptions>("/vaccine/options"),
  cohort: () => call<Cohort>("/vaccine/cohort"),
  cohortStart: (n: number) => call<{ started: boolean }>("/vaccine/cohort/start", json("POST", { n })),
  cohortStop: () => call<{ stopping: boolean }>("/vaccine/cohort/stop", { method: "POST" }),
  cohortAudit: (n: number) => call<{ started: boolean }>("/vaccine/cohort/audit", json("POST", { n })),
  vaxAddVariants: (text: string, dataset = "patient", source = "pasted by you") => call<{ read: number; added: number; problems: string[] }>("/vaccine/variants", json("POST", { text, dataset, source })),
  vaxSetHla: (text: string, dataset = "patient") => call<{ alleles: string[]; problems: string[] }>("/vaccine/hla", json("POST", { text, dataset })),
  vaxHlaFromCase: () => call<{ alleles: string[]; problems: string[] }>("/vaccine/hla/from-case", { method: "POST" }),
  vaxClear: (dataset: string) => call<void>(`/vaccine/data?dataset=${dataset}`, { method: "DELETE" }),
  vaxSynthetic: () => call<{ variants: number; hla: string[] }>("/vaccine/synthetic", { method: "POST" }),
  vaxFetchRefs: (dataset = "patient") => call<Record<string, string>>("/vaccine/references/fetch", json("POST", { dataset })),
  vaxRun: (dataset: string) => call<{ queued: boolean }>("/vaccine/run", json("POST", { dataset })),
  vaxVerify: (id: number) => call<{ ok: boolean; stored: string; replayed: string; detail: string }>(`/vaccine/runs/${id}/verify`, { method: "POST" }),
  vaxEvals: (board: boolean) => call<{ queued: boolean }>("/vaccine/evals", json("POST", { board })),
  consultText: () => call<{ text: string }>("/consult/text"),
  saveConsultItem: (key: string, body: { asked?: boolean; answer?: string }) => call<{ ok: boolean }>(`/consult/items/${key}`, json("PUT", body)),
  saveConsultAdvice: (advice: string) => call<{ ok: boolean }>("/consult/advice", json("PUT", { advice })),
  finishConsult: () => call<{ saved: boolean; recommendations: number; event: boolean }>("/consult/finish", { method: "POST" }),
  answerQuestion: (id: string, value: string, detail = "") =>
    call<{ ok: boolean; alert: { level: string; message: string } | null }>(`/priorities/questions/${id}`, json("POST", { value, detail })),
  deleteRecommendation: (id: number) => call<void>(`/recommendations/${id}`, { method: "DELETE" }),
  rebuildRecommendations: () => call<{ queued: number }>("/recommendations/rebuild", { method: "POST" }),
  advisors: () => call<{ packs: PackInfo[]; problems: { file: string; problem: string }[] }>("/advisors"),
  runAdvisor: (id: string) => call<{ queued: boolean }>(`/advisors/${id}/run`, { method: "POST" }),
  putFact: (key: string, body: { status: string; value: string }) => call<{ ok: boolean }>(`/facts/${key}`, json("PUT", body)),
  deleteFact: (key: string) => call<void>(`/facts/${key}`, { method: "DELETE" }),
  today: () => call<TodayView>("/wellness/today"),
  trends: () => call<Trends>("/wellness/trends"),
  library: () => call<{ starters: Starter[]; gentle_set: string[]; domains: Domain[] }>("/wellness/library"),
  addHabit: (h: { domain: string; title: string; detail?: string; when?: string; dose?: string }) => call<{ id: number }>("/wellness/habits", json("POST", h)),
  patchHabit: (id: number, patch: { status?: string; when?: string; title?: string }) => call<{ ok: boolean }>(`/wellness/habits/${id}`, json("PATCH", patch)),
  deleteHabit: (id: number) => call<void>(`/wellness/habits/${id}`, { method: "DELETE" }),
  logHabit: (id: number, done: boolean) => call<{ ok: boolean }>(`/wellness/habits/${id}/log`, json("PUT", { done })),
  addStarters: (keys: string[]) => call<{ added: number }>("/wellness/starters", json("POST", { keys })),
  saveCheckin: (fields: Partial<CheckIn>) => call<{ checkin: CheckIn; alert: { level: string; message: string } | null }>("/wellness/checkin", json("PUT", fields)),
  saveVision: (text: string) => call<{ vision: string }>("/wellness/vision", json("PUT", { text })),
  scanMedicines: () => call<{ queued: number }>("/wellness/medicines/scan", { method: "POST" }),
};
