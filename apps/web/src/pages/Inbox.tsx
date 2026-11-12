import { useCallback, useEffect, useState } from "react";
import { api, type Job, type JobsSummary, type ScanProposal } from "../api";
import CaseReview, { type CaseReviewData } from "./CaseReview";
import ScanReview from "./ScanReview";

const KIND_LABEL: Record<string, string> = { ingest: "adding to library", analyze: "reading with the local AI", ocr: "reading the scanned pages", journey: "finding dated events", actions: "finding advisors' recommendations", meds: "finding medicines", plan: "building your plan" };
const KIND_SHORT: Record<string, string> = { ingest: "add to library", analyze: "analyse", ocr: "read scan", journey: "build journey", actions: "find recommendations", meds: "find medicines", plan: "build plan" };

export default function Inbox({ onChanged }: { onChanged: () => void }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [summary, setSummary] = useState<JobsSummary | null>(null);
  const [scan, setScan] = useState<{ job: Job; proposal: ScanProposal } | null>(null);
  const [caseReview, setCaseReview] = useState<{ job: Job; review: CaseReviewData } | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [j, s] = await Promise.all([api.jobs(), api.jobsSummary()]);
    setJobs(j);
    setSummary(s);
  }, []);
  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 3000);
    return () => clearInterval(t);
  }, [load]);

  async function openScan(job: Job) {
    setError("");
    try {
      const r = await api.jobResult(job.id);
      if (r.scan) setScan({ job, proposal: r.scan });
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function openCase(job: Job) {
    setError("");
    try {
      const r = await api.jobResult(job.id);
      if (r.case && r.document_id) setCaseReview({ job, review: { documentId: r.document_id, filename: job.filename, proposal: r.case } });
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function resolve(job: Job, part: "scan" | "case") {
    await api.resolveJob(job.id, part);
    await load();
    onChanged();
  }

  // "Review all scan reports in turn": after each one is saved, the next opens automatically.
  const [turn, setTurn] = useState<number[]>([]);
  async function startTurn() {
    const ids = jobs.filter((j) => j.review_status === "pending" && j.has_scan).map((j) => j.id).reverse();
    if (ids.length === 0) return;
    setTurn(ids.slice(1));
    const first = jobs.find((j) => j.id === ids[0]);
    if (first) await openScan(first);
  }
  async function openNextInTurn() {
    const [next, ...rest] = turn;
    setTurn(rest);
    if (next === undefined) return;
    const fresh = (await api.jobs()).find((j) => j.id === next && j.has_scan);
    if (fresh) await openScan(fresh);
    else if (rest.length) setTimeout(() => void openNextInTurn(), 0);
  }

  const analyze = jobs.filter((j) => j.kind === "analyze");
  const ready = analyze.filter((j) => j.review_status === "pending");
  const working = jobs.filter((j) => j.status === "queued" || j.status === "running");
  const failed = jobs.filter((j) => j.status === "failed");
  const finished = analyze.filter((j) => j.status === "done" && j.review_status !== "pending");
  const active = (summary?.queued ?? 0) + (summary?.running ?? 0);

  return (
    <section className="page">
      <header className="page-head">
        <h1>Inbox</h1>
        <p>Uploaded files are read in the background. The AI prepares suggestions here; nothing changes in your records until you review and confirm it.</p>
      </header>

      {active > 0 && (
        <div className="card progress-card">
          <div className="spinner small" />
          <div>
            <strong>
              Working on {summary?.current ? summary.current.filename : "the queue"}
              {summary?.current && (
                <span className="muted">
                  {" "}({KIND_LABEL[summary.current.kind] ?? summary.current.kind}{summary.current.detail ? `, ${summary.current.detail}` : ""})
                </span>
              )}
            </strong>
            <div className="muted small">{active} job{active === 1 ? "" : "s"} left. You can keep using the rest of the app; chat answers take priority.</div>
          </div>
        </div>
      )}
      {error && <div className="alert urgent">{error}</div>}

      <p className="muted small">
        Each file can produce up to two suggestions: <b>scan data</b> (lesion sizes and findings → Progress and Next steps) and <b>case-file details</b> (patient facts → Case file).
        Review each one against the original, or choose <em>Not needed</em> to dismiss it without saving anything.
      </p>
      <h2 className="section">Ready for your review {ready.length > 0 && <span className="badge question">{ready.length}</span>}</h2>
      {ready.filter((j) => j.has_scan).length > 0 && (
        <div className="scan-banner">
          <span>
            <b>{ready.filter((j) => j.has_scan).length} scan report{ready.filter((j) => j.has_scan).length === 1 ? "" : "s"} to review.</b> These feed the <b>Progress</b> page.
            {turn.length > 0 && <> {turn.length} more queued after this one.</>}
          </span>
          <button className="primary" onClick={startTurn}>Review scan reports one by one</button>
        </div>
      )}
      {ready.length === 0 && <p className="muted">{active > 0 ? "Suggestions will appear here as each file finishes." : "Nothing waiting. Upload files on the Documents page."}</p>}
      <ul className="doclist">
        {ready.map((j) => (
          <li key={j.id}>
            <div>
              <strong>{j.filename}</strong>
              <div className="muted small">
                {j.has_scan && <div><b>Scan data</b> → sizes and findings for the Progress chart and Next steps.</div>}
                {j.has_case && <div><b>Case-file details</b> → patient facts (diagnosis, stage, treatment…) for the Case file.</div>}
              </div>
            </div>
            <div className="row wrap">
              {j.has_scan && (
                <>
                  <button className="primary" onClick={() => openScan(j)}>Review scan data</button>
                  <button className="small-btn" onClick={() => resolve(j, "scan")} title="Dismiss this suggestion">Not needed</button>
                </>
              )}
              {j.has_case && (
                <>
                  <button className={j.has_scan ? "" : "primary"} onClick={() => openCase(j)}>Review case-file updates</button>
                  <button className="small-btn" onClick={() => resolve(j, "case")} title="Dismiss this suggestion">Not needed</button>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>

      {failed.length > 0 && (
        <>
          <h2 className="section">Needs attention <span className="badge attention">{failed.length}</span></h2>
          <button onClick={() => api.retryFailed().then(load)}>Retry all failed</button>
          <ul className="doclist">
            {failed.map((j) => (
              <li key={j.id}>
                <div>
                  <strong>{j.filename}</strong>
                  <div className="muted small">{j.kind === "ingest" ? "Couldn't be added" : j.kind === "ocr" ? "Couldn't read the scanned pages (pages already read are kept)" : "Couldn't be read by the AI"}: {j.error}</div>
                </div>
                {j.kind !== "ingest" && <button onClick={() => api.retryJob(j.id).then(load)}>Retry</button>}
              </li>
            ))}
          </ul>
        </>
      )}

      {working.length > 0 && (
        <>
          <h2 className="section">In the queue</h2>
          <ul className="queue">
            {working.map((j) => (
              <li key={j.id}>
                <span className={`badge ${j.status === "running" ? "partial" : ""}`}>{j.status === "running" ? "now" : "waiting"}</span>
                {j.filename} <span className="muted small">— {KIND_SHORT[j.kind] ?? j.kind}{j.progress ? ` (${j.progress})` : ""}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {finished.length > 0 && (
        <details className="section">
          <summary>{finished.length} file(s) processed with nothing to review</summary>
          <ul className="queue">
            {finished.map((j) => (
              <li key={j.id}>
                {j.filename} <span className="muted small">— {j.skipped || (j.review_status === "reviewed" ? "reviewed" : "no new information found")}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {scan && (
        <ScanReview
          doc={{ id: scan.job.document_id ?? 0, filename: scan.job.filename }}
          proposal={scan.proposal}
          onClose={() => { setScan(null); setTurn([]); }}
          onSaved={async () => {
            const j = scan.job;
            setScan(null);
            await resolve(j, "scan");
            await openNextInTurn();
          }}
        />
      )}
      {caseReview && (
        <CaseReview
          review={caseReview.review}
          onClose={() => setCaseReview(null)}
          onApplied={async () => {
            const j = caseReview.job;
            setCaseReview(null);
            await resolve(j, "case");
          }}
        />
      )}
    </section>
  );
}
