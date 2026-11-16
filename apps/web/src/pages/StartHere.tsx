import { useEffect, useState } from "react";
import { api, type FastTrack } from "../api";

const DONE_KEY = "cc-vax-today-done";

function splitSubject(text: string): { subject: string; body: string } {
  const m = text.match(/^Subject:\s*(.+)\n+([\s\S]*)$/);
  return m ? { subject: m[1], body: m[2] } : { subject: "Urgent request about my father’s cancer care", body: text };
}

export default function StartHere({ onNext }: { onNext: (tab: "options" | "cohort" | "data" | "trials") => void }) {
  const [ft, setFt] = useState<FastTrack | null>(null);
  const [copied, setCopied] = useState("");
  const [open, setOpen] = useState("");
  const [done, setDone] = useState<string[]>(() => JSON.parse(localStorage.getItem(DONE_KEY) ?? "[]"));
  useEffect(() => { void api.fasttrack().then(setFt).catch(() => undefined); }, []);
  if (!ft) return <p className="muted">Loading…</p>;

  const draft = (id: string) => ft.drafts.find((d) => d.id === id);
  const copy = (id: string, text: string) => { void navigator.clipboard.writeText(text); setCopied(id); setTimeout(() => setCopied(""), 2000); };
  const toggle = (id: string) => {
    const next = done.includes(id) ? done.filter((x) => x !== id) : [...done, id];
    setDone(next);
    localStorage.setItem(DONE_KEY, JSON.stringify(next));
  };

  return (
    <div>
      <div className="card">
        <div className="card-head"><h3>What this page can and cannot do</h3></div>
        <p className="small" style={{ marginBottom: 6 }}>
          <b>It cannot give or make a vaccine.</b> A personalised vaccine is made for one person by a specialist team inside a clinical trial, and it begins with tests on his tumour and blood. Nobody can shorten that to a day, and anyone who offers one outside a trial or hospital should not be trusted.
        </p>
        <p className="small" style={{ marginBottom: 0 }}>
          <b>What it does:</b> it makes the first steps as fast as possible. The three things below are ready to send, and each one can start the clock on tests, trials and a tumour-board review today.
        </p>
      </div>

      {ft.encouraging.length > 0 && (
        <div className="card" style={{ borderLeft: "4px solid #2e8b57" }}>
          <div className="card-head"><h3>What is encouraging in his records</h3></div>
          <ul className="small">{ft.encouraging.map((e) => <li key={e.text}>{e.text} <span className="muted">({e.source})</span></li>)}</ul>
          <p className="small muted" style={{ marginBottom: 0 }}>This is real progress. It does not replace the open questions: a lesion that is smaller but still active, and the clot in the neck vein. Those are what the three steps below are for.</p>
        </div>
      )}

      <div className="card">
        <div className="card-head"><h3>Do these three things today</h3><span className="muted small">{done.length} of {ft.today.length} done</span></div>
        {ft.today.map((t, i) => {
          const d = draft(t.id);
          const { subject, body } = d ? splitSubject(d.text) : { subject: "", body: "" };
          return (
            <div key={t.id} className="today-step" style={{ borderTop: i ? "1px solid var(--line)" : "none", padding: "10px 0" }}>
              <label className="row" style={{ justifyContent: "flex-start", gap: 10, alignItems: "flex-start" }}>
                <input type="checkbox" checked={done.includes(t.id)} onChange={() => toggle(t.id)} style={{ marginTop: 4 }} />
                <span><b>{i + 1}. {t.title}</b> <span className="muted small">· about {t.minutes} min</span><br /><span className="small">{t.why}</span></span>
              </label>
              {d && (
                <div style={{ marginLeft: 28, marginTop: 6 }}>
                  <div className="row wrap" style={{ justifyContent: "flex-start", gap: 8 }}>
                    <button className="primary" onClick={() => copy(t.id, d.text)}>{copied === t.id ? "Copied ✓" : "Copy the message"}</button>
                    <a className="btn-link" href={`mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`}>Open in email</a>
                    <a className="btn-link" href={`https://wa.me/?text=${encodeURIComponent(d.text)}`} target="_blank" rel="noreferrer">Send by WhatsApp</a>
                    <button className="link" onClick={() => setOpen(open === t.id ? "" : t.id)}>{open === t.id ? "Hide" : "Read it first"}</button>
                  </div>
                  <div className="muted small">To: {d.to}</div>
                  {open === t.id && <pre className="draft">{d.text}</pre>}
                </div>
              )}
            </div>
          );
        })}
        <p className="muted small" style={{ marginBottom: 0 }}>The messages are written from his records only. Read them once and correct anything that is wrong before sending. Email and WhatsApp open on your side; nothing is sent from this app.</p>
      </div>

      <div className="card">
        <div className="card-head"><h3>What happens next</h3></div>
        <ol className="small" style={{ paddingLeft: 20, marginBottom: 6 }}>
          <li><b>This week:</b> the tumour board decides about the neck clot and the next treatment. A trial centre tells you whether he can be screened and which tests it needs.</li>
          <li><b>When sequencing and HLA results arrive:</b> <button className="link" onClick={() => onNext("data")}>paste them in Data</button>. This tool then ranks which mutations the immune system could recognise, in minutes, and produces a summary for the trial team.</li>
          <li><b>Meanwhile:</b> <button className="link" onClick={() => onNext("trials")}>check a specific trial against his records</button> (for example NCT06868433), <button className="link" onClick={() => onNext("options")}>read the ten treatment options</button> so you can ask informed questions, and <button className="link" onClick={() => onNext("cohort")}>see what the simulation says</button> about which tests matter most.</li>
        </ol>
        <p className="small" style={{ marginBottom: 0 }}><b>Do not wait on any of this for the neck-vein problem.</b> New breathlessness, chest pain, coughing blood, fainting or sudden neck swelling means emergency care now.</p>
      </div>

      <details className="card">
        <summary><b>More detail</b> (what the reports show, the longer plan, cautions)</summary>
        <ul className="small">{ft.findings.map((f) => <li key={f.key}>{f.text} <span className="muted">({f.filename})</span></li>)}</ul>
        <p className="small">
          The Core Diagnostics file in this app is the <b>PD-L1 test only</b>, and it lists the DNA/RNA panel as “pending”. If you have a separate sequencing report, upload it so it is on file. A small gene panel with no driver variant does <b>not</b> mean the tumour has no mutations a vaccine could use: that needs whole-exome sequencing of tumour and blood, plus RNA and HLA typing. Ask about the uncertain PMS2 result and microsatellite/mismatch-repair status, which can matter for immunotherapy.
        </p>
        <ol className="small" style={{ paddingLeft: 20 }}>{ft.steps.map((s) => <li key={s.title}><b>{s.when}: {s.title}.</b> {s.detail}</li>)}</ol>
        <ul className="small">{ft.cautions.map((c) => <li key={c}>{c}</li>)}</ul>
      </details>
    </div>
  );
}
