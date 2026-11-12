import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api, type DoNextItem, type PackInfo } from "../api";

const KIND_LABEL: Record<string, string> = { recommendation: "Advisor advised", finding: "From the reports", check: "Missing check" };
const SEV_CLASS: Record<string, string> = { attention: "attention", advice: "advice", question: "question", info: "info", check: "check" };

function DoNextCard({ it, onChanged }: { it: DoNextItem; onChanged: () => void }) {
  const set = (status: string) => api.setRecStatus(it.rec_id!, status).then(onChanged);
  return (
    <li className={`donext ${SEV_CLASS[it.severity] ?? ""}`}>
      <span className="rank">{it.rank}</span>
      <div className="grow">
        <div>
          <span className={`badge ${it.severity === "attention" ? "attention" : it.kind === "recommendation" ? "partial" : ""}`}>
            {it.severity === "attention" ? "Needs attention" : KIND_LABEL[it.kind]}
          </span>{" "}
          <strong>{it.title}</strong>
        </div>
        <div className="small">{it.detail}</div>
        {it.ask && <div className="small">Ask: “{it.ask}”</div>}
        {it.notes.map((n, i) => <div key={i} className="hint small">{n}</div>)}
        {it.evidence.filter((e) => e.quote).map((e, i) => (
          <div key={i} className="quote">
            “{e.quote}” — {e.document_id ? <a href={`/api/documents/${e.document_id}/file`} target="_blank" rel="noreferrer">{e.filename || `D${e.document_id}`}</a> : "report"}
          </div>
        ))}
        {it.kind === "recommendation" && (
          <div className="row" style={{ justifyContent: "flex-start", marginTop: 4 }}>
            <button className="small-btn primary" onClick={() => set("done")}>Done</button>
            <button className="small-btn" onClick={() => set("dismissed")}>Not relevant</button>
          </div>
        )}
      </div>
    </li>
  );
}

export function PackPanel({ pack, onRun, runningDetail }: { pack: PackInfo; onRun: () => void; runningDetail: string }) {
  const plan = pack.latest;
  const [copied, setCopied] = useState(false);
  const running = !!pack.running;
  return (
    <div className="card pack">
      <div className="card-head">
        <div>
          <h3>{pack.name}</h3>
          <div className="muted small">{pack.summary}</div>
        </div>
        <button className="primary" onClick={onRun} disabled={running}>
          {running ? "Building…" : plan ? "Rebuild" : "Build this plan"}
        </button>
      </div>
      <div className="muted small">
        Reads only: {pack.inputs.map((i) => <span key={i} className="badge">{i.replace("_", " ")}</span>)}
      </div>
      {running && (
        <div className="progress-card" style={{ margin: "12px 0" }}>
          <div className="spinner small" />
          <div className="small">
            {pack.running === "queued" ? "Waiting its turn…" : "Specialists are reading your record, then one lead advisor writes the plan"}
            {runningDetail && <span className="muted"> — {runningDetail}</span>}
          </div>
        </div>
      )}
      {!plan && !running && (
        <p className="muted small">
          Not built yet. It runs in the background (a few minutes on the local model): {pack.scenarios.length} specialist question{pack.scenarios.length === 1 ? "" : "s"}, then a lead
          write-up, then code checks it for treatment advice, invented figures and invented references.
        </p>
      )}
      {plan && (
        <>
          {plan.stale && <div className="alert urgent">Your record has changed since this was built. Rebuild it to include the latest information.</div>}
          {plan.used_fallback && (
            <div className="muted small">
              Assembled directly from your record without the AI writing step ({plan.flags[plan.flags.length - 1] ?? "the AI answer didn’t pass the checks"}). The facts are the same; it is just less polished.
            </div>
          )}
          <div className="plan-body"><ReactMarkdown>{plan.markdown}</ReactMarkdown></div>
          <div className="row wrap" style={{ justifyContent: "flex-start" }}>
            <button className="small-btn" onClick={() => { void navigator.clipboard?.writeText(plan.markdown); setCopied(true); setTimeout(() => setCopied(false), 2000); }}>{copied ? "Copied" : "Copy"}</button>
            <span className="muted small">Built {new Date(plan.created_at).toLocaleString()}</span>
          </div>
          {plan.notes.length > 0 && (
            <details>
              <summary className="small">How it was built — the specialists’ notes</summary>
              {plan.notes.map((n) => (
                <div key={n.id} className="small" style={{ margin: "8px 0" }}>
                  <b>{n.description.length > 140 ? `${n.description.slice(0, 140)}…` : n.description}</b>
                  <div className="muted" style={{ whiteSpace: "pre-wrap" }}>{n.note}</div>
                </div>
              ))}
              {plan.flags.length > 0 && <div className="muted small">Checks: {plan.flags.join(" · ")}</div>}
            </details>
          )}
        </>
      )}
    </div>
  );
}

export default function PlanTab({ version, onChanged }: { version: number; onChanged: () => void }) {
  const [items, setItems] = useState<DoNextItem[] | null>(null);
  const [packs, setPacks] = useState<PackInfo[]>([]);
  const [problems, setProblems] = useState<{ file: string; problem: string }[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [showAll, setShowAll] = useState(false);
  const [copied, setCopied] = useState(false);
  const [detail, setDetail] = useState("");
  const [err, setErr] = useState("");

  const loadItems = useCallback(() => api.nextSteps().then((r) => setItems(r.do_next)), []);
  const loadPacks = useCallback(
    () => api.advisors().then((r) => {
      setPacks(r.packs);
      setProblems(r.problems);
      setSelected((s) => s || r.packs.find((p) => p.id === "carecompanion.next_steps")?.id || r.packs[0]?.id || "");
    }),
    [],
  );
  useEffect(() => {
    void loadItems();
    void loadPacks();
  }, [loadItems, loadPacks, version]);

  const anyRunning = packs.some((p) => p.running);
  useEffect(() => {
    if (!anyRunning) return;
    const t = setInterval(() => {
      void loadPacks();
      api.jobsSummary().then((s) => setDetail(s.current?.kind === "plan" ? s.current.detail : "")).catch(() => undefined);
    }, 4000);
    return () => clearInterval(t);
  }, [anyRunning, loadPacks]);

  async function run(id: string) {
    setErr("");
    try {
      await api.runAdvisor(id);
      await loadPacks();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  if (!items) return <p className="muted">Loading…</p>;
  const shown = showAll ? items : items.slice(0, 8);
  const visitList = items
    .filter((i) => i.kind !== "recommendation" || !i.possibly_done)
    .slice(0, 12)
    .map((i, n) => `${n + 1}. ${i.ask || i.title}${i.kind === "recommendation" ? ` (${i.detail})` : ""}`)
    .join("\n");
  const pack = packs.find((p) => p.id === selected);

  return (
    <div>
      <h2 className="section" style={{ marginTop: 8 }}>Do next <span className="muted small">— ranked by urgency, with the reason for each</span></h2>
      {items.length === 0 && <p className="muted">Nothing to do yet. Upload reports and the plan fills in.</p>}
      <ol className="donext-list">
        {shown.map((it) => <DoNextCard key={it.id} it={it} onChanged={() => { void loadItems(); onChanged(); }} />)}
      </ol>
      <div className="row wrap" style={{ justifyContent: "flex-start" }}>
        {items.length > 8 && <button onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer" : `Show all ${items.length}`}</button>}
        {visitList && (
          <button onClick={() => { void navigator.clipboard?.writeText(visitList); setCopied(true); setTimeout(() => setCopied(false), 2500); }}>
            {copied ? "Copied" : "Copy as a visit question list"}
          </button>
        )}
      </div>

      <h2 className="section">Care plans <span className="muted small">— written by advisor packs from your record</span></h2>
      {err && <div className="alert urgent">{err}</div>}
      <div className="tabs small-tabs">
        {packs.map((p) => (
          <button key={p.id} className={selected === p.id ? "tab on" : "tab"} onClick={() => setSelected(p.id)}>
            {p.name} {p.running ? "⏳" : p.latest?.stale ? "•" : ""}
          </button>
        ))}
      </div>
      {pack && <PackPanel key={pack.id} pack={pack} onRun={() => run(pack.id)} runningDetail={detail} />}
      {problems.length > 0 && (
        <details className="small">
          <summary>{problems.length} custom pack file(s) could not be loaded</summary>
          <ul>{problems.map((p) => <li key={p.file}><b>{p.file}</b>: {p.problem}</li>)}</ul>
        </details>
      )}
      <p className="muted small">Packs are small YAML files. Put your own in the <code>advisors</code> folder inside the data folder to add or replace one.</p>
    </div>
  );
}
