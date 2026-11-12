import { useCallback, useEffect, useState } from "react";
import { api, type Domain, type PackInfo, type Starter } from "../api";
import { PackPanel } from "./PlanTab";

const PACK_ID = "carecompanion.wellbeing";

export default function StrategyTab({ onChanged }: { onChanged: () => void }) {
  const [pack, setPack] = useState<PackInfo | null>(null);
  const [starters, setStarters] = useState<Starter[]>([]);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [detail, setDetail] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const loadPack = useCallback(() => api.advisors().then((r) => setPack(r.packs.find((p) => p.id === PACK_ID) ?? null)), []);
  const loadLib = useCallback(() => api.library().then((l) => { setStarters(l.starters); setDomains(l.domains); }), []);
  useEffect(() => { void loadPack(); void loadLib(); }, [loadPack, loadLib]);

  const running = !!pack?.running;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      void loadPack();
      api.jobsSummary().then((s) => setDetail(s.current?.kind === "plan" ? s.current.detail : "")).catch(() => undefined);
    }, 4000);
    return () => clearInterval(t);
  }, [running, loadPack]);

  const add = (s: Starter) => api.addStarters([s.key]).then(() => { void loadLib(); onChanged(); });

  return (
    <div>
      <p className="muted" style={{ marginTop: 10 }}>
        Your strategy for diet, routine, medicines, mind and movement, written from your own plan, your check-ins and what your advisors recommended.
        It never changes treatment and never claims that a food or practice treats cancer.
      </p>
      {err && <div className="alert urgent">{err}</div>}
      {pack ? (
        <PackPanel pack={pack} runningDetail={detail} onRun={() => api.runAdvisor(PACK_ID).then(loadPack).catch((e: Error) => setErr(e.message))} />
      ) : (
        <p className="muted small">The wellbeing strategy pack is not available.</p>
      )}

      <h2 className="section">Ideas to add to your day <span className="muted small">— tap + to add; confirm diet or activity changes with your care team</span></h2>
      {domains.filter((d) => starters.some((s) => s.domain === d.id)).map((d) => (
        <div className="card" key={d.id}>
          <div className="card-head"><h3>{d.icon} {d.label}</h3></div>
          <p className="muted small" style={{ marginTop: 0 }}>{d.why}</p>
          <ul className="plain ideas">
            {starters.filter((s) => s.domain === d.id).map((s) => (
              <li key={s.key}>
                <div className="grow"><strong>{s.title}</strong><div className="muted small">{s.detail}</div></div>
                {s.added ? <span className="badge ready">In my plan</span> : <button className="small-btn primary" onClick={() => add(s)} aria-label={`Add ${s.title}`}>＋ Add</button>}
              </li>
            ))}
          </ul>
        </div>
      ))}

      <div className="card">
        <div className="card-head"><h3>💊 Medicines</h3></div>
        <p className="muted small" style={{ marginTop: 0 }}>
          Medicines are read from your prescriptions and discharge notes (quoted, and shown for you to confirm) or added by you. The app only records and reminds; it never suggests a dose.
        </p>
        <div className="row" style={{ justifyContent: "flex-start" }}>
          <button onClick={() => api.scanMedicines().then((r) => setMsg(r.queued ? `Reading ${r.queued} document${r.queued === 1 ? "" : "s"} in the background — found medicines appear on the Today tab to confirm.` : "No documents mention medicines yet.")).catch((e: Error) => setErr(e.message))}>
            Look for medicines in my documents
          </button>
          {msg && <span className="muted small">{msg}</span>}
        </div>
      </div>
    </div>
  );
}
