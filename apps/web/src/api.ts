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
  setRecStatus: (id: number, status: string, note?: string) => call<Rec[]>(`/recommendations/${id}`, json("PATCH", { status, note })),
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
