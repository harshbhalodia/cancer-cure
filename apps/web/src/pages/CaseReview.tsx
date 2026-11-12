import { useEffect, useMemo, useState } from "react";
import { api, type CaseDetail, type CaseProposal } from "../api";

export interface CaseReviewData {
  documentId: number;
  filename: string;
  proposal: CaseProposal;
}

const CAT_LABEL: Record<string, string> = {
  diagnosis: "Diagnosis", biopsy: "Biopsy", surgery: "Surgery", chemotherapy: "Chemotherapy", radiotherapy: "Radiotherapy",
  immunotherapy: "Immunotherapy", imaging: "Imaging", consultation: "Consultation", lab: "Lab", admission: "Admission", other: "Other",
};

/** Review what a document would add to the case history. Nothing is overwritten: whether a value becomes
 *  the current one depends on its date, so an old report can only ever go to history. */
export default function CaseReview({ review, onClose, onApplied }: { review: CaseReviewData; onClose: () => void; onApplied: () => void }) {
  const { proposal } = review;
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [asOf, setAsOf] = useState(proposal.as_of);
  const [values, setValues] = useState({ ...proposal.fields });
  const keys = Object.keys(proposal.fields).filter((k) => proposal.fields[k]);
  const [picked, setPicked] = useState<Record<string, boolean>>(() => Object.fromEntries(keys.map((k) => [k, true])));
  const [evPicked, setEvPicked] = useState<boolean[]>(() => proposal.events.map(() => true));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.caseDetail().then(setDetail).catch((e) => setErr((e as Error).message));
  }, []);

  const outcome = useMemo(() => {
    const out: Record<string, { text: string; current: boolean }> = {};
    for (const k of keys) {
      const f = detail?.fields[k];
      if (!f) continue;
      if (f.kind === "cumulative") out[k] = { text: "adds to the running list (kept in date order)", current: true };
      else if (!f.value) out[k] = { text: "fills this empty field", current: true };
      else if (!asOf) out[k] = { text: "history only — this report has no date, so it can’t replace the current value", current: false };
      else if (f.as_of && asOf < f.as_of) out[k] = { text: `history only — older than the current value (${f.as_of})`, current: false };
      else out[k] = { text: `becomes the current value (replaces the one ${f.as_of ? `from ${f.as_of}` : "with no date"})`, current: true };
    }
    return out;
  }, [detail, keys, asOf]);

  async function apply() {
    setSaving(true);
    setErr("");
    try {
      const fields = Object.fromEntries(keys.filter((k) => picked[k]).map((k) => [k, values[k]]));
      const events = proposal.events.filter((_, i) => evPicked[i]);
      await api.applyProposal(review.documentId, { as_of: asOf, fields, events });
      onApplied();
    } catch (e) {
      setErr((e as Error).message);
      setSaving(false);
    }
  }

  const count = keys.filter((k) => picked[k]).length + evPicked.filter(Boolean).length;

  return (
    <div className="modal-backdrop">
      <div className="modal wide">
        <h2>Add to case history</h2>
        <p className="muted">
          Suggested by the AI from {review.filename}. Nothing is overwritten: values are stored with this report’s date, and the <b>current</b> case file is always the
          latest dated information. An older report goes to history without disturbing what is current.
        </p>
        <label className="field" style={{ maxWidth: 260 }}>
          <span>Report date (the date these facts were true)</span>
          <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        </label>
        {!asOf && <div className="alert urgent">This report has no date. Add one so it is placed correctly in the history.</div>}

        {keys.length > 0 && <h3>Details</h3>}
        {keys.map((k) => {
          const f = detail?.fields[k];
          const o = outcome[k];
          return (
            <div key={k} className="review-row">
              <label>
                <input type="checkbox" checked={!!picked[k]} onChange={(e) => setPicked({ ...picked, [k]: e.target.checked })} /> <strong>{f?.label ?? k}</strong>{" "}
                {o && <span className={`badge ${o.current ? "ready" : "partial"}`}>{o.current ? "current" : "history"}</span>}
              </label>
              {o && <div className="muted small">{o.text}</div>}
              {f && f.kind !== "cumulative" && f.value && <div className="muted small">Now: {f.value.slice(0, 200)}</div>}
              <textarea rows={2} value={values[k]} onChange={(e) => setValues({ ...values, [k]: e.target.value })} />
            </div>
          );
        })}

        {proposal.events.length > 0 && <h3>Journey events</h3>}
        {proposal.events.map((e, i) => (
          <div key={i} className="item">
            <label className="check">
              <input type="checkbox" checked={evPicked[i]} onChange={(ev) => setEvPicked(evPicked.map((v, k) => (k === i ? ev.target.checked : v)))} />
              <b>{e.date || "date unknown"}</b> <span className="badge">{CAT_LABEL[e.category] ?? e.category}</span> {e.title}
            </label>
            {e.detail && <div className="muted small">{e.detail}</div>}
            <div className="quote">“{e.quote}”</div>
          </div>
        ))}
        {keys.length === 0 && proposal.events.length === 0 && <p>Nothing new to add from this document.</p>}

        {proposal.rejected.length > 0 && (
          <details>
            <summary>{proposal.rejected.length} suggestion(s) were adjusted or discarded because they could not be verified</summary>
            <ul className="muted small">{proposal.rejected.map((r, i) => <li key={i}><b>{r.item}</b>: {r.reason}</li>)}</ul>
          </details>
        )}
        {err && <div className="alert urgent">Could not save: {err}</div>}
        <div className="row end sticky">
          <button onClick={onClose}>Cancel</button>
          <button className="primary" onClick={apply} disabled={count === 0 || saving}>
            {saving ? "Saving…" : `Add ${count} item${count === 1 ? "" : "s"} to history`}
          </button>
        </div>
      </div>
    </div>
  );
}
