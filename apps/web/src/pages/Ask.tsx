import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api, type Message } from "../api";

const SUGGESTIONS = [
  "Summarise my latest report in plain language",
  "What changed compared with the previous scan?",
  "Prepare questions for the next oncologist visit",
  "Explain the medical terms in the latest report",
];

export default function Ask({ role, aiReady, onNavigate }: { role: string; aiReady: boolean; onNavigate: (t: "case" | "documents") => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.history().then(setMessages).catch(() => undefined);
  }, []);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(message: string) {
    const msg = message.trim();
    if (!msg || busy) return;
    setText("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", content: msg, citations: [], flags: [] }]);
    try {
      const reply = await api.chat(msg, role);
      setMessages((m) => [...m, { ...reply, role: "assistant" }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: `Something went wrong: ${(e as Error).message}`, citations: [], flags: [] }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="page chat">
      <header className="page-head">
        <h1>Ask</h1>
        <p>Answers use your case file and uploaded documents, and cite where each fact came from.</p>
      </header>
      <div className="messages">
        {messages.length === 0 && (
          <div className="empty">
            <h2>How can I help today?</h2>
            <p>
              Drop a report anywhere on this page, or <button className="link" onClick={() => onNavigate("documents")}>open Documents</button>. Fill in the{" "}
              <button className="link" onClick={() => onNavigate("case")}>case file</button> so answers stay specific.
            </p>
            <div className="chips">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="chip" onClick={() => send(s)} disabled={!aiReady}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={m.id ?? `t${i}`} className={`msg ${m.role}`}>
            {m.flags.filter((f) => f.type === "triage").map((f, k) => (
              <div key={k} className={`alert ${f.level}`}>
                {f.level === "emergency" ? "Possible emergency" : "Contact your care team today"}: {f.reasons?.join("; ")}
              </div>
            ))}
            {m.role === "assistant" ? <ReactMarkdown>{m.content}</ReactMarkdown> : <p>{m.content}</p>}
            {m.citations.length > 0 && (
              <div className="sources">
                Sources:{" "}
                {m.citations.map((c) => (
                  <a key={`${c.document_id}-${c.page}`} href={`/api/documents/${c.document_id}/file`} target="_blank" rel="noreferrer">
                    D{c.document_id} p{c.page} · {c.filename}
                    {c.doc_date ? ` (${c.doc_date})` : ""}
                  </a>
                ))}
              </div>
            )}
            {m.flags.some((f) => f.type === "safety") && <div className="note">Part of this answer was withheld for safety. Please ask your oncology team.</div>}
          </div>
        ))}
        {busy && <div className="msg assistant thinking">Thinking… a local model can take a minute for detailed answers.</div>}
        <div ref={end} />
      </div>
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send(text);
        }}
      >
        <textarea
          value={text}
          placeholder={aiReady ? "Ask about a report, a symptom, a term, or what to ask the doctor…" : "The local AI is not available — start LM Studio's server"}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send(text);
            }
          }}
          rows={2}
        />
        <button className="primary" disabled={busy || !text.trim()}>
          Send
        </button>
      </form>
    </section>
  );
}
