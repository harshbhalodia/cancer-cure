import { useCallback, useEffect, useState } from "react";
import { api, workspaceUrl, type ActionsView, type CareAction } from "../api";

function FollowUp({ action, onSave }: { action: CareAction; onSave: () => Promise<void> }) {
  const [owner, setOwner] = useState(action.owner);
  const [due, setDue] = useState(action.due_date);
  const [answer, setAnswer] = useState(action.answer);
  const [status, setStatus] = useState(action.status);
  const [source, setSource] = useState(action.answer_source);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const save = async () => {
    setBusy(true); setError("");
    try {
      await api.updateAction(action.id, { owner, due_date: due, answer, status, answer_source: source });
      await onSave();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <details className="follow-up">
    <summary><span className={`badge ${action.overdue ? "attention" : ""}`}>{action.overdue ? "Overdue" : action.status.replace(/_/g, " ")}</span> <strong>{action.title}</strong>
      <div className="muted small">{action.priority} · {action.owner} · due {action.due_date || "not set"}</div>
    </summary>
    <p className="small">{action.why}</p>
    {action.evidence.kind && <div className="small muted">Source: {action.evidence.kind}
      {action.evidence.document_id && <> · <a href={workspaceUrl(`/api/documents/${action.evidence.document_id}/file`)} target="_blank" rel="noreferrer">Original report</a></>}
      {action.evidence.quote && <div className="quote">{action.evidence.quote}</div>}
    </div>}
    <div className="form-grid">
      <label>Responsible person<input value={owner} onChange={(e) => setOwner(e.target.value)} maxLength={120} /></label>
      <label>Follow-up date<input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></label>
      <label>Status<select value={status} onChange={(e) => setStatus(e.target.value as CareAction["status"])}>
        <option value="open">Open</option><option value="contacted">Contacted team</option><option value="awaiting_reply">Awaiting reply</option>
        <option value="resolved">Resolved with answer</option><option value="dismissed">Dismissed</option>
      </select></label>
      <label>Who supplied the answer?<select value={source} onChange={(e) => setSource(e.target.value as CareAction["answer_source"])}>
        <option value="you">You</option><option value="clinician">Clinician (reported by you)</option><option value="coordinator">Coordinator (reported by you)</option>
      </select></label>
    </div>
    <label>Answer / resolution<textarea value={answer} onChange={(e) => setAnswer(e.target.value)} maxLength={4000} rows={3} /></label>
    <p className="small muted">These answers are entered by you, not independently verified. Closing a task does not clear a medical alert.</p>
    {error && <div className="alert urgent" role="alert">{error}</div>}
    <button disabled={busy || !owner.trim()} onClick={() => void save()}>{busy ? "Saving..." : "Save follow-up"}</button>
    <details><summary className="small">Change history</summary>
      <ul className="small">{action.history.map((h, i) => <li key={i}>{h.at.slice(0, 16)}: {Object.entries(h.changes).map(([k, v]) => `${k}: ${v}`).join("; ")} {h.note}</li>)}</ul>
    </details>
  </details>;
}

export default function Actions({ version }: { version: number }) {
  const [data, setData] = useState<ActionsView | null>(null);
  const [title, setTitle] = useState("");
  const [why, setWhy] = useState("");
  const [owner, setOwner] = useState("You");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState("");
  const [copied, setCopied] = useState(false);
  const load = useCallback(async () => { setData(await api.actions()); }, []);
  useEffect(() => { void load().catch((e: Error) => setError(e.message)); }, [load, version]);
  useEffect(() => {
    const refresh = () => { void load().catch((e: Error) => setError(e.message)); };
    window.addEventListener("cc-watch-changed", refresh);
    return () => window.removeEventListener("cc-watch-changed", refresh);
  }, [load]);
  const run = async (task: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await task(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <div className="card actions-panel">
    <div className="card-head"><h3>Your follow-ups</h3><button disabled={busy} onClick={() => void run(async () => { setSummary((await api.visitSummary()).text); setCopied(false); })}>Prepare visit summary</button></div>
    <p className="small muted">{data?.note || "Track questions, contacts and answers. This is not a treatment plan."}</p>
    {error && <div className="alert urgent" role="alert">{error}</div>}
    {!data && !error && <p className="muted">Loading follow-ups...</p>}
    {data && <>
      {data.focus.length ? data.focus.map((a) => <FollowUp key={`${a.id}:${a.updated_at}`} action={a} onSave={load} />)
        : <p>No open follow-ups. Add a question or track a suggestion below.</p>}
      {data.items.length > data.focus.length && <details><summary>All follow-ups ({data.items.length})</summary>
        {data.items.filter((a) => !data.focus.some((f) => f.id === a.id)).map((a) => <FollowUp key={`${a.id}:${a.updated_at}`} action={a} onSave={load} />)}
      </details>}
      <details><summary>Add a follow-up question</summary>
        <label>Question / task<input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} placeholder="What needs an answer?" /></label>
        <label>Why it matters<textarea value={why} onChange={(e) => setWhy(e.target.value)} maxLength={2000} rows={2} /></label>
        <div className="form-grid"><label>Responsible person<input value={owner} onChange={(e) => setOwner(e.target.value)} maxLength={120} /></label>
          <label>Follow-up date<input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></label></div>
        <button className="primary" disabled={busy || !title.trim() || !owner.trim()} onClick={() => void run(async () => {
          await api.addAction({ title, why, owner, due_date: due }); setTitle(""); setWhy(""); setDue(""); await load();
        })}>Add follow-up</button>
      </details>
      {!!data.suggestions.length && <details><summary>From alerts, advice and trial questions ({data.suggestions.length})</summary>
        {data.suggestions.map((s) => <div className="suggested-action" key={s.source_key}><div><strong>{s.title}</strong><p className="small muted">{s.why}</p></div>
          <button disabled={busy} onClick={() => void run(async () => { await api.addAction({ source_key: s.source_key }); await load(); })}>Track this</button></div>)}
      </details>}
    </>}
    {summary && <div className="visit-preview">
      <h4>Review before sharing</h4><p className="small">This stays on your computer. Only copy it after reviewing; nothing is sent automatically.</p>
      <pre className="draft">{summary}</pre>
      <button disabled={busy} onClick={() => void run(async () => { await navigator.clipboard.writeText(summary); setCopied(true); })}>{copied ? "Copied" : "Copy reviewed summary"}</button>
      <button onClick={() => setSummary("")}>Close preview</button>
    </div>}
  </div>;
}
