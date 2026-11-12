import { useCallback, useEffect, useState } from "react";
import { api, type Rec } from "../api";

const CATS = ["test", "imaging", "biopsy", "surgery", "radiotherapy", "chemotherapy", "immunotherapy", "referral", "follow_up", "supportive", "lifestyle", "other"];
const FILTERS: { id: "open" | "done" | "dismissed" | "all"; label: string }[] = [
  { id: "open", label: "Open" }, { id: "done", label: "Done" }, { id: "dismissed", label: "Not relevant" }, { id: "all", label: "All" },
];

function RecCard({ r, onChange }: { r: Rec; onChange: (recs: Rec[]) => void }) {
  const [note, setNote] = useState(r.note);
  const [editing, setEditing] = useState(false);
  const act = (status: string, withNote?: string) => api.setRecStatus(r.id, status, withNote).then(onChange);
  return (
    <li className={`rec-card ${r.status}`}>
      <div className="rec-top">
        <div className="grow">
          <strong>{r.text}</strong>
          <div className="muted small">
            {r.advisor || "Advisor not named"} · {r.rec_date || "date unknown"} · <span className="badge">{r.category.replace("_", " ")}</span>{" "}
            <span className="badge">{r.certainty}</span>
            {r.timing && <> · timing: {r.timing}</>}
            {r.target_date && <> · by {r.target_date}</>}
          </div>
        </div>
        {r.status !== "open" && <span className={`badge ${r.status === "done" ? "ready" : ""}`}>{r.status === "done" ? "Done" : "Not relevant"}</span>}
      </div>
      {r.addressed_by.length > 0 && r.status === "open" && (
        <div className="hint">
          May already be done: {r.addressed_by.map((a) => `${a.title} on ${a.date}`).join("; ")}.{" "}
          <button className="link" onClick={() => act("done", `Matches: ${r.addressed_by[0].title} on ${r.addressed_by[0].date}`)}>Mark as done</button>
        </div>
      )}
      <div className="muted small">
        {r.document_id ? <a href={`/api/documents/${r.document_id}/file`} target="_blank" rel="noreferrer">{r.filename || `D${r.document_id}`}</a> : "advice you added yourself"}
        {r.quote && <span className="quote"> “{r.quote}”</span>}
      </div>
      {r.note && !editing && <div className="small">Note: {r.note}</div>}
      <div className="row wrap" style={{ justifyContent: "flex-start", marginTop: 6 }}>
        {r.status === "open" ? (
          <>
            <button className="small-btn primary" onClick={() => act("done")}>Done</button>
            <button className="small-btn" onClick={() => act("dismissed")} title="No longer relevant or the team decided otherwise">Not relevant</button>
          </>
        ) : (
          <button className="small-btn" onClick={() => act("open")}>Reopen</button>
        )}
        <button className="small-btn" onClick={() => setEditing(!editing)}>{r.note ? "Edit note" : "Add note"}</button>
        <button className="small-btn danger" onClick={() => api.deleteRecommendation(r.id).then(() => api.recommendations().then(onChange))} title="Remove (e.g. read wrongly)">✕</button>
      </div>
      {editing && (
        <div className="inline-form" style={{ marginLeft: 0 }}>
          <input value={note} placeholder="e.g. Completed in Feb, or why it isn’t relevant" onChange={(e) => setNote(e.target.value)} />
          <button className="primary" onClick={() => { void act(r.status, note); setEditing(false); }}>Save note</button>
        </div>
      )}
    </li>
  );
}

export default function RecsTab({ version, onChanged }: { version: number; onChanged: () => void }) {
  const [recs, setRecs] = useState<Rec[] | null>(null);
  const [filter, setFilter] = useState<"open" | "done" | "dismissed" | "all">("open");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ text: "", category: "other", advisor: "", rec_date: "" });
  const [msg, setMsg] = useState("");

  const load = useCallback(() => api.recommendations().then(setRecs), []);
  useEffect(() => {
    void load();
  }, [load, version]);

  const update = (r: Rec[]) => {
    setRecs(r);
    onChanged();
  };

  async function add() {
    setMsg("");
    try {
      update(await api.addRecommendation(form));
      setForm({ text: "", category: "other", advisor: "", rec_date: "" });
      setAdding(false);
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  async function rebuild() {
    const r = await api.rebuildRecommendations();
    setMsg(`Reading ${r.queued} document${r.queued === 1 ? "" : "s"} for advisors’ recommendations in the background — new ones appear here as each finishes (progress is in the Inbox).`);
  }

  if (!recs) return <p className="muted">Loading…</p>;
  const shown = recs.filter((r) => filter === "all" || r.status === filter);
  const count = (s: string) => recs.filter((r) => s === "all" || r.status === s).length;

  return (
    <div>
      <p className="muted">
        What each doctor or report actually advised, quoted from your documents. Mark each one done or not relevant as you go — that keeps the plan accurate.
      </p>
      <div className="row wrap" style={{ justifyContent: "space-between", margin: "10px 0" }}>
        <div className="tabs small-tabs">
          {FILTERS.map((f) => (
            <button key={f.id} className={filter === f.id ? "tab on" : "tab"} onClick={() => setFilter(f.id)}>{f.label} ({count(f.id)})</button>
          ))}
        </div>
        <div className="row">
          <button onClick={rebuild} title="Read every document again for advisors' recommendations">Find in all documents</button>
          <button onClick={() => setAdding(!adding)}>{adding ? "Cancel" : "Add advice I was given"}</button>
        </div>
      </div>
      {msg && <div className="muted small" style={{ marginBottom: 8 }}>{msg}</div>}
      {adding && (
        <div className="card">
          <div className="grid3">
            <label className="field"><span>Who advised it</span><input value={form.advisor} onChange={(e) => setForm({ ...form, advisor: e.target.value })} placeholder="e.g. Dr Bhatt" /></label>
            <label className="field"><span>Date advised</span><input type="date" value={form.rec_date} onChange={(e) => setForm({ ...form, rec_date: e.target.value })} /></label>
            <label className="field"><span>Type</span>
              <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>{CATS.map((c) => <option key={c} value={c}>{c.replace("_", " ")}</option>)}</select>
            </label>
          </div>
          <label className="field wide"><span>What was advised</span><input value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} placeholder="e.g. Repeat PET-CT in three months" /></label>
          <div className="row end"><button className="primary" disabled={!form.text.trim()} onClick={add}>Add</button></div>
        </div>
      )}
      {shown.length === 0 && (
        <p className="muted">
          {recs.length === 0
            ? "No recommendations found yet. They are read from your documents in the background; use “Find in all documents” to scan them again, or add advice you were given in person."
            : "Nothing in this view."}
        </p>
      )}
      <ul className="rec-cards">
        {shown.map((r) => <RecCard key={r.id} r={r} onChange={update} />)}
      </ul>
    </div>
  );
}
