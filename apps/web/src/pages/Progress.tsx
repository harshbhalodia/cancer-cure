import { useEffect, useState } from "react";
import { api, type Progress as ProgressData, type Series } from "../api";

const COLORS = ["#1f7a6d", "#c2562e", "#4f6bd6", "#a8801a", "#8a4fb0"];

function Chart({ series }: { series: Series[] }) {
  const pts = series.flatMap((s) => s.points);
  if (pts.length === 0) return null;
  const times = pts.map((p) => new Date(p.date).getTime());
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const yMax = Math.max(10, Math.ceil((Math.max(...pts.map((p) => p.size_mm)) * 1.15) / 10) * 10);
  const W = 640, H = 240, L = 44, R = 16, T = 14, B = 34;
  const x = (d: string) => (tMax === tMin ? (L + W - R) / 2 : L + ((new Date(d).getTime() - tMin) / (tMax - tMin)) * (W - L - R));
  const y = (v: number) => H - B - (v / yMax) * (H - T - B);
  const dates = [...new Set(pts.map((p) => p.date))].sort();
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Lesion sizes over time">
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line x1={L} x2={W - R} y1={y(yMax * f)} y2={y(yMax * f)} stroke="var(--line)" />
          <text x={L - 6} y={y(yMax * f) + 4} textAnchor="end" fontSize="11" fill="var(--muted)">{Math.round(yMax * f)}</text>
        </g>
      ))}
      <text x={4} y={12} fontSize="11" fill="var(--muted)">mm</text>
      {dates.map((d) => (
        <text key={d} x={x(d)} y={H - 10} textAnchor={x(d) > W - 60 ? "end" : x(d) < L + 40 ? "start" : "middle"} fontSize="11" fill="var(--muted)">{d}</text>
      ))}
      {series.map((s, i) => {
        const c = COLORS[i % COLORS.length];
        return (
          <g key={s.lesion}>
            <polyline fill="none" stroke={c} strokeWidth="2.5" points={s.points.map((p) => `${x(p.date)},${y(p.size_mm)}`).join(" ")} />
            {s.points.map((p) => (
              <g key={p.date}>
                <circle cx={x(p.date)} cy={y(p.size_mm)} r="5" fill={p.kind === "current" ? c : "var(--panel)"} stroke={c} strokeWidth="2" />
                <text x={x(p.date)} y={y(p.size_mm) - 9} textAnchor="middle" fontSize="11" fill="var(--ink)">{p.size_mm}</text>
              </g>
            ))}
          </g>
        );
      })}
    </svg>
  );
}

const CERT: Record<string, string> = { definite: "stated", possible: "possible — not confirmed", absent: "not seen" };

export default function Progress({ version, onOpenDoc, onOpenInbox }: { version: number; onOpenDoc: () => void; onOpenInbox: () => void }) {
  const [data, setData] = useState<ProgressData | null>(null);
  const [waiting, setWaiting] = useState(0);
  useEffect(() => {
    api.progress().then(setData).catch(() => setData({ series: [], scans: [] }));
    api.jobs().then((j) => setWaiting(j.filter((x) => x.has_scan).length)).catch(() => undefined);
  }, [version]);
  if (!data) return <section className="page">Loading…</section>;
  const targets = data.series.filter((s) => s.is_target);

  return (
    <section className="page">
      <header className="page-head">
        <h1>Progress</h1>
        <p>What the scans say, measured the same way every time. Sizes come from your confirmed reports; the app does the arithmetic.</p>
      </header>
      {waiting > 0 && (
        <div className="scan-banner">
          <span>
            <b>{waiting} scan report{waiting === 1 ? " is" : "s are"} waiting for your review.</b> Progress only updates from <em>Review scan data</em>
            {" "}— reviewing case-file updates doesn’t add measurements here.
          </span>
          <button className="primary" onClick={onOpenInbox}>Review them now</button>
        </div>
      )}
      {data.scans.length === 0 && (
        <div className="empty-card">
          <strong>No scan data yet.</strong>
          <p className="muted">
            Go to <button className="link" onClick={onOpenDoc}>Documents</button> and choose <em>Read scan data</em> on an imaging report. You review every value before it is saved.
          </p>
        </div>
      )}
      {targets.length > 0 && (
        <div className="card">
          <h3>Target lesion size</h3>
          <Chart series={targets} />
          <div className="legend">
            {targets.map((s, i) => (
              <span key={s.lesion}><i style={{ background: COLORS[i % COLORS.length] }} /> {s.label}</span>
            ))}
            <span className="muted">● measured on that scan &nbsp; ○ quoted by a later report as the earlier size</span>
          </div>
        </div>
      )}
      {[...data.scans].reverse().map((s) => (
        <div key={s.id} className="card">
          <h3>
            {s.modality || "Scan"} · {s.date || "date unknown"}
            {s.comparator_date && <span className="muted"> — compared with {s.comparator_modality || "previous study"} {s.comparator_date}</span>}
          </h3>
          <div className="compare">
            <div>
              <div className="muted small">Report says</div>
              <strong>{s.reported.label || "—"}</strong>
              {s.reported.pct != null && <div className="muted small">{s.reported.pct}% change ({s.reported.sum_prior} → {s.reported.sum_now} mm)</div>}
            </div>
            <div>
              <div className="muted small">App computed (sizes only)</div>
              {s.computed ? (
                <>
                  <strong>{s.computed.category_label}</strong>
                  <div className="muted small">{s.computed.pct_change}% ({s.computed.sum_prior} → {s.computed.sum_now} mm)</div>
                </>
              ) : (
                <span className="muted">Needs the same lesion measured on both scans</span>
              )}
            </div>
          </div>
          {s.discrepancy && <div className="alert urgent">{s.discrepancy}</div>}
          {s.computed && <p className="muted small">{s.computed.caveat}</p>}
          {s.findings.length > 0 && (
            <ul className="findings">
              {s.findings.map((f) => (
                <li key={f.id} className={f.certainty}>
                  <span className={`badge ${f.certainty}`}>{CERT[f.certainty] ?? f.certainty}</span> {f.text}
                  {f.quote && <div className="quote">“{f.quote}”</div>}
                </li>
              ))}
            </ul>
          )}
          <a href={`/api/documents/${s.document_id}/file`} target="_blank" rel="noreferrer" className="small">Open the report (D{s.document_id})</a>
        </div>
      ))}
    </section>
  );
}
