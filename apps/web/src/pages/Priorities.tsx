import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api, type Priorities, type PriorityQuestion, type PriorityTrack } from "../api";

export function usePriorities(version: number) {
  const [data, setData] = useState<Priorities | null>(null);
  const load = useCallback(() => api.priorities().then(setData).catch(() => setData(null)), []);
  useEffect(() => { void load(); }, [load, version]);
  return { data, reload: load };
}

function TrackCard({ t, n }: { t: PriorityTrack; n: number }) {
  return (
    <li className={`track ${t.priority}`}>
      <span className="rank">{n}</span>
      <div className="grow">
        <div><span className={`badge ${t.priority === "urgent" ? "attention" : "partial"}`}>{t.label}</span> <strong>{t.title}</strong></div>
        <div className="small">{t.why}</div>
        {t.facts.map((f, i) => <div key={i} className="small facts">{f}</div>)}
        <div className="small ask-title">Ask the care team</div>
        <ul className="asks">{t.asks.map((a, i) => <li key={i}>{a}</li>)}</ul>
        {t.go_now && <div className="small go-now">🚨 {t.go_now}</div>}
        {t.evidence.map((e, i) => (
          <div key={i} className="quote">
            “{e.quote}” — {e.document_id ? <a href={`/api/documents/${e.document_id}/file`} target="_blank" rel="noreferrer">{e.filename || `D${e.document_id}`}</a> : "report"}
          </div>
        ))}
      </div>
    </li>
  );
}

export function SettleFirst({ tracks }: { tracks: PriorityTrack[] }) {
  if (tracks.length === 0) return null;
  return (
    <div className="card settle">
      <div className="card-head"><h3>🎯 Settle these first <span className="muted small">— from the latest scan, in this order</span></h3></div>
      <ol className="donext-list">{tracks.map((t, i) => <TrackCard key={t.id} t={t} n={i + 1} />)}</ol>
      <p className="muted small" style={{ marginBottom: 0 }}>These are questions for the treating team, drawn from what the report says. They are not diagnoses or medical orders. Each is also tracked in <b>Advisors’ recommendations</b>.</p>
    </div>
  );
}

function Question({ q, onDone }: { q: PriorityQuestion; onDone: (alert: { level: string; message: string } | null) => void }) {
  const [detail, setDetail] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const pick = async (value: string) => {
    setBusy(true);
    setErr("");
    try {
      const r = await api.answerQuestion(q.id, value, detail);
      onDone(r.alert);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };
  return (
    <li className="question">
      <div><strong>{q.text}</strong></div>
      <div className="muted small">{q.why}</div>
      {q.detail_label && <input className="q-detail" placeholder={q.detail_label} value={detail} onChange={(e) => setDetail(e.target.value)} />}
      <div className="row wrap" style={{ justifyContent: "flex-start", marginTop: 6 }}>
        {q.options.map((o) => (
          <button key={o.value} disabled={busy} className={o.value === "unsure" ? "small-btn" : "small-btn primary"} onClick={() => pick(o.value)}>{o.label}</button>
        ))}
      </div>
      {err && <div className="hint">{err}</div>}
    </li>
  );
}

export function Questions({ questions, onAnswered }: { questions: PriorityQuestion[]; onAnswered: () => void }) {
  const [alert, setAlert] = useState<{ level: string; message: string } | null>(null);
  if (questions.length === 0 && !alert) return null;
  return (
    <div className="card questions">
      <div className="card-head"><h3>❓ Help the plan be accurate <span className="muted small">— {questions.length} quick question{questions.length === 1 ? "" : "s"}</span></h3></div>
      {alert && <div className={alert.level === "emergency" ? "alert emergency" : "alert urgent"}><ReactMarkdown>{alert.message}</ReactMarkdown></div>}
      <ul className="plain">
        {questions.map((q) => <Question key={q.id} q={q} onDone={(a) => { if (a) setAlert(a); onAnswered(); }} />)}
      </ul>
    </div>
  );
}

export function MessageCard({ message }: { message: Priorities["message"] }) {
  const [copied, setCopied] = useState(false);
  const [text, setText] = useState(message.text);
  useEffect(() => setText(message.text), [message.text]);
  if (!message.available) return null;
  return (
    <details className="card message-card">
      <summary><strong>✉️ Message to send the oncologist</strong> <span className="muted small">— ready to copy, edit if you like</span></summary>
      <textarea rows={Math.min(18, text.split("\n").length + 1)} value={text} onChange={(e) => setText(e.target.value)} aria-label="Message to the oncologist" />
      <div className="row wrap" style={{ justifyContent: "flex-start" }}>
        <button className="primary" onClick={() => { void navigator.clipboard?.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2500); }}>{copied ? "Copied" : "Copy message"}</button>
        {message.attach && <span className="muted small">Attach the report: <b>{message.attach}</b>. Built only from figures in your confirmed scan data.</span>}
      </div>
    </details>
  );
}
