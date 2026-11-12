import { useCallback, useEffect, useState } from "react";
import { api, type CaseDetail, type CaseFieldDetail, type JourneyItem } from "../api";

const CATS = ["diagnosis", "biopsy", "surgery", "chemotherapy", "radiotherapy", "immunotherapy", "imaging", "consultation", "lab", "admission", "other"];
const CAT_ICON: Record<string, string> = {
  diagnosis: "🩺", biopsy: "🔬", surgery: "🏥", chemotherapy: "💊", radiotherapy: "☢️", immunotherapy: "💉",
  imaging: "🖼️", consultation: "🗣️", lab: "🧪", admission: "🛏️", other: "•",
};
const HINTS: Record<string, string> = {
  diagnosis: "As your doctors word it", histology: "e.g. squamous cell carcinoma", stage: "e.g. pT2N1M0 / Stage III",
  hla_type: "Needed later for vaccine work", current_treatment: "As prescribed by your team", current_status: "Latest scan / doctor impression",
};

function Summary({ detail, reload }: { detail: CaseDetail; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const s = detail.summary;
  async function generate() {
    setBusy(true);
    setErr("");
    try {
      await api.generateSummary();
      reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="card">
      <div className="card-head">
        <h3>Summary of the whole journey</h3>
        <button onClick={generate} disabled={busy}>{busy ? "Writing… (about a minute)" : s ? "Refresh summary" : "Write summary"}</button>
      </div>
      {s ? (
        <>
          {s.stale && <div className="alert urgent">The history has changed since this summary was written. Refresh it.</div>}
          <p className="summary-text">{s.text}</p>
          <p className="muted small">AI-written only from the dated entries below, on {new Date(s.generated_at).toLocaleString()}. Check it against them.</p>
        </>
      ) : (
        <p className="muted">No summary yet. It is written from the dated history below: how things began, what was done and when, and where things stand now.</p>
      )}
      {err && <div className="alert urgent">{err}</div>}
    </div>
  );
}

const KEY_CATS = ["diagnosis", "biopsy", "surgery", "chemotherapy", "radiotherapy", "immunotherapy", "imaging"];

function EventRow({ it, reload, undated, sameAs }: { it: JourneyItem; reload: () => void; undated?: boolean; sameAs?: JourneyItem[] }) {
  const [editing, setEditing] = useState(false);
  const [date, setDate] = useState(it.date);
  const [title, setTitle] = useState(it.title);
  const [category, setCategory] = useState(it.category);
  const [err, setErr] = useState("");

  async function save() {
    setErr("");
    try {
      await api.editEvent(it.id!, { date, title, category });
      setEditing(false);
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  if (it.kind === "group") {
    return (
      <li className="j-group">
        <span className="j-date">{it.date}</span>
        <span className="j-icon" aria-hidden>{CAT_ICON[it.category] ?? "•"}</span>
        <details className="grow">
          <summary><strong>{it.title}</strong> <span className="muted small">— {it.detail.length > 80 ? `${it.detail.slice(0, 80)}…` : it.detail}</span></summary>
          <ul className="group-list">
            {it.events!.map((e) => (
              <li key={e.id}>
                {e.title}{" "}
                {e.document_id ? <a className="small" href={`/api/documents/${e.document_id}/file`} target="_blank" rel="noreferrer">{e.filename || "report"}</a> : null}
                <button className="small-btn danger" title="Remove" onClick={() => api.deleteEvent(e.id!).then(reload)}>✕</button>
              </li>
            ))}
          </ul>
        </details>
      </li>
    );
  }

  return (
    <li className={undated ? "j-undated" : ""}>
      <span className="j-date">{it.date || "date unknown"}</span>
      <span className="j-icon" aria-hidden>{CAT_ICON[it.category] ?? "•"}</span>
      <div className="grow">
        {editing ? (
          <div className="inline-form" style={{ margin: 0 }}>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Date" />
            <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Type">
              {CATS.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <input value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Title" />
            <button className="primary" onClick={save} disabled={!title.trim()}>Save</button>
            <button onClick={() => setEditing(false)}>Cancel</button>
            {err && <span className="muted">{err}</span>}
          </div>
        ) : (
          <>
            <strong>{it.title}</strong> <span className="badge">{it.category}</span>
            {it.detail && <div className="muted small">{it.detail}</div>}
            <div className="muted small">
              {it.document_id ? <a href={`/api/documents/${it.document_id}/file`} target="_blank" rel="noreferrer">{it.filename || `D${it.document_id}`}</a> : "added by you"}
              {it.quote && <span className="quote"> “{it.quote}”</span>}
            </div>
            {sameAs && sameAs.length > 0 && (
              <div className="small same-as">
                Probably the same as:{" "}
                {sameAs.map((c) => (
                  <button key={c.id} className="link" title="Remove this undated duplicate; the dated event stays"
                    onClick={() => api.deleteEvent(it.id!).then(reload)}>
                    {c.date} {c.title.length > 40 ? `${c.title.slice(0, 40)}…` : c.title}
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </div>
      {!editing && (
        <>
          <button className="small-btn" title={undated ? "Add the date" : "Edit"} onClick={() => setEditing(true)}>{undated ? "Set date" : "Edit"}</button>
          <button className="small-btn danger" title="Remove from the journey" onClick={() => api.deleteEvent(it.id!).then(reload)}>✕</button>
        </>
      )}
    </li>
  );
}

function Journey({ detail, reload }: { detail: CaseDetail; reload: () => void }) {
  const [open, setOpen] = useState(false);
  const [keyOnly, setKeyOnly] = useState(false);
  const [date, setDate] = useState("");
  const [category, setCategory] = useState("other");
  const [title, setTitle] = useState("");
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const j = detail.journey;

  async function rebuild() {
    if (!confirm("Read every document again for dated events? It runs in the background (about a minute per document). Events are checked against each document, never replace anything, and you can edit or remove any of them.")) return;
    try {
      const r = await api.rebuildJourney();
      setNote(`Reading ${r.queued} document${r.queued === 1 ? "" : "s"} in the background. Events appear here as each finishes; progress is in the Inbox.`);
    } catch (e) {
      setNote((e as Error).message);
    }
  }
  async function add() {
    setErr("");
    try {
      await api.addEvent({ date, category, title });
      setTitle("");
      setDate("");
      setOpen(false);
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  const visible = (it: JourneyItem) => !keyOnly || KEY_CATS.includes(it.category);

  return (
    <div className="card">
      <div className="card-head">
        <h3>Journey <span className="muted small">({j.total} event{j.total === 1 ? "" : "s"})</span></h3>
        <div className="row">
          <label className="check"><input type="checkbox" checked={keyOnly} onChange={(e) => setKeyOnly(e.target.checked)} /> Key events only</label>
          <button onClick={rebuild} title="Read every document again for dated events">Rebuild from all documents</button>
          <button onClick={() => setOpen(!open)}>{open ? "Cancel" : "Add an event"}</button>
        </div>
      </div>
      {note && <div className="muted small" style={{ marginBottom: 8 }}>{note}</div>}
      {j.milestones.length > 0 && (
        <div className="milestones" aria-label="The story at a glance">
          {j.milestones.map((m, i) => (
            <span key={i} className="milestone">
              <span className="j-icon" aria-hidden>{CAT_ICON[m.category] ?? "•"}</span> <b>{m.date}</b> {m.title}
            </span>
          ))}
        </div>
      )}
      {open && (
        <div className="inline-form">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Date" />
          <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Type">
            {CATS.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <input value={title} placeholder="What happened, e.g. Started radiotherapy" onChange={(e) => setTitle(e.target.value)} />
          <button className="primary" onClick={add} disabled={!title.trim()}>Add</button>
          {err && <span className="muted">{err}</span>}
        </div>
      )}
      {j.total === 0 && <p className="muted">No events yet. They are added when you review a report in the Inbox, or you can add them yourself.</p>}

      {j.phases.map((p) => {
        const items = p.items.filter(visible);
        if (items.length === 0) return null;
        return (
          <section key={p.id} className={`phase phase-${p.kind}`}>
            <h4>
              {p.title}
              {p.subtitle && <span className="badge">{p.subtitle}</span>}{" "}
              <span className="muted small">{p.start === p.end ? p.start : `${p.start} → ${p.end}`} · {p.count} event{p.count === 1 ? "" : "s"}</span>
            </h4>
            <ol className="journey">
              {items.map((it) => <EventRow key={`${it.kind}-${it.ids.join("-")}`} it={it} reload={reload} />)}
            </ol>
          </section>
        );
      })}

      {j.undated.length > 0 && (
        <section className="phase phase-undated">
          <h4>Date unknown <span className="muted small">— give these a date so they join the timeline</span></h4>
          <ol className="journey">
            {j.undated.filter(visible).map((it) => (
              <EventRow key={it.id} it={it} reload={reload} undated
                sameAs={j.phases.flatMap((p) => p.items).filter((d) => d.kind === "event" && d.category === it.category).slice(0, 3)} />
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}

function Field({ f, edit, setEdit, reload }: { f: CaseFieldDetail; edit: string | undefined; setEdit: (v: string) => void; reload: () => void }) {
  const [showHistory, setShowHistory] = useState(false);
  const [adding, setAdding] = useState(false);
  const [newDate, setNewDate] = useState("");
  const [newValue, setNewValue] = useState("");
  const [err, setErr] = useState("");
  const cumulative = f.kind === "cumulative";
  const long = cumulative || ["diagnosis", "current_status", "current_treatment", "goals", "allergies", "hla_type"].includes(f.key);
  const value = edit ?? f.value;
  const undated = !cumulative && f.value && !f.as_of;

  async function addEntry() {
    setErr("");
    try {
      await api.addEntry(f.key, newValue, newDate);
      setNewValue("");
      setNewDate("");
      setAdding(false);
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <div className={long ? "field wide" : "field"}>
      <span>{f.label}</span>
      {cumulative ? (
        <div className="readonly">{f.value || <span className="muted">Nothing recorded yet</span>}</div>
      ) : long ? (
        <textarea rows={3} value={value} placeholder={HINTS[f.key] ?? ""} onChange={(e) => setEdit(e.target.value)} />
      ) : (
        <input value={value} placeholder={HINTS[f.key] ?? ""} onChange={(e) => setEdit(e.target.value)} />
      )}
      <div className="field-meta muted small">
        {!cumulative && f.value && (
          <>
            {f.as_of ? `as of ${f.as_of}` : <b className="warn-text">date unknown</b>} ·{" "}
            {f.document_id ? <a href={`/api/documents/${f.document_id}/file`} target="_blank" rel="noreferrer">from a report</a> : "entered by you"}
            {" · "}
          </>
        )}
        <button className="link" onClick={() => setShowHistory(!showHistory)}>History ({f.history.length})</button>
        {cumulative && <> · <button className="link" onClick={() => setAdding(!adding)}>Add entry</button></>}
      </div>
      {undated && <div className="muted small">Set a date in the history so newer reports can correctly supersede this and older ones can’t.</div>}
      {adding && (
        <div className="inline-form">
          <input type="date" value={newDate} onChange={(e) => setNewDate(e.target.value)} aria-label="Date" />
          <input value={newValue} placeholder="New entry" onChange={(e) => setNewValue(e.target.value)} />
          <button className="primary" onClick={addEntry} disabled={!newValue.trim()}>Add</button>
          {err && <span className="muted">{err}</span>}
        </div>
      )}
      {showHistory && (
        <ul className="history">
          {f.history.length === 0 && <li className="muted">No entries yet.</li>}
          {f.history.map((h) => (
            <li key={h.id} className={h.is_current ? "current" : ""}>
              <div className="grow">
                <div>{h.value || <i>(cleared)</i>}</div>
                <div className="muted small">
                  <input
                    type="date"
                    className="mini-date"
                    value={h.as_of}
                    title="When this was true"
                    onChange={(e) => api.setEntryDate(h.id, e.target.value).then(reload)}
                  />{" "}
                  {h.document_id ? <a href={`/api/documents/${h.document_id}/file`} target="_blank" rel="noreferrer">{h.filename || "report"}</a> : "you"}
                  {h.is_current && !cumulative && <span className="badge ready">current</span>}
                  {!h.is_current && <span className="badge">older</span>}
                </div>
              </div>
              <button className="small-btn danger" title="Remove this entry" onClick={() => api.deleteEntry(h.id).then(reload)}>✕</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function CaseFile() {
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [state, setState] = useState("");

  const load = useCallback(() => api.caseDetail().then(setDetail), []);
  useEffect(() => {
    void load();
  }, [load]);

  if (!detail) return <section className="page">Loading…</section>;
  const dirty = Object.keys(edits).length > 0;

  async function save() {
    setState("Saving…");
    try {
      await api.saveCase(edits);
      setEdits({});
      await load();
      setState("Saved");
    } catch (e) {
      setState(`Could not save: ${(e as Error).message}`);
    }
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>Case file</h1>
        <p>
          A running history, not a single record. Every value keeps its date and source; the <b>current</b> case file is the latest dated information, so
          uploading an old report adds to the history without changing what is current.
        </p>
      </header>

      <Summary detail={detail} reload={load} />
      <Journey detail={detail} reload={load} />

      <h2 className="section">Current case file</h2>
      <div className="form-grid">
        {Object.values(detail.fields).map((f) => (
          <Field
            key={f.key}
            f={f}
            edit={edits[f.key]}
            setEdit={(v) => {
              if (v === f.value) {
                const { [f.key]: _drop, ...rest } = edits;
                setEdits(rest);
              } else setEdits({ ...edits, [f.key]: v });
            }}
            reload={load}
          />
        ))}
      </div>
      <div className="savebar">
        <button className="primary" disabled={!dirty} onClick={save}>
          Save changes
        </button>
        <span className="muted">{dirty ? "Unsaved changes — saved as new entries dated today" : state}</span>
      </div>
    </section>
  );
}
