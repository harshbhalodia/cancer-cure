import { useEffect, useState } from "react";
import { api, type WatchTrends } from "../api";
import { useWatch } from "./Alerts";

function Spark({ pts, tone }: { pts: { day: string; value: number }[]; tone: string }) {
  if (pts.length < 2) return <div className="spark-empty muted small">{pts.length ? "1 day so far" : "no data"}</div>;
  const vals = pts.map((p) => p.value);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const w = 160, h = 40;
  const xy = pts.map((p, i) => [(i / (pts.length - 1)) * (w - 8) + 4, h - 6 - ((p.value - lo) / span) * (h - 12)]);
  return (
    <svg className={`spark ${tone}`} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="trend">
      <polyline points={xy.map((p) => p.join(",")).join(" ")} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      {xy.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r={i === xy.length - 1 ? 3.5 : 2} fill="currentColor" />)}
    </svg>
  );
}

function direction(slope: number | null, lowerBetter: boolean | null): { text: string; tone: string } {
  if (slope === null) return { text: "need 4+ days of logs for a trend", tone: "calm" };
  if (Math.abs(slope) < 0.05) return { text: "steady", tone: "calm" };
  const up = slope > 0;
  const good = lowerBetter === null ? null : lowerBetter ? !up : up;
  return { text: `${up ? "rising" : "falling"} about ${Math.abs(slope).toFixed(2)} a day`, tone: good === null ? "calm" : good ? "better" : "worse" };
}

export default function WatchTab() {
  const { snap } = useWatch(60000);
  const [t, setT] = useState<WatchTrends | null>(null);
  const [perm, setPerm] = useState<string>(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
  useEffect(() => { void api.watchTrends().then(setT); }, [snap?.active.length]);

  return (
    <div>
      <p className="muted" style={{ marginTop: 10 }}>
        Every log is compared with your own usual numbers. The app looks for sudden changes, slow slides and signs you are recovering, and tells you what to check or do straight away.
      </p>
      <div className="card">
        <div className="card-head"><h3>Where each area stands</h3></div>
        <div className="areas">
          {[["symptom", "🩺 Symptoms"], ["vitals", "🌡️ Vitals"], ["medicine", "💊 Medicines"], ["diet", "🥗 Diet"], ["routine", "🗓️ Routine"], ["mind", "🌅 Mind"], ["report", "📄 Reports"], ["trend", "📈 Trends"]].map(([d, label]) => {
            const mine = snap?.active.filter((s) => s.domain === d && s.status !== "resolved") ?? [];
            const worst = mine.some((s) => s.level === "emergency") ? "emergency" : mine.some((s) => s.level === "urgent") ? "urgent" : mine.some((s) => s.level === "watch") ? "watch" : mine.some((s) => s.level === "recovering") ? "recovering" : "ok";
            return <div key={d} className={`area ${worst}`}><span>{label}</span><b>{worst === "ok" ? "All clear" : mine.length === 1 ? mine[0].title : `${mine.length} items`}</b></div>;
          })}
        </div>
      </div>

      {t && t.metrics.length > 0 ? (
        <div className="metric-grid">
          {t.metrics.map((m) => {
            const d = direction(m.slope_per_day, m.lower_is_better);
            return (
              <div className="card metric" key={m.key}>
                <div className="card-head" style={{ marginBottom: 2 }}><h3 style={{ margin: 0 }}>{m.label}</h3></div>
                <div className="metric-num">{m.latest}<span className="muted small">{m.unit}</span></div>
                <div className="muted small">{d.text}</div>
                <div className={`spark-wrap ${d.tone}`}><Spark pts={m.series} tone={d.tone} /></div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="empty-card"><h3 style={{ marginTop: 0 }}>Trends appear as you log</h3><p className="muted">Log a few times a day for a few days. After about four days the app can show your usual numbers and warn you when something drifts.</p></div>
      )}

      <div className="card">
        <div className="card-head"><h3>Alerts on this device</h3></div>
        {perm === "unsupported" ? <p className="muted small">This browser cannot show notifications. Keep the app open to see alerts.</p> : perm === "granted" ? (
          <p className="muted small">On. You will get a notification here when a new urgent or emergency alert appears while the app is open.</p>
        ) : (
          <div className="row wrap" style={{ justifyContent: "flex-start" }}>
            <button onClick={() => Notification.requestPermission().then(setPerm)}>Turn on notifications</button>
            <span className="muted small">{perm === "denied" ? "Blocked in the browser settings." : "So an urgent alert is not missed."}</span>
          </div>
        )}
      </div>

      {snap?.history && snap.history.length > 0 && (
        <div className="card">
          <div className="card-head"><h3>Recently resolved</h3></div>
          <ul className="plain headlines">
            {snap.history.slice(0, 10).map((s) => (
              <li key={s.id} className="small">{s.level === "recovering" ? "🌱" : "✔"} {s.title} <span className="muted">· {s.resolved_at ? new Date(s.resolved_at).toLocaleString() : ""}</span></li>
            ))}
          </ul>
        </div>
      )}

      <details className="card">
        <summary><strong>How the alerts are decided</strong></summary>
        <ul className="small">
          <li><b>Emergency:</b> short of breath, chest pain, coughing blood, fainting, new confusion, oxygen below 92%, words of despair, or an emergency phrase in your note.</li>
          <li><b>Act today:</b> temperature 38 °C or more, pulse over 120 or under 45, top blood pressure under 90 or 180+, pain 8+, neck swelling, bleeding, new lump, swollen limb, a medicine not ticked for two days, weight down 5% in a month, pain up 3+ points on your usual, or an urgent report item still open after a day.</li>
          <li><b>Keep an eye on:</b> pain up 2+, appetite, energy or mood down 1.5+ against your usual week, weight down 2% in a week, a missed medicine today, poor sleep two nights, three low-mood days, and “heading toward” forecasts from a straight-line trend over the last week.</li>
          <li><b>Recovering:</b> pain easing, appetite/energy/mood improving, fever settled.</li>
          <li>These are conservative starting points for your oncologist to review. The steps only ever say to check, recheck, log again, or call; never to change treatment or doses.</li>
        </ul>
      </details>
    </div>
  );
}
