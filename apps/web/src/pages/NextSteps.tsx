import { useCallback, useEffect, useState } from "react";
import { api, type Decision, type Readiness, type Requirement } from "../api";
import PlanTab from "./PlanTab";
import RecsTab from "./RecsTab";

const STATUS_TEXT: Record<string, string> = { ready: "Ready", partial: "Partly ready", blocked: "Blocked" };

function RecordRow({ r, onSaved }: { r: Requirement; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState("present");
  const [value, setValue] = useState("");
  const [err, setErr] = useState("");

  async function save() {
    setErr("");
    try {
      await api.putFact(r.key, { status, value });
      setOpen(false);
      setValue("");
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <li className={r.met ? "rec met" : "rec"}>
      <div className="rec-head">
        <span className="tick" aria-hidden>{r.met ? "✓" : r.status === "not_done" ? "✗" : "?"}</span>
        <div className="grow">
          <strong>{r.label}</strong>
          <div className="muted small">
            {r.met ? `${r.status === "negative" ? "Tested — negative/none. " : ""}${r.value || "Recorded"}` : r.status === "not_done" ? "Documented as not done" : "Not in the record yet"}
            {r.note && ` · ${r.note}`}
          </div>
        </div>
        {r.source === "fact" && (
          <button className="small-btn" onClick={() => api.deleteFact(r.key).then(onSaved)}>Reset</button>
        )}
        {r.source !== "derived" && <button className="small-btn" onClick={() => setOpen(!open)}>{r.met ? "Edit" : "Add result"}</button>}
      </div>
      {!r.met && <div className="muted small why">{r.why}</div>}
      {open && (
        <div className="inline-form">
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
            <option value="present">Has a result</option>
            <option value="negative">Tested — negative / none</option>
            <option value="not_done">Not done</option>
          </select>
          {status === "present" && <input value={value} placeholder="Result, e.g. CPS 20" onChange={(e) => setValue(e.target.value)} />}
          <button className="primary" onClick={save}>Save</button>
          {err && <span className="muted">{err}</span>}
        </div>
      )}
    </li>
  );
}

function DecisionCard({ d }: { d: Decision }) {
  return (
    <div className={`decision ${d.status}`}>
      <div className="decision-head">
        <strong>{d.title}</strong>
        <span className={`badge ${d.status}`}>{STATUS_TEXT[d.status]}</span>
      </div>
      <div className="muted small">{d.question}</div>
      {d.blocked_by.length > 0 && <div className="small"><b>Can’t start without:</b> {d.blocked_by.join(", ")}</div>}
      {d.unmet.length > 0 && d.blocked_by.length === 0 && <div className="small"><b>Still missing:</b> {d.unmet.map((u) => u.label).join(", ")}</div>}
      {d.status === "ready" && <div className="small">Everything this step normally needs is on file.</div>}
    </div>
  );
}

function ChecksTab({ version }: { version: number }) {
  const [data, setData] = useState<Readiness | null>(null);
  const load = useCallback(() => api.readiness().then(setData), []);
  useEffect(() => {
    void load();
  }, [load, version]);
  if (!data) return <p className="muted">Loading…</p>;

  const groups = [...new Set(data.requirements.map((r) => r.group))];
  const missing = data.requirements.filter((r) => !r.met).length;

  return (
    <div>
      <p className="muted">
        Whether the record has what each step normally needs.
        {data.profile === "oral_cavity" && " Tailored to oral-cavity (tongue/mouth) cancer."} Add results here and the plan updates.
      </p>
      <h2 className="section">Where things stand</h2>
      <div className="decisions">
        {data.decisions.map((d) => <DecisionCard key={d.id} d={d} />)}
      </div>

      <h2 className="section">Record checklist <span className="muted small">({missing} still to fill)</span></h2>
      {groups.map((g) => (
        <div key={g}>
          <h3 className="group">{g}</h3>
          <ul className="reclist">
            {data.requirements.filter((r) => r.group === g).map((r) => <RecordRow key={r.key} r={r} onSaved={load} />)}
          </ul>
        </div>
      ))}
      <p className="muted small">The checklist is a starting list from general oncology practice. Ask the oncologist which items matter for this case.</p>
    </div>
  );
}

type Tab = "plan" | "recs" | "checks";

export default function NextSteps({ version }: { version: number }) {
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem("cc-next-tab") as Tab) || "plan");
  const [openRecs, setOpenRecs] = useState<number | null>(null);
  const [bump, setBump] = useState(0);
  const choose = (t: Tab) => {
    setTab(t);
    localStorage.setItem("cc-next-tab", t);
  };
  useEffect(() => {
    api.recommendations().then((r) => setOpenRecs(r.filter((x) => x.status === "open").length)).catch(() => undefined);
  }, [version, bump, tab]);

  return (
    <section className="page">
      <header className="page-head">
        <h1>Next steps</h1>
        <p>What to do next, built from what your advisors recommended, what the scans and reports show, and what is still missing. Always questions and checks to confirm with the care team, never treatment advice.</p>
      </header>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "plan"} className={tab === "plan" ? "tab on" : "tab"} onClick={() => choose("plan")}>Plan</button>
        <button role="tab" aria-selected={tab === "recs"} className={tab === "recs" ? "tab on" : "tab"} onClick={() => choose("recs")}>
          Advisors’ recommendations {openRecs ? <span className="nav-badge neutral">{openRecs}</span> : null}
        </button>
        <button role="tab" aria-selected={tab === "checks"} className={tab === "checks" ? "tab on" : "tab"} onClick={() => choose("checks")}>Checks</button>
      </div>
      {tab === "plan" && <PlanTab version={version + bump} onChanged={() => setBump((b) => b + 1)} />}
      {tab === "recs" && <RecsTab version={version} onChanged={() => setBump((b) => b + 1)} />}
      {tab === "checks" && <ChecksTab version={version} />}
    </section>
  );
}
