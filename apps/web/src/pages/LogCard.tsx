import { useCallback, useEffect, useState } from "react";
import { api, type WatchFlag, type WatchReading, type WatchSnapshot } from "../api";
import { notifyWatchChanged } from "./Alerts";

const SCALES: { key: "energy" | "mood" | "appetite"; label: string; faces: string[] }[] = [
  { key: "energy", label: "Energy", faces: ["🪫", "😴", "😐", "🙂", "⚡"] },
  { key: "mood", label: "Mood", faces: ["😞", "😕", "😐", "🙂", "😄"] },
  { key: "appetite", label: "Appetite", faces: ["🚫", "🥣", "🍽️", "😋", "🍛"] },
];
const LEVEL = ["Very low", "Low", "Okay", "Good", "Very good"];

function Scale({ label, faces, value, onPick }: { label: string; faces: string[]; value: number | null; onPick: (v: number | null) => void }) {
  return (
    <div className="scale">
      <span className="scale-label">{label}</span>
      <div className="scale-btns" role="radiogroup" aria-label={label}>
        {faces.map((f, i) => (
          <button key={i} role="radio" aria-checked={value === i + 1} title={`${label}: ${LEVEL[i]}`} className={value === i + 1 ? "face on" : "face"} onClick={() => onPick(value === i + 1 ? null : i + 1)}>{f}</button>
        ))}
      </div>
    </div>
  );
}

const EMPTY = { energy: null as number | null, mood: null as number | null, appetite: null as number | null, pain: null as number | null, temp_c: "", pulse: "", spo2: "", bp_sys: "", bp_dia: "", weight_kg: "", note: "" };

function summary(r: WatchReading): string {
  const bits: string[] = [];
  if (r.pain !== null) bits.push(`pain ${r.pain}/10`);
  if (r.energy !== null) bits.push(`energy ${r.energy}/5`);
  if (r.mood !== null) bits.push(`mood ${r.mood}/5`);
  if (r.appetite !== null) bits.push(`appetite ${r.appetite}/5`);
  if (r.temp_c !== null) bits.push(`${r.temp_c} °C`);
  if (r.pulse !== null) bits.push(`pulse ${r.pulse}`);
  if (r.spo2 !== null) bits.push(`SpO₂ ${r.spo2}%`);
  if (r.bp_sys !== null) bits.push(`BP ${r.bp_sys}/${r.bp_dia ?? "?"}`);
  if (r.weight_kg !== null) bits.push(`${r.weight_kg} kg`);
  return bits.join(" · ");
}

export default function LogCard({ onLogged }: { onLogged: () => void }) {
  const [form, setForm] = useState(EMPTY);
  const [flags, setFlags] = useState<string[]>([]);
  const [catalog, setCatalog] = useState<WatchFlag[]>([]);
  const [today, setToday] = useState<WatchReading[]>([]);
  const [result, setResult] = useState<{ snap: WatchSnapshot; checks: string[]; time: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [sleep, setSleep] = useState("");

  const loadToday = useCallback(() => api.watchReadings().then(setToday), []);
  useEffect(() => { void api.watchFlags().then(setCatalog); void loadToday(); }, [loadToday]);

  const toggle = (k: string) => setFlags((f) => (f.includes(k) ? f.filter((x) => x !== k) : [...f, k]));
  const empty = Object.values(form).every((v) => v === null || v === "") && flags.length === 0;

  async function submit() {
    setBusy(true);
    setErr("");
    const body: Record<string, unknown> = { flags };
    for (const [k, v] of Object.entries(form)) if (v !== null && v !== "") body[k] = typeof v === "string" && k !== "note" ? Number(v) : v;
    try {
      const r = await api.logReading(body);
      setResult({ snap: r.snapshot, checks: r.check_now, time: r.reading.time });
      setForm(EMPTY);
      setFlags([]);
      await loadToday();
      notifyWatchChanged();
      onLogged();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const open = result?.snap.active.filter((s) => s.status === "open") ?? [];
  const worst = open.find((s) => s.level === "emergency") ?? open.find((s) => s.level === "urgent");
  const good = open.filter((s) => s.level === "recovering");

  return (
    <div className="card log-card">
      <div className="card-head">
        <h3>📝 Log how things are right now</h3>
        <span className="muted small">As often as you like · skip anything · {today.length} log{today.length === 1 ? "" : "s"} today</span>
      </div>
      {SCALES.map((s) => <Scale key={s.key} label={s.label} faces={s.faces} value={form[s.key]} onPick={(v) => setForm({ ...form, [s.key]: v })} />)}
      <div className="scale">
        <span className="scale-label">Pain</span>
        <div className="scale-btns pain" role="radiogroup" aria-label="Pain from 0 to 10">
          {Array.from({ length: 11 }, (_, n) => (
            <button key={n} role="radio" aria-checked={form.pain === n} title={n === 0 ? "No pain" : n === 10 ? "Worst pain" : `Pain ${n}`} className={form.pain === n ? `pain-btn on p${Math.min(3, Math.floor(n / 3))}` : "pain-btn"} onClick={() => setForm({ ...form, pain: form.pain === n ? null : n })}>{n}</button>
          ))}
        </div>
      </div>

      <div className="small ask-title" style={{ marginTop: 10 }}>Anything new? Tap what applies</div>
      <div className="chips">
        {catalog.map((f) => (
          <button key={f.key} aria-pressed={flags.includes(f.key)} className={`chip-btn ${f.level} ${flags.includes(f.key) ? "on" : ""}`} onClick={() => toggle(f.key)}>{f.label}</button>
        ))}
      </div>

      <details className="vitals">
        <summary>🌡️ Vitals &amp; weight <span className="muted small">(only if you measured)</span></summary>
        <div className="row wrap" style={{ justifyContent: "flex-start", gap: 12, marginTop: 8 }}>
          <label className="mini-field">Temp (°C or °F)<input type="number" step="0.1" value={form.temp_c} onChange={(e) => setForm({ ...form, temp_c: e.target.value })} /></label>
          <label className="mini-field">Pulse (/min)<input type="number" value={form.pulse} onChange={(e) => setForm({ ...form, pulse: e.target.value })} /></label>
          <label className="mini-field">SpO₂ (%)<input type="number" value={form.spo2} onChange={(e) => setForm({ ...form, spo2: e.target.value })} /></label>
          <label className="mini-field">BP top<input type="number" value={form.bp_sys} onChange={(e) => setForm({ ...form, bp_sys: e.target.value })} /></label>
          <label className="mini-field">BP bottom<input type="number" value={form.bp_dia} onChange={(e) => setForm({ ...form, bp_dia: e.target.value })} /></label>
          <label className="mini-field">Weight (kg)<input type="number" step="0.1" value={form.weight_kg} onChange={(e) => setForm({ ...form, weight_kg: e.target.value })} /></label>
        </div>
      </details>

      <label className="mini-field wide" style={{ marginTop: 8 }}>Note
        <textarea rows={2} value={form.note} placeholder="e.g. after lunch the mouth felt sore; swallowed soup fine…" onChange={(e) => setForm({ ...form, note: e.target.value })} />
      </label>
      <div className="row wrap" style={{ justifyContent: "flex-start", marginTop: 8 }}>
        <button className="primary" disabled={busy || empty} onClick={submit}>{busy ? "Checking…" : "Log now"}</button>
        <label className="mini-field inline">Last night’s sleep (h)
          <input type="number" min={0} max={24} step={0.5} value={sleep} onChange={(e) => setSleep(e.target.value)} onBlur={() => sleep !== "" && api.saveCheckin({ sleep_hours: Number(sleep) }).then(notifyWatchChanged)} />
        </label>
        {err && <span className="hint">{err}</span>}
      </div>

      {result && (
        <div className={`log-result ${worst ? worst.level : good.length ? "good" : "calm"}`}>
          <strong>Logged at {result.time}.</strong>{" "}
          {worst ? (
            <>Right now: <b>{worst.title}</b>. {worst.actions[0]?.text}</>
          ) : good.length ? (
            <>Good news: {good[0].title}. Keep doing what is working.</>
          ) : open.length ? (
            <>Nothing urgent. {open.length} thing{open.length === 1 ? "" : "s"} worth a look above.</>
          ) : (
            <>Nothing worrying in this log. Keep going and log again later.</>
          )}
          {result.checks.length > 0 && <ul className="steps">{result.checks.slice(0, 3).map((c, i) => <li key={i}>🔎 {c}</li>)}</ul>}
        </div>
      )}

      {today.length > 0 && (
        <ul className="plain log-list">
          {[...today].reverse().map((r) => (
            <li key={r.id}>
              <span className="log-time">{r.time}</span>
              <span className="grow small">{summary(r)}{r.flags.length ? ` · ${r.flags.map((f) => catalog.find((c) => c.key === f)?.label ?? f).join(", ")}` : ""}{r.note ? ` — ${r.note}` : ""}</span>
              <button className="link small" onClick={() => api.deleteReading(r.id).then(() => { void loadToday(); notifyWatchChanged(); onLogged(); })} title="Remove this log (e.g. entered by mistake)">remove</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
