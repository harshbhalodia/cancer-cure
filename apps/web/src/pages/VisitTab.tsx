import { useCallback, useEffect, useState } from "react";
import { api, type Consult, type ConsultSection } from "../api";

function QuestionRow({ q, state, onSave }: { q: { key: string; text: string }; state?: { asked: boolean; answer: string }; onSave: (key: string, body: { asked?: boolean; answer?: string }) => void }) {
  const [open, setOpen] = useState(!!state?.answer);
  const [answer, setAnswer] = useState(state?.answer ?? "");
  return (
    <li className={state?.asked ? "cq asked" : "cq"}>
      <label className="cq-main">
        <input type="checkbox" checked={!!state?.asked} onChange={(e) => onSave(q.key, { asked: e.target.checked })} />
        <span>{q.text}</span>
      </label>
      <button className="link small" onClick={() => setOpen(!open)}>{open ? "hide answer" : state?.answer ? "see answer" : "record answer"}</button>
      {open && (
        <textarea rows={2} value={answer} placeholder="What the doctor said…" onChange={(e) => setAnswer(e.target.value)}
          onBlur={() => answer !== (state?.answer ?? "") && onSave(q.key, { answer })} />
      )}
    </li>
  );
}

function SectionCard({ s, n, answers, onSave }: { s: ConsultSection; n: number; answers: Consult["answers"]; onSave: (key: string, body: { asked?: boolean; answer?: string }) => void }) {
  const done = s.questions.filter((q) => answers[q.key]?.asked).length;
  return (
    <div className={`card csec ${s.priority}`}>
      <div className="card-head">
        <h3><span className="rank">{n}</span> {s.title}</h3>
        <span className="muted small">{done}/{s.questions.length} asked</span>
      </div>
      {s.context.map((c, i) => <div key={i} className="small facts">{c}</div>)}
      <ul className="plain cqs">{s.questions.map((q) => <QuestionRow key={q.key} q={q} state={answers[q.key]} onSave={onSave} />)}</ul>
    </div>
  );
}

export default function VisitTab() {
  const [data, setData] = useState<Consult | null>(null);
  const [advice, setAdvice] = useState("");
  const [msg, setMsg] = useState("");
  const [copied, setCopied] = useState(false);
  const load = useCallback(() => api.consult().then((d) => { setData(d); setAdvice((a) => a || d.advice); }), []);
  useEffect(() => { void load(); }, [load]);

  const save = async (key: string, body: { asked?: boolean; answer?: string }) => {
    await api.saveConsultItem(key, body);
    await load();
  };
  const finish = async () => {
    setMsg("");
    try {
      await api.saveConsultAdvice(advice);
      const r = await api.finishConsult();
      setMsg(`Saved to the journey${r.recommendations ? ` and ${r.recommendations} piece${r.recommendations === 1 ? "" : "s"} of advice added to Advisors’ recommendations` : ""}.`);
      await load();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  if (!data) return <p className="muted">Loading…</p>;
  const total = data.sections.reduce((n, s) => n + s.questions.length, 0);
  const asked = data.sections.reduce((n, s) => n + s.questions.filter((q) => data.answers[q.key]?.asked).length, 0);
  if (data.sections.length === 0) {
    return <div className="empty-card" style={{ marginTop: 14 }}><h3 style={{ marginTop: 0 }}>No checklist yet</h3><p className="muted">Confirm a scan report’s data (Inbox or Documents) and the checklist for the next doctor visit is built from it.</p></div>;
  }
  return (
    <div>
      <p className="muted" style={{ marginTop: 10 }}>
        Take this to the visit. Tick each question as you ask it and write down what the doctor says. These are questions for the treating team, not advice.
      </p>
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <div className="today-meter" style={{ margin: 0 }}>
          <div className="meter"><div style={{ width: `${total ? (asked / total) * 100 : 0}%` }} /></div>
          <span><strong>{asked}</strong> of {total} asked</span>
        </div>
        <button onClick={() => api.consultText().then((r) => { void navigator.clipboard?.writeText(r.text); setCopied(true); setTimeout(() => setCopied(false), 2500); })}>{copied ? "Copied" : "Copy checklist as text"}</button>
      </div>
      <div className="go-now" style={{ margin: "10px 0" }}>🚨 {data.emergency}</div>

      {data.sections.map((s, i) => <SectionCard key={s.id} s={s} n={i + 1} answers={data.answers} onSave={save} />)}

      <div className="card">
        <div className="card-head"><h3>🗣️ Tell the doctor</h3></div>
        <ul className="plain">
          {data.mention.map((m) => (
            <li key={m.id} className="mention"><strong>{m.text}</strong>{m.note && <div className="muted small">{m.note}</div>}</li>
          ))}
        </ul>
      </div>

      {data.leave_with.length > 0 && (
        <div className="card leave">
          <div className="card-head"><h3>🎯 Don’t leave without clarity on</h3></div>
          <ol style={{ margin: 0, paddingLeft: 20 }}>{data.leave_with.map((t, i) => <li key={i}>{t}</li>)}</ol>
        </div>
      )}

      <div className="card">
        <div className="card-head"><h3>📝 What the doctor advised</h3><span className="muted small">one item per line</span></div>
        <textarea rows={4} value={advice} placeholder={"e.g.\nColour Doppler of the neck vein tomorrow\nReview in 2 weeks with reports"} onChange={(e) => setAdvice(e.target.value)} />
        <div className="row wrap" style={{ justifyContent: "flex-start", marginTop: 8 }}>
          <button className="primary" onClick={finish}>{data.status === "saved" ? "Update the saved visit" : "Save this visit"}</button>
          <span className="muted small">Adds a dated consultation to the journey and each advice line to Advisors’ recommendations.</span>
        </div>
        {msg && <div className="hint" style={{ color: "var(--brand)" }}>{msg}</div>}
      </div>

      {data.history.length > 0 && (
        <p className="muted small">Saved visits: {data.history.map((h) => `${h.day} (${h.answered} answer${h.answered === 1 ? "" : "s"})`).join(" · ")}</p>
      )}
    </div>
  );
}
