import { useEffect, useState } from "react";
import { api, type DoNextItem } from "../api";
import DayTab from "./DayTab";
import ImprovementsTab from "./ImprovementsTab";
import StrategyTab from "./StrategyTab";

type Tab = "day" | "strategy" | "improve";
const SEV_LABEL: Record<string, string> = { attention: "Needs attention", advice: "Advisor advised", question: "To confirm", info: "Note", check: "Missing check" };

function FocusStrip({ version, onOpenNext }: { version: number; onOpenNext: () => void }) {
  const [items, setItems] = useState<DoNextItem[] | null>(null);
  useEffect(() => { void api.nextSteps().then((r) => setItems(r.do_next)).catch(() => setItems([])); }, [version]);
  if (!items || items.length === 0) return null;
  const top = items.filter((i) => !i.possibly_done).slice(0, 3);
  return (
    <div className="card focus-card">
      <div className="card-head">
        <h3>🧭 Focus now <span className="muted small">— the most important next steps</span></h3>
        <button className="small-btn" onClick={onOpenNext}>All {items.length} →</button>
      </div>
      <ol className="focus-list">
        {top.map((it) => (
          <li key={it.id}>
            <span className={`badge ${it.severity === "attention" ? "attention" : it.kind === "recommendation" ? "partial" : ""}`}>{SEV_LABEL[it.severity] ?? it.kind}</span>
            <strong>{it.title.length > 110 ? `${it.title.slice(0, 110)}…` : it.title}</strong>
          </li>
        ))}
      </ol>
    </div>
  );
}

export default function Today({ version, onOpenNext }: { version: number; onOpenNext: () => void }) {
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem("cc-today-tab") as Tab) || "day");
  const [bump, setBump] = useState(0);
  const choose = (t: Tab) => { setTab(t); localStorage.setItem("cc-today-tab", t); };
  const date = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });

  return (
    <section className="page">
      <header className="page-head">
        <h1>Today <span className="muted" style={{ fontSize: "1rem", fontWeight: 400 }}>· {date}</span></h1>
        <p>Your next steps, medicines, food, routine and mind practice in one place, with a one-minute check-in so you can see what is helping.</p>
      </header>
      <FocusStrip version={version + bump} onOpenNext={onOpenNext} />
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "day"} className={tab === "day" ? "tab on" : "tab"} onClick={() => choose("day")}>Today</button>
        <button role="tab" aria-selected={tab === "strategy"} className={tab === "strategy" ? "tab on" : "tab"} onClick={() => choose("strategy")}>Strategy &amp; ideas</button>
        <button role="tab" aria-selected={tab === "improve"} className={tab === "improve" ? "tab on" : "tab"} onClick={() => choose("improve")}>Improvements</button>
      </div>
      {tab === "day" && <DayTab onOpenStrategy={() => choose("strategy")} />}
      {tab === "strategy" && <StrategyTab onChanged={() => setBump((b) => b + 1)} />}
      {tab === "improve" && <ImprovementsTab version={version + bump} />}
    </section>
  );
}
