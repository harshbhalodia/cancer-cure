import { useEffect, useState } from "react";
import { api, type Doc, type ScanFinding, type ScanLesion, type ScanProposal } from "../api";

const num = (v: string): number | null => (v.trim() === "" || Number.isNaN(Number(v)) ? null : Number(v));

export default function ScanReview({ doc, proposal, onClose, onSaved }: { doc: Pick<Doc, "id" | "filename">; proposal: ScanProposal; onClose: () => void; onSaved: () => void }) {
  const [study, setStudy] = useState(proposal.study);
  const [lesions, setLesions] = useState<ScanLesion[]>(proposal.lesions);
  const [findings, setFindings] = useState<ScanFinding[]>(proposal.findings);
  const [existing, setExisting] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const rr = proposal.reported_response;

  useEffect(() => {
    api.progress().then((p) => setExisting(p.series.map((s) => s.label))).catch(() => undefined);
  }, []);

  const setLesion = (i: number, patch: Partial<ScanLesion>) => setLesions(lesions.map((l, k) => (k === i ? { ...l, ...patch } : l)));
  const setFinding = (i: number, patch: Partial<ScanFinding>) => setFindings(findings.map((f, k) => (k === i ? { ...f, ...patch } : f)));

  async function save() {
    setSaving(true);
    setErr("");
    try {
      await api.saveScan(doc.id, {
        modality: study.modality, date: study.date, comparator_modality: study.comparator_modality, comparator_date: study.comparator_date,
        lesions, findings,
        reported_label: rr.label, reported_criteria: rr.criteria, reported_sum_prior: rr.sum_prior_mm, reported_sum_now: rr.sum_now_mm,
        reported_pct: rr.percent_change, reported_quote: rr.quote,
      });
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
      setSaving(false);
    }
  }

  const noPriorDate = lesions.some((l) => l.size_mm_prior != null) && !study.comparator_date;

  return (
    <div className="modal-backdrop">
      <div className="modal wide">
        <h2>Check the scan data</h2>
        <p className="muted">
          Read from {doc.filename}. Each line below was matched against the report text; compare with the quoted source and fix anything that looks wrong. Nothing is saved until you confirm.
        </p>

        <div className="grid3">
          <label className="field"><span>Scan type</span><input value={study.modality} onChange={(e) => setStudy({ ...study, modality: e.target.value })} /></label>
          <label className="field"><span>Scan date</span><input type="date" value={study.date} onChange={(e) => setStudy({ ...study, date: e.target.value })} /></label>
          <label className="field"><span>Compared with (date)</span><input type="date" value={study.comparator_date} onChange={(e) => setStudy({ ...study, comparator_date: e.target.value })} /></label>
        </div>
        {noPriorDate && <div className="alert urgent">Earlier sizes are listed but the comparison date is missing — add it so they appear on the chart.</div>}

        <h3>Lesion measurements (mm)</h3>
        <datalist id="lesion-names">{existing.map((n) => <option key={n} value={n} />)}</datalist>
        {lesions.length === 0 && <p className="muted">No verified measurements found.</p>}
        {lesions.map((l, i) => (
          <div key={i} className="item">
            <div className="grid5">
              <label className="field"><span>Lesion</span><input list="lesion-names" value={l.name} onChange={(e) => setLesion(i, { name: e.target.value })} /></label>
              <label className="field"><span>Earlier</span><input inputMode="decimal" value={l.size_mm_prior ?? ""} onChange={(e) => setLesion(i, { size_mm_prior: num(e.target.value) })} /></label>
              <label className="field"><span>Now</span><input inputMode="decimal" value={l.size_mm_now ?? ""} onChange={(e) => setLesion(i, { size_mm_now: num(e.target.value) })} /></label>
              <label className="field"><span>SUVmax</span><input inputMode="decimal" value={l.suv_max_now ?? ""} onChange={(e) => setLesion(i, { suv_max_now: num(e.target.value) })} /></label>
              <button className="danger small-btn" onClick={() => setLesions(lesions.filter((_, k) => k !== i))}>Remove</button>
            </div>
            <label className="check"><input type="checkbox" checked={l.is_target} onChange={(e) => setLesion(i, { is_target: e.target.checked })} /> Track as a target lesion</label>
            <div className="quote">“{l.quote}”</div>
          </div>
        ))}

        <h3>Findings</h3>
        {findings.length === 0 && <p className="muted">No verified findings.</p>}
        {findings.map((f, i) => (
          <div key={i} className="item">
            <div className="grid-find">
              <input value={f.text} onChange={(e) => setFinding(i, { text: e.target.value })} aria-label="Finding" />
              <select value={f.certainty} onChange={(e) => setFinding(i, { certainty: e.target.value })} aria-label="Certainty">
                <option value="definite">Stated plainly</option>
                <option value="possible">Possible / appears / could be</option>
                <option value="absent">Not seen</option>
              </select>
              <select value={f.category} onChange={(e) => setFinding(i, { category: e.target.value })} aria-label="Type">
                <option value="primary">Main tumour</option>
                <option value="nodal">Lymph node</option>
                <option value="distant">Distant spread</option>
                <option value="vascular">Blood vessel</option>
                <option value="other">Other</option>
              </select>
              <button className="danger small-btn" onClick={() => setFindings(findings.filter((_, k) => k !== i))}>Remove</button>
            </div>
            <div className="quote">“{f.quote}”</div>
          </div>
        ))}

        {rr.label && (
          <p>
            <strong>Report’s own conclusion:</strong> {rr.label}
            {rr.percent_change != null && ` (${rr.percent_change}% change, ${rr.sum_prior_mm} → ${rr.sum_now_mm} mm)`}
            <span className="quote">“{rr.quote}”</span>
          </p>
        )}

        {proposal.rejected.length > 0 && (
          <details>
            <summary>{proposal.rejected.length} item(s) the AI proposed were discarded because they could not be verified</summary>
            <ul className="muted small">{proposal.rejected.map((r, i) => <li key={i}><b>{r.item}</b>: {r.reason}</li>)}</ul>
          </details>
        )}
        {err && <div className="alert urgent">Could not save: {err}</div>}
        <div className="row end sticky">
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={saving || (lesions.length === 0 && findings.length === 0 && !rr.label)} onClick={save}>
            {saving ? "Saving…" : "Confirm and save"}
          </button>
        </div>
      </div>
    </div>
  );
}
