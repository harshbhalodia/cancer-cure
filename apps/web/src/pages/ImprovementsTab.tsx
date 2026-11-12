import { useEffect, useState } from "react";
import { api, type TrendMetric, type Trends } from "../api";

const VERDICT: Record<string, { text: string; cls: string }> = {
  better: { text: "Better", cls: "good" }, worse: { text: "Worse", cls: "watch" }, steady: { text: "Steady", cls: "calm" },
  up: { text: "Up", cls: "calm" }, down: { text: "Down", cls: "calm" },
};

function Spark({ m }: { m: TrendMetric }) {
  const pts = m.series.slice(-14);
  if (pts.length < 2) return <div className="spark-empty muted small">{pts.length ? "1 entry so far" : "no entries yet"}</div>;
  const vals = pts.map((p) => p.value);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = hi - lo || 1;
  const w = 160, h = 40;
  const xy = pts.map((p, i) => [(i / (pts.length - 1)) * (w - 8) + 4, h - 6 - ((p.value - lo) / span) * (h - 12)]);
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${m.label} over the last two weeks`}>
      <polyline points={xy.map((p) => p.join(",")).join(" ")} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      {xy.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r={i === xy.length - 1 ? 3.5 : 2} fill="currentColor" />)}
    </svg>
  );
}

export default function ImprovementsTab({ version }: { version: number }) {
  const [t, setT] = useState<Trends | null>(null);
  useEffect(() => { void api.trends().then(setT); }, [version]);
  if (!t) return <p className="muted">Loading…</p>;

  const withData = t.metrics.filter((m) => m.series.length > 0);
  if (t.checkin_days === 0 && t.adherence.length === 0) {
    return (
      <div className="empty-card" style={{ marginTop: 14 }}>
        <h3 style={{ marginTop: 0 }}>Your improvements will appear here</h3>
        <p className="muted">Check in on the Today tab for a few days and tick off your habits. Each week is compared with the one before, so you can see what is helping.</p>
      </div>
    );
  }
  return (
    <div>
      <div className="card">
        <div className="card-head">
          <h3>This week compared with last week</h3>
          <span className="muted small">{t.checkin_days} check-in day{t.checkin_days === 1 ? "" : "s"} so far{t.checkin_streak >= 2 ? ` · 🔥 ${t.checkin_streak} in a row` : ""}</span>
        </div>
        {t.headlines.length === 0 ? (
          <p className="muted">Two or more check-ins in each of two weeks are needed before trends are shown. Keep going — a minute a day is enough.</p>
        ) : (
          <ul className="plain headlines">
            {t.headlines.map((h, i) => <li key={i} className={`tone ${h.tone}`}><span aria-hidden>{h.tone === "good" ? "✅" : h.tone === "watch" ? "⚠️" : "➖"}</span> {h.text}</li>)}
          </ul>
        )}
        <p className="muted small" style={{ marginBottom: 0 }}>These are your own entries, compared plainly. They are not test results and do not measure the cancer; share worrying changes with your care team.</p>
      </div>

      {withData.length > 0 && (
        <div className="metric-grid">
          {withData.map((m) => (
            <div className="card metric" key={m.key}>
              <div className="card-head" style={{ marginBottom: 2 }}>
                <h3 style={{ margin: 0 }}>{m.label}</h3>
                {m.verdict && <span className={`badge verdict ${VERDICT[m.verdict].cls}`}>{VERDICT[m.verdict].text}</span>}
              </div>
              <div className="metric-num">{m.this_week ?? "—"}<span className="muted small">{m.this_week !== null ? m.unit : ""}</span> <span className="muted small">this week</span></div>
              <div className="muted small">{m.last_week !== null ? `${m.last_week}${m.unit} the week before` : "no data the week before"}{m.lower_is_better ? " · lower is better" : ""}</div>
              <div className={`spark-wrap ${m.verdict ?? "calm"}`}><Spark m={m} /></div>
            </div>
          ))}
        </div>
      )}

      {t.adherence.length > 0 && (
        <div className="card">
          <div className="card-head"><h3>Habits kept</h3><span className="muted small">share of planned days ticked</span></div>
          {t.adherence.map((a) => {
            const now = a.this_week === null ? 0 : Math.round(a.this_week * 100);
            const before = a.last_week === null ? null : Math.round(a.last_week * 100);
            return (
              <div className="adh" key={a.domain}>
                <span className="adh-label">{a.icon} {a.label}</span>
                <div className="meter"><div style={{ width: `${now}%` }} />{before !== null && <i className="marker" style={{ left: `${before}%` }} title={`Last week ${before}%`} />}</div>
                <span className="adh-pct">{now}%</span>
              </div>
            );
          })}
          <p className="muted small" style={{ marginBottom: 0 }}>The small tick on each bar marks last week.</p>
        </div>
      )}
    </div>
  );
}
