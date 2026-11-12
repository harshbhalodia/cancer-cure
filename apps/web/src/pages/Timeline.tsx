import { useEffect, useState } from "react";
import { api, type TimelineEvent } from "../api";

const ICON: Record<string, string> = { document: "📄", case: "🗂️", alert: "⚠️", scan: "📈", record: "✅" };

export default function Timeline({ version }: { version: number }) {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  useEffect(() => {
    api.timeline().then(setEvents).catch(() => undefined);
  }, [version]);

  const days = new Map<string, TimelineEvent[]>();
  for (const e of events) {
    const day = new Date(e.ts).toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" });
    days.set(day, [...(days.get(day) ?? []), e]);
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>Timeline</h1>
        <p>Every upload, case-file change and safety alert, in order — the story of the journey so far.</p>
      </header>
      {events.length === 0 && <p className="muted">Nothing yet. Upload a report to begin.</p>}
      {[...days.entries()].map(([day, list]) => (
        <div key={day} className="day">
          <h3>{day}</h3>
          <ul>
            {list.map((e) => (
              <li key={e.id} className={`ev ${e.kind}`}>
                <span aria-hidden>{ICON[e.kind] ?? "•"}</span>
                <div>
                  <strong>{e.title}</strong>
                  {e.detail && <div className="muted">{e.detail}</div>}
                </div>
                <time>{new Date(e.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
