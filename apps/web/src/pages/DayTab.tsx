import { useCallback, useEffect, useState } from "react";
import { api, workspaceUrl, type HabitItem, type TodayView } from "../api";
import LogCard from "./LogCard";

const WHEN_LABEL: Record<string, string> = { morning: "Morning", midday: "Midday", evening: "Evening", bedtime: "Bedtime", anytime: "Any time" };

function MindCard({ view, onSaved }: { view: TodayView; onSaved: () => void }) {
  const [vision, setVision] = useState(view.vision);
  const [editing, setEditing] = useState(false);
  const ci = view.checkin;
  return (
    <div className="card mind-card">
      <div className="card-head"><h3>🌅 My intention</h3></div>
      {editing || !vision ? (
        <div className="vision-edit">
          <label className="mini-field wide">My recovery vision — in my own words
            <textarea rows={2} value={vision} placeholder="Describe the life you are working towards: where you are, who is with you, what you are doing…" onChange={(e) => setVision(e.target.value)} />
          </label>
          <button className="small-btn primary" onClick={() => api.saveVision(vision).then(() => { setEditing(false); onSaved(); })}>Save vision</button>
        </div>
      ) : (
        <blockquote className="vision" onClick={() => setEditing(true)} title="Click to edit">
          {vision} <span className="muted small">✎</span>
        </blockquote>
      )}
      <div className="grid2">
        <label className="mini-field wide">Today I intend to…
          <input defaultValue={ci?.intention ?? ""} placeholder="One line: how I want today to go" onBlur={(e) => e.target.value !== (ci?.intention ?? "") && api.saveCheckin({ intention: e.target.value }).then(onSaved)} />
        </label>
        <label className="mini-field wide">I am grateful for…
          <input defaultValue={ci?.gratitude ?? ""} placeholder="One small, specific thing" onBlur={(e) => e.target.value !== (ci?.gratitude ?? "") && api.saveCheckin({ gratitude: e.target.value }).then(onSaved)} />
        </label>
      </div>
      <p className="muted small" style={{ marginTop: 8 }}>Intention and visualisation support how you feel and cope. They sit alongside your treatment and are not a treatment for the cancer.</p>
    </div>
  );
}

function SuggestedMeds({ items, onChanged }: { items: HabitItem[]; onChanged: () => void }) {
  if (items.length === 0) return null;
  return (
    <div className="card confirm-card">
      <div className="card-head"><h3>💊 Medicines found in your documents</h3></div>
      <p className="muted small">Confirm the ones you are taking so they appear in your daily list. Check each dose against the prescription itself, and ask your doctor or pharmacist if anything is unclear.</p>
      <ul className="plain">
        {items.map((m) => (
          <li key={m.id} className="med-row">
            <div className="grow">
              <strong>{m.title}</strong> {m.dose && <span className="badge">{m.dose}</span>}
              {m.prescriber && <span className="muted small"> · {m.prescriber}</span>}
              {m.quote && <div className="quote">“{m.quote}” — {m.document_id ? <a href={workspaceUrl(`/api/documents/${m.document_id}/file`)} target="_blank" rel="noreferrer">{m.filename}</a> : "document"}</div>}
            </div>
            <button className="small-btn primary" onClick={() => api.patchHabit(m.id, { status: "active" }).then(onChanged)}>I take this</button>
            <button className="small-btn" onClick={() => api.patchHabit(m.id, { status: "dropped" }).then(onChanged)}>Not taking</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function HabitRow({ h, onToggle, onChanged }: { h: HabitItem; onToggle: (h: HabitItem) => void; onChanged: () => void }) {
  return (
    <li className={h.done ? "habit done" : "habit"}>
      <label className="habit-main">
        <input type="checkbox" checked={h.done} onChange={() => onToggle(h)} />
        <span className="habit-text">
          <span className="habit-title">{h.title}</span>
          {h.dose && <span className="habit-sub">💊 {h.dose}</span>}
          {h.detail && !h.dose && <span className="habit-sub">{h.detail}</span>}
        </span>
      </label>
      <span className="chip">{WHEN_LABEL[h.when] ?? h.when}</span>
      {h.streak >= 2 && <span className="streak" title={`${h.streak} days in a row`}>🔥 {h.streak}</span>}
      <span className="dots" title="Last 7 days" aria-label="Last 7 days">{h.week.map((d, i) => <i key={i} className={d ? "on" : ""} />)}</span>
      <details className="habit-menu">
        <summary aria-label="More">⋯</summary>
        <div className="menu-pop">
          <button className="small-btn" onClick={() => api.patchHabit(h.id, { status: "paused" }).then(onChanged)}>Pause</button>
          <button className="small-btn danger" onClick={() => api.deleteHabit(h.id).then(onChanged)}>Remove</button>
        </div>
      </details>
    </li>
  );
}

export default function DayTab({ onOpenStrategy }: { onOpenStrategy: () => void }) {
  const [view, setView] = useState<TodayView | null>(null);
  const [err, setErr] = useState("");
  const [form, setForm] = useState({ domain: "diet", title: "", when: "anytime", dose: "" });

  const load = useCallback(() => api.today().then(setView).catch((e: Error) => setErr(e.message)), []);
  useEffect(() => { void load(); }, [load]);

  const toggle = async (h: HabitItem) => {
    setView((v) => v && {
      ...v, habits: v.habits.map((x) => (x.id === h.id ? { ...x, done: !x.done } : x)),
      done: v.done + (h.done ? -1 : 1),
    });
    try {
      await api.logHabit(h.id, !h.done);
      await load();
    } catch {
      await load();
    }
  };

  if (!view) return err ? <div className="alert urgent">{err}</div> : <p className="muted">Loading…</p>;
  const pct = view.total ? Math.round((view.done / view.total) * 100) : 0;
  const groups = view.domains.map((d) => ({ d, items: view.habits.filter((h) => h.domain === d.id) })).filter((g) => g.items.length);

  return (
    <div>
      {err && <div className="alert urgent" onClick={() => setErr("")}>{err}</div>}
      {view.total > 0 && (
        <div className="today-meter">
          <div className="meter" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><div style={{ width: `${pct}%` }} /></div>
          <span><strong>{view.done}</strong> of {view.total} done today{view.done === view.total ? " — well done 🌟" : ""}{view.checkin_streak >= 2 ? ` · 🔥 ${view.checkin_streak}-day check-in streak` : ""}</span>
        </div>
      )}
      <MindCard view={view} onSaved={load} />
      <LogCard onLogged={load} />
      <SuggestedMeds items={view.suggested_medicines} onChanged={load} />

      {view.habits.length === 0 ? (
        <div className="empty-card">
          <h3 style={{ marginTop: 0 }}>Build your daily plan in one tap</h3>
          <p className="muted">A small, gentle set across food, movement, mind and support. You can change everything later and nothing is compulsory.</p>
          <div className="row" style={{ justifyContent: "flex-start" }}>
            <button className="primary" onClick={() => api.library().then((l) => api.addStarters(l.gentle_set)).then(load)}>Start with a gentle daily set</button>
            <button onClick={onOpenStrategy}>Choose from ideas</button>
          </div>
        </div>
      ) : (
        groups.map(({ d, items }) => (
          <div className="card" key={d.id}>
            <div className="card-head">
              <h3>{d.icon} {d.label}</h3>
              <span className="muted small">{items.filter((i) => i.done).length}/{items.length}</span>
            </div>
            <ul className="plain habits">{items.map((h) => <HabitRow key={h.id} h={h} onToggle={toggle} onChanged={load} />)}</ul>
          </div>
        ))
      )}

      <details className="card add-card">
        <summary><strong>＋ Add to my plan</strong> <span className="muted small">a medicine, meal habit, practice…</span></summary>
        <div className="grid-add">
          <select value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })} aria-label="Area">
            {view.domains.map((d) => <option key={d.id} value={d.id}>{d.icon} {d.label}</option>)}
          </select>
          <input placeholder={form.domain === "medication" ? "Medicine name" : "What will you do?"} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          {form.domain === "medication" && <input placeholder="Dose and timing, as prescribed" value={form.dose} onChange={(e) => setForm({ ...form, dose: e.target.value })} />}
          <select value={form.when} onChange={(e) => setForm({ ...form, when: e.target.value })} aria-label="When">
            {view.when.map((w) => <option key={w} value={w}>{WHEN_LABEL[w]}</option>)}
          </select>
          <button className="primary" disabled={!form.title.trim()} onClick={() => api.addHabit(form).then(() => { setForm({ ...form, title: "", dose: "" }); return load(); }).catch((e: Error) => setErr(e.message))}>Add</button>
        </div>
      </details>
    </div>
  );
}
