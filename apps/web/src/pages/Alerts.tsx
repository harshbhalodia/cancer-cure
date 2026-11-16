import { useCallback, useEffect, useState } from "react";
import { api, type WatchSignal, type WatchSnapshot } from "../api";

export const WATCH_EVENT = "cc-watch-changed";
export const notifyWatchChanged = () => window.dispatchEvent(new Event(WATCH_EVENT));

export function useWatch(pollMs = 30000) {
  const [snap, setSnap] = useState<WatchSnapshot | null>(null);
  const load = useCallback(() => api.watchSignals().then(setSnap).catch(() => undefined), []);
  useEffect(() => {
    void load();
    const t = setInterval(load, pollMs);
    window.addEventListener(WATCH_EVENT, load);
    return () => { clearInterval(t); window.removeEventListener(WATCH_EVENT, load); };
  }, [load, pollMs]);
  return { snap, reload: load };
}

const LEVEL_LABEL: Record<string, string> = { emergency: "Emergency", urgent: "Act today", watch: "Keep an eye on", recovering: "Recovering", info: "Note" };
const KIND_ICON: Record<string, string> = { call: "📞", check: "🔎", do: "✅", log: "📝" };
const DOMAIN_ICON: Record<string, string> = { symptom: "🩺", vitals: "🌡️", medicine: "💊", diet: "🥗", routine: "🗓️", mind: "🌅", report: "📄", trend: "📈" };

function ago(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 2) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
}

function AlertCard({ s, onAck }: { s: WatchSignal; onAck: (id: number, note: string, recheck?: number) => void }) {
  const [note, setNote] = useState("");
  const [recheck, setRecheck] = useState("60");
  const recovering = s.level === "recovering";
  return (
    <li className={`alert-card ${s.level} ${s.status === "ack" ? "ack" : ""}`}>
      <div className="alert-top">
        <span className="alert-ico" aria-hidden>{DOMAIN_ICON[s.domain] ?? "•"}</span>
        <div className="grow">
          <div><span className={`badge lvl-${s.level}`}>{LEVEL_LABEL[s.level]}</span> <strong>{s.title}</strong></div>
          <div className="small muted">{s.why} · {ago(s.since)}{s.recheck_due && s.status === "open" ? " · recheck due now" : ""}</div>
        </div>
      </div>
      <ul className="steps">
        {s.actions.map((a, i) => <li key={i} className={`step ${a.kind}`}><span aria-hidden>{KIND_ICON[a.kind]}</span> {a.text}</li>)}
      </ul>
      {s.status === "ack" ? (
        <div className="small muted">Acknowledged{s.ack_note ? `: ${s.ack_note}` : ""}. It will come back if it gets worse.</div>
      ) : (
        <div className="row wrap" style={{ justifyContent: "flex-start", gap: 6 }}>
          <input className="ack-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder={recovering ? "What do you think helped? (optional)" : "What you did, e.g. called the team (optional)"} />
          {!recovering && (
            <select value={recheck} onChange={(e) => setRecheck(e.target.value)} aria-label="Remind me to recheck">
              <option value="30">recheck in 30 min</option><option value="60">recheck in 1 h</option><option value="240">recheck in 4 h</option><option value="">no reminder</option>
            </select>
          )}
          <button className="small-btn primary" onClick={() => onAck(s.id, note, recheck ? Number(recheck) : undefined)}>{recovering ? "Noted" : "I’ve done this"}</button>
        </div>
      )}
    </li>
  );
}

export function AlertsPanel({ snap, onChange }: { snap: WatchSnapshot | null; onChange?: () => void }) {
  const [busy, setBusy] = useState(false);
  if (!snap || snap.active.length === 0) return null;
  const ack = async (id: number, note: string, recheck?: number) => {
    setBusy(true);
    try { await api.ackSignal(id, note, recheck); notifyWatchChanged(); onChange?.(); } finally { setBusy(false); }
  };
  const serious = snap.active.filter((s) => s.status === "open" && (s.level === "emergency" || s.level === "urgent")).length;
  return (
    <div className={`card alerts ${snap.highest ?? ""}`} aria-live="polite">
      <div className="card-head">
        <h3>{serious ? "🚨 Needs your attention now" : "👀 Worth a look"}</h3>
        <span className="muted small">{snap.active.filter((s) => s.status === "open").length} open</span>
      </div>
      <ul className={`plain alert-list ${busy ? "busy" : ""}`}>{snap.active.map((s) => <AlertCard key={s.id} s={s} onAck={ack} />)}</ul>
      <p className="muted small" style={{ marginBottom: 0 }}>Found by simple rules from what you log. They tell you what to check and when to call; they are not a diagnosis. In an emergency call the emergency number first.</p>
    </div>
  );
}
