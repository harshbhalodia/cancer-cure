import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Health, type JobsSummary } from "./api";
import Ask from "./pages/Ask";
import CaseFile from "./pages/CaseFile";
import Documents from "./pages/Documents";
import Inbox from "./pages/Inbox";
import NextSteps from "./pages/NextSteps";
import Progress from "./pages/Progress";
import Timeline from "./pages/Timeline";
import Today from "./pages/Today";

type Tab = "today" | "ask" | "next" | "progress" | "inbox" | "case" | "documents" | "timeline";
const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "today", label: "Today", icon: "🌿" },
  { id: "ask", label: "Ask", icon: "💬" },
  { id: "next", label: "Next steps", icon: "🧭" },
  { id: "progress", label: "Progress", icon: "📈" },
  { id: "inbox", label: "Inbox", icon: "📥" },
  { id: "case", label: "Case file", icon: "🗂️" },
  { id: "documents", label: "Documents", icon: "📄" },
  { id: "timeline", label: "Timeline", icon: "🕒" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("today");
  const [health, setHealth] = useState<Health | null>(null);
  const [role, setRole] = useState(() => localStorage.getItem("cc-role") ?? "caregiver");
  const [docsVersion, setDocsVersion] = useState(0);
  const [toast, setToast] = useState("");
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(0);
  const [jobs, setJobs] = useState<JobsSummary | null>(null);

  useEffect(() => {
    const load = () => api.health().then(setHealth).catch(() => setHealth(null));
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  // Background-processing status. Refresh the library views whenever the finished-job count changes.
  const finishedCount = useRef(-1);
  useEffect(() => {
    const load = () =>
      api.jobsSummary().then((s) => {
        setJobs(s);
        const finished = s.done + s.failed;
        if (finishedCount.current !== -1 && finished !== finishedCount.current) setDocsVersion((v) => v + 1);
        finishedCount.current = finished;
      }).catch(() => undefined);
    void load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);

  const flashToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 7000);
  };

  const uploadFiles = useCallback(async (files: File[]) => {
    const real = files.filter((f) => f.size > 0 || f.name.includes("."));
    if (real.length === 0) return;
    setUploading((n) => n + 1);
    try {
      const r = await api.bulkUpload(real);
      const dup = r.results.filter((x) => x.status === "duplicate").length;
      const bad = r.results.filter((x) => !["queued", "duplicate"].includes(x.status)).length;
      flashToast(
        `${r.queued} file${r.queued === 1 ? "" : "s"} queued for background processing` +
          (dup ? ` · ${dup} already on file` : "") + (bad ? ` · ${bad} skipped (unsupported or empty)` : "") + ". Keep working — results will appear in the Inbox.",
      );
      setDocsVersion((v) => v + 1);
    } catch (e) {
      flashToast(`Upload failed: ${(e as Error).message}`);
    } finally {
      setUploading((n) => n - 1);
    }
  }, []);

  useEffect(() => {
    const over = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes("Files")) {
        e.preventDefault();
        setDragging(true);
      }
    };
    const leave = (e: DragEvent) => {
      if (e.relatedTarget === null) setDragging(false);
    };
    const drop = (e: DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (files.length) void uploadFiles(files);
    };
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [uploadFiles]);

  const aiState = !health ? "Backend offline" : !health.llm.reachable ? "AI offline" : !health.llm.model_available ? "Model not loaded" : "AI ready";
  const aiOk = aiState === "AI ready";

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">✚</span>
          <div>
            <strong>Cancer-Cure</strong>
            <small>Companion</small>
          </div>
        </div>
        <nav>
          {TABS.map((t) => (
            <button key={t.id} className={tab === t.id ? "nav active" : "nav"} onClick={() => setTab(t.id)}>
              <span aria-hidden>{t.icon}</span> {t.label}
              {t.id === "inbox" && jobs && jobs.pending_review + jobs.failed > 0 && <span className="nav-badge">{jobs.pending_review + jobs.failed}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <label>
            I am the
            <select
              value={role}
              onChange={(e) => {
                setRole(e.target.value);
                localStorage.setItem("cc-role", e.target.value);
              }}
            >
              <option value="patient">patient</option>
              <option value="caregiver">caregiver</option>
              <option value="clinician">clinician</option>
            </select>
          </label>
          <div className={aiOk ? "status ok" : "status bad"} title={health?.llm.model}>
            <span className="dot" /> {aiState}
          </div>
          {(uploading > 0 || (jobs && jobs.queued + jobs.running > 0)) && (
            <button className="activity" onClick={() => setTab("inbox")} title="Open the Inbox">
              <span className="spinner mini" />
              {uploading > 0 ? "Uploading…" : `Processing ${jobs!.queued + jobs!.running} file task${jobs!.queued + jobs!.running === 1 ? "" : "s"}`}
            </button>
          )}
          <p className="fineprint">
            Information only — not medical advice. For emergencies call {health?.emergency_number ?? "your local emergency number"}.
          </p>
        </div>
      </aside>
      <main>
        {tab === "today" && <Today version={docsVersion} onOpenNext={() => setTab("next")} />}
        {tab === "ask" && <Ask role={role} aiReady={aiOk} onNavigate={setTab} />}
        {tab === "case" && <CaseFile />}
        {tab === "next" && <NextSteps version={docsVersion} />}
        {tab === "progress" && <Progress version={docsVersion} onOpenDoc={() => setTab("documents")} onOpenInbox={() => setTab("inbox")} />}
        {tab === "inbox" && <Inbox onChanged={() => setDocsVersion((v) => v + 1)} />}
        {tab === "documents" && (
          <Documents version={docsVersion} onUpload={uploadFiles} onOpenCase={() => setTab("case")} onOpenProgress={() => setTab("progress")} onOpenInbox={() => setTab("inbox")} />
        )}
        {tab === "timeline" && <Timeline version={docsVersion} />}
      </main>
      {toast && <div className="toast">{toast}</div>}
      {dragging && <div className="drop-overlay">Drop any number of reports, scans or doctor advice — they’ll be processed in the background</div>}
    </div>
  );
}
