import { useCallback, useEffect, useState } from "react";
import { api, type TrialAssessment, type TrialBrief, type TrialHit } from "../api";

const LABEL: Record<string, string> = { ok: "Records support", check: "Check", missing: "Not on file", routine: "Routine" };
const COLOR: Record<string, string> = { ok: "#2e8b57", check: "#c9a227", missing: "#c0392b", routine: "#7a8794" };

function Badge({ s }: { s: string }) {
  return <span className="badge" style={{ background: `color-mix(in srgb, ${COLOR[s] ?? "#888"} 18%, white)`, color: COLOR[s], borderColor: COLOR[s] }}>{LABEL[s] ?? s}</span>;
}

function Select({ label, value, options, onChange }: { label: string; value: string; options: [string, string][]; onChange: (v: string) => void }) {
  return (
    <label className="small" style={{ display: "block", marginBottom: 8 }}>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} style={{ marginLeft: 8 }}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

export default function TrialsTab() {
  const [list, setList] = useState<TrialBrief[]>([]);
  const [t, setT] = useState<TrialAssessment | null>(null);
  const [nct, setNct] = useState("");
  const [term, setTerm] = useState("vaccine OR neoantigen");
  const [country, setCountry] = useState("");
  const [hits, setHits] = useState<TrialHit[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [copied, setCopied] = useState("");
  const [lines, setLines] = useState("");

  const load = useCallback(() => api.trials().then(setList).catch(() => undefined), []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (!t && list.length) void api.trial(list[0].id).then((a) => { setT(a); setLines(a.profile.treatment_lines ?? ""); }); }, [list, t]);

  const run = async (fn: () => Promise<TrialAssessment | TrialHit[] | void>) => {
    setErr(""); setBusy(true);
    try { return await fn(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const open = async (id: number) => { const a = await api.trial(id); setT(a); setLines(a.profile.treatment_lines ?? ""); };
  const add = async (id: string) => {
    const a = (await run(() => api.trialAdd(id))) as TrialAssessment | undefined;
    if (a) { setT(a); setLines(a.profile.treatment_lines ?? ""); setNct(""); await load(); }
  };
  const save = async (patch: Record<string, string>) => { if (t) { const a = (await run(() => api.trialProfile(t.id, patch))) as TrialAssessment | undefined; if (a) setT(a); } };
  const copy = (id: string, text: string) => { void navigator.clipboard.writeText(text); setCopied(id); setTimeout(() => setCopied(""), 1800); };
  const email = t?.central.find((c) => c.email)?.email ?? t?.sites.flatMap((s) => s.contacts).find((c) => c.email)?.email ?? "";

  return (
    <div>
      <div className="card">
        <div className="card-head"><h3>Check a clinical trial against his records</h3></div>
        <p className="small">Enter a trial number (for example NCT06868433). The tool reads the official ClinicalTrials.gov text, compares every eligibility line with his documents, and shows what is supported, what needs checking and what is missing. It then drafts the questions to send to the study team. <b>Only the study team can decide eligibility</b>, from the current protocol. Only the trial number leaves this computer.</p>
        <div className="row wrap" style={{ justifyContent: "flex-start", gap: 8 }}>
          <input value={nct} onChange={(e) => setNct(e.target.value)} placeholder="NCT06868433" aria-label="Trial number" style={{ width: 170 }} />
          <button className="primary" disabled={busy || !nct.trim()} onClick={() => add(nct)}>{busy ? "Working…" : "Check this trial"}</button>
        </div>
        <details style={{ marginTop: 8 }}>
          <summary className="small">Search for other recruiting trials (head and neck squamous cell carcinoma)</summary>
          <div className="row wrap" style={{ justifyContent: "flex-start", gap: 8, marginTop: 6 }}>
            <input value={term} onChange={(e) => setTerm(e.target.value)} aria-label="Treatment words" style={{ width: 220 }} />
            <input value={country} onChange={(e) => setCountry(e.target.value)} placeholder="Country (optional, e.g. India)" aria-label="Country" style={{ width: 200 }} />
            <button disabled={busy} onClick={async () => { const r = (await run(() => api.trialSearch(term, country))) as TrialHit[] | undefined; if (r) setHits(r); }}>Search</button>
          </div>
          {hits && (hits.length === 0 ? <p className="small muted">No recruiting trials matched.</p> : (
            <ul className="small">{hits.map((h) => (
              <li key={h.nct_id}><b>{h.nct_id}</b> · {h.phase || "phase n/a"} · {h.countries.join(", ") || "sites n/a"}<br />{h.title} <button className="link" onClick={() => add(h.nct_id)}>Check fit</button></li>
            ))}</ul>
          ))}
        </details>
        {err && <div className="alert urgent">{err}</div>}
        {list.length > 0 && (
          <div className="row wrap" style={{ justifyContent: "flex-start", gap: 6, marginTop: 8 }}>
            {list.map((x) => <button key={x.id} className={t?.id === x.id ? "tab on" : "tab"} onClick={() => open(x.id)}>{x.nct_id}</button>)}
          </div>
        )}
      </div>

      {t && (
        <>
          <div className="card">
            <div className="card-head"><h3>{t.nct_id}: {t.title}</h3><span className="badge">{t.status.replace(/_/g, " ").toLowerCase()}</span></div>
            <div className="small muted">{t.phase.replace("PHASE", "Phase ")} · registry verified {t.verified || "n/a"} · last updated {t.last_update || "n/a"} · fetched {t.fetched_at.slice(0, 10)} · <a href={t.url} target="_blank" rel="noreferrer">official record</a></div>
            <div className="row wrap" style={{ justifyContent: "flex-start", gap: 8, marginTop: 6 }}>
              <button disabled={busy} onClick={async () => { const a = (await run(() => api.trialRefresh(t.id))) as TrialAssessment | undefined; if (a) setT(a); }}>Re-check the registry for changes</button>
              <button className="link" onClick={async () => { if (confirm("Remove this trial from the list?")) { await api.trialDelete(t.id); setT(null); await load(); } }}>Remove</button>
            </div>
            <p className="small" style={{ marginTop: 10, marginBottom: 0 }}>
              Against his records, of {t.criteria.length} eligibility lines: <b style={{ color: COLOR.ok }}>{t.counts.ok} supported</b> · <b style={{ color: COLOR.check }}>{t.counts.check} to check</b> · <b style={{ color: COLOR.missing }}>{t.counts.missing} not on file</b> · {t.counts.routine} routine checks. This is a preparation list, not an eligibility decision.
            </p>
          </div>

          {t.notes.length > 0 && (
            <div className="card vax-warn">
              <b>Things to know before you contact them</b>
              <ul className="small" style={{ marginBottom: 0 }}>{t.notes.map((n) => <li key={n}>{n}</li>)}</ul>
            </div>
          )}

          <div className="card">
            <div className="card-head"><h3>The questions that decide it</h3></div>
            {t.key_issues.map((k) => (
              <div key={k.key} style={{ padding: "8px 0", borderTop: "1px solid var(--line)" }}>
                <Badge s={k.status} /> <span className="small">{k.text}</span>
                {k.ask && <div className="small muted">Ask: {k.ask}</div>}
              </div>
            ))}
          </div>

          <div className="card">
            <div className="card-head"><h3>Tell the tool what you know</h3></div>
            <p className="muted small">Only you and his doctors can answer these. They update the checks above. Anything you type here is labelled “reported by you” until a document backs it up.</p>
            <Select label="ECOG performance status (his oncologist assigns it)" value={t.profile.ecog ?? ""} onChange={(v) => save({ ecog: v })}
              options={[["", "Not known"], ["0", "0: fully active"], ["1", "1: light work only"], ["2", "2: up and about over half the day"], ["3", "3: mostly in bed or chair"], ["4", "4: bed-bound"]]} />
            <Select label="Has the surgeon said the current disease can be removed to cure it?" value={t.profile.surgeon_opinion ?? ""} onChange={(v) => save({ surgeon_opinion: v })}
              options={[["", "Not asked yet"], ["yes", "Yes"], ["no", "No"]]} />
            <Select label="Blood thinner for the neck-vein clot" value={t.profile.anticoagulant ?? ""} onChange={(v) => save({ anticoagulant: v })}
              options={[["", "Not known"], ["none", "None"], ["lmwh", "Low-molecular-weight heparin injections"], ["other", "Another blood thinner (tablets)"]]} />
            <Select label="Autoimmune disease, or steroids / immunosuppressants in the last 14 days" value={t.profile.autoimmune_or_steroids ?? ""} onChange={(v) => save({ autoimmune_or_steroids: v })}
              options={[["", "Not known"], ["no", "No"], ["yes", "Yes"]]} />
            <label className="small" style={{ display: "block" }}>Treatments he has had for the recurrence: drug names, start and stop dates, and why each stopped (for example “nivolumab with an oral chemotherapy tablet, name …, since …”)
              <textarea value={lines} onChange={(e) => setLines(e.target.value)} rows={3} style={{ width: "100%", marginTop: 4 }} />
            </label>
            <button style={{ marginTop: 6 }} onClick={() => save({ treatment_lines: lines })}>Save</button>
            <p className="muted small" style={{ marginBottom: 0 }}>The most useful document to add: the prescription or a photo of the tablet packaging, and the oncologist’s treatment summary. Upload them in Documents.</p>
          </div>

          <div className="card">
            <div className="card-head"><h3>Message to the study team</h3></div>
            <p className="muted small">Written from his records, plus the questions above. Read it and correct anything that is wrong before sending.</p>
            <pre className="draft">{t.letter}</pre>
            <div className="row wrap" style={{ justifyContent: "flex-start", gap: 8 }}>
              <button className="primary" onClick={() => copy("letter", t.letter)}>{copied === "letter" ? "Copied ✓" : "Copy the message"}</button>
              <a className="btn-link" href={`mailto:${email}?subject=${encodeURIComponent(`Enquiry about ${t.nct_id}: eligibility screening`)}&body=${encodeURIComponent(t.letter)}`}>Open in email</a>
              <a className="btn-link" href={`https://wa.me/?text=${encodeURIComponent(t.letter)}`} target="_blank" rel="noreferrer">Send by WhatsApp</a>
            </div>
            <div className="small" style={{ marginTop: 10 }}><b>Contacts listed in the registry (confirm before relying on them):</b>
              <ul>
                {t.central.map((c) => <li key={c.email + c.phone}>{c.name}{c.role ? ` (${c.role.toLowerCase()})` : ""}: {c.phone} {c.email}</li>)}
                {t.sites.filter((s) => s.status === "RECRUITING").map((s) => (
                  <li key={s.facility}><b>{s.facility}</b>, {s.city}, {s.country}: {s.contacts.map((c) => `${c.name} ${c.phone}`.trim()).join("; ")}</li>
                ))}
              </ul>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h3>Enquiry log</h3></div>
            <div className="row wrap" style={{ justifyContent: "flex-start", gap: 8 }}>
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Emailed Dr Shin; they replied that nivolumab is acceptable" style={{ flex: 1, minWidth: 260 }} />
              <button disabled={!note.trim()} onClick={async () => { const a = (await run(() => api.trialLog(t.id, note))) as TrialAssessment | undefined; if (a) { setT(a); setNote(""); } }}>Add</button>
            </div>
            <ul className="small">{[...t.log].reverse().map((l, i) => <li key={i}><span className="muted">{l.when}</span> {l.text}</li>)}</ul>
          </div>

          <details className="card">
            <summary><b>Every eligibility line, with what the records show</b></summary>
            {t.criteria.map((c) => (
              <div key={c.n} style={{ padding: "8px 0", borderTop: "1px solid var(--line)" }}>
                <Badge s={c.status} /> <span className="muted small">{c.kind}</span>
                <div className="small">{c.text}</div>
                {c.findings.map((f, i) => <div key={i} className="small muted" style={{ marginLeft: 12 }}>• {f.text}</div>)}
              </div>
            ))}
          </details>
        </>
      )}
    </div>
  );
}
