import { useCallback, useEffect, useState } from "react";
import { workspaceUrl } from "../api";

type Source = {
  id: number; title: string; kind: string; text: string; source_url: string; as_of: string;
};
type CitedPoint = { source_id: number; quote: string; interpretation: string };
type Brief = {
  id: number; question: string; status: string; error: string; sources: Source[]; fingerprint: string; created_at: string;
  result: {
    model?: string; disclaimer?: string; validation?: string; validation_repairs?: number;
    reported_requirements?: CitedPoint[]; reported_concerns?: CitedPoint[]; evidence_notes?: CitedPoint[];
    unanswered_questions?: string[]; desk_research_tasks?: string[];
  };
};
type ResearchCycle = {
  job_id: number; cycle: number; question: string; status: string; error: string;
  result: {
    brief?: Brief["result"]; detail?: string; validation?: string;
    progress?: { additional_cited_passages: number };
    critique?: {
      model: string;
      checks: { point_id: string; verdict: string; reason: string }[];
      gaps: { question: string; source_ids: number[]; answerability: string }[];
      next_question: string;
    };
  };
};
type ResearchLoop = {
  id: number; question: string; sources: Source[]; fingerprint: string; max_cycles: number;
  status: string; stop_reason: string; closed: boolean; cycles: ResearchCycle[];
};
type Notebook = { sources: Source[]; briefs: Brief[]; loops: ResearchLoop[]; disclaimer: string };

async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(workspaceUrl(path.startsWith("/api/") ? path : `/api/research/notebook${path}`), body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  } : undefined);
  if (!response.ok) {
    const text = await response.text();
    let detail = `Request failed (${response.status}): ${text}`;
    try {
      const parsed = JSON.parse(text);
      detail = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail ?? parsed);
    } catch { /* Non-JSON server errors are displayed verbatim. */ }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

function localDate(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

const QUESTIONS = [
  "Which requirements are specific to the study, which statements are tentative concerns rather than confirmed findings, and what remains unanswered?",
  "What do these sources support about the research platform, and what evidence is missing to compare it with sequencing-based computational research?",
  "What can I investigate through reading and software only, and which questions still require qualified clinical or laboratory assessment?",
];
const SECTIONS = [
  ["reported_requirements", "Reported study requirements"],
  ["reported_concerns", "Reported concerns - not confirmed patient findings"],
  ["evidence_notes", "Source-grounded evidence notes"],
] as const;

function briefText(brief: Brief): string {
  const lines = [`Local research brief #${brief.id}`, brief.question, `Model: ${brief.result.model}`, ""];
  for (const [key, title] of SECTIONS) {
    lines.push(title);
    for (const point of brief.result[key] ?? []) {
      const source = brief.sources.find((item) => item.id === point.source_id);
      lines.push(`- ${point.interpretation}\n  Source [S${point.source_id}] ${source?.title}: "${point.quote}"`);
    }
  }
  lines.push("Unanswered questions", ...(brief.result.unanswered_questions ?? []), "Desk-research tasks", ...(brief.result.desk_research_tasks ?? []));
  lines.push("", brief.result.validation ?? "", brief.result.disclaimer ?? "");
  return lines.join("\n\n");
}

function BriefFindings({ result, sources }: { result: Brief["result"]; sources: Source[] }) {
  return <>
    {SECTIONS.map(([key, title]) => <div key={key}>
      <h4>{title}</h4>
      {!result[key]?.length && <p className="small muted">No supported point extracted from the selected excerpts.</p>}
      {result[key]?.map((point, index) => {
        const original = sources.find((item) => item.id === point.source_id);
        return <div key={index}>
          <p>{point.interpretation}</p>
          <blockquote className="quote">{point.quote}</blockquote>
          <p className="small muted">[S{point.source_id}] {original?.title} · {original?.kind} · {original?.as_of} · user-supplied, unverified</p>
        </div>;
      })}
    </div>)}
    <h4>Unanswered questions</h4><ul>{result.unanswered_questions?.map((text, i) => <li key={i}>{text}</li>)}</ul>
    <h4>Desk-research tasks, not clinical or laboratory actions</h4><ul>{result.desk_research_tasks?.map((text, i) => <li key={i}>{text}</li>)}</ul>
    <p className="small muted">{result.validation}</p>
    <p className="small">{result.disclaimer}</p>
  </>;
}

export default function ResearchNotebook() {
  const [data, setData] = useState<Notebook | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [question, setQuestion] = useState(QUESTIONS[0]);
  const [source, setSource] = useState({
    title: "", kind: "correspondence", text: "", source_url: "", as_of: localDate(),
  });
  const load = useCallback(async () => { setData(await request<Notebook>("")); }, []);
  useEffect(() => { void load().catch((e: Error) => setError(e.message)); }, [load]);
  const pending = (data?.briefs.some((brief) => ["queued", "running"].includes(brief.status)) ?? false)
    || (data?.loops.some((loop) => loop.cycles.some((cycle) => ["queued", "running"].includes(cycle.status))) ?? false);
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => { void load().catch((e: Error) => setError(e.message)); }, 4000);
    return () => clearInterval(timer);
  }, [pending, load]);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(""); setNotice("");
    try { await fn(); } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  return <section className="card">
    <div className="card-head"><h2>Private source research notebook</h2><span className="badge partial">local AI · desk research only</span></div>
    <p>Read correspondence and publications, separate requirements from concerns, and prepare evidence gaps and questions. No sequencing data or completed pipeline run is needed.</p>
    <div className="hint">
      <strong>What this can and cannot replace</strong>
      <ul className="small">
        <li>This notebook helps organise and question sources. It cannot determine surgical fitness, tissue viability, trial eligibility or personal benefit.</li>
        <li>A tissue-quality concern is not a confirmed pathology finding. An omitted histologic variant is unresolved, not automatically eligible or excluded.</li>
        <li>The Ranked targets pipeline is a sequencing-based neoantigen computation, not a TMV vaccine simulation. It cannot bypass a trial's collection-site or laboratory requirements.</li>
        <li>No vaccine manufacture, tissue handling, dosing or administration instructions are generated. Do not delay oncology care for software research.</li>
      </ul>
    </div>
    <p className="small muted">Only the excerpts and question you select are sent to the configured loopback local model. No web search, URL fetch or automatic access to the rest of the patient record. Sources remain user-supplied and unverified.</p>
    {error && <div className="alert urgent" role="alert">{error}</div>}
    {notice && <div className="alert ok" role="status">{notice}</div>}
    {!data && <button disabled={busy} onClick={() => void run(load)}>Retry loading notebook</button>}
    <details>
      <summary><strong>Add correspondence or a publication excerpt</strong></summary>
      <p className="small muted">Paste only the relevant passage you are entitled to use. Remove email addresses, phone numbers, signatures and unnecessary identifiers. Saving a URL records a citation only; it is not opened.</p>
      <form onSubmit={(event) => {
        event.preventDefault();
        void run(async () => {
          const saved = await request<Source>("/sources", source);
          setSelected((ids) => ids.length < 8 ? [...ids, saved.id] : ids);
          setSource({ title: "", kind: "correspondence", text: "", source_url: "", as_of: localDate() });
          await load(); setNotice("Source saved locally. It is not independently verified.");
        });
      }}>
        <label>Research source title<input required maxLength={200} value={source.title} onChange={(e) => setSource({ ...source, title: e.target.value })} /></label>
        <div className="form-grid">
          <label>Source type<select value={source.kind} onChange={(e) => setSource({ ...source, kind: e.target.value })}>
            <option value="correspondence">Correspondence (reported, not a published result)</option>
            <option value="publication">Publication excerpt (check original)</option>
            <option value="registry">Trial registry excerpt</option>
            <option value="personal_note">Personal note (not medical evidence)</option>
          </select></label>
          <label>Source as-of date<input required type="date" value={source.as_of} onChange={(e) => setSource({ ...source, as_of: e.target.value })} /></label>
        </div>
        <label>Optional public citation URL<input type="url" maxLength={2000} value={source.source_url} onChange={(e) => setSource({ ...source, source_url: e.target.value })} /></label>
        <label>Relevant source excerpt<textarea required minLength={20} maxLength={12000} rows={6} value={source.text} onChange={(e) => setSource({ ...source, text: e.target.value })} /></label>
        <button disabled={busy} className="primary">Save local source</button>
      </form>
    </details>
    {data && <>
      <h3>Select sources for this question</h3>
      {!data.sources.length && <p>No notebook sources yet. Add the relevant part of a reply or paper above.</p>}
      {data.sources.map((item) => <div key={item.id}>
        <label className="check"><input type="checkbox" checked={selected.includes(item.id)} disabled={!selected.includes(item.id) && selected.length >= 8}
          onChange={(e) => setSelected(e.target.checked ? [...selected, item.id] : selected.filter((id) => id !== item.id))} />
          [S{item.id}] {item.title} · {item.kind.replaceAll("_", " ")} · {item.as_of} · unverified
        </label>
        <details><summary className="small">Read saved excerpt S{item.id}</summary><pre className="draft">{item.text}</pre></details>
      </div>)}
      <p className="small muted">Select 1-8 sources; maximum combined excerpt size 36,000 characters. Sources are append-only; add a dated correction rather than silently editing a brief's evidence.</p>
      <label>Research question<textarea rows={3} minLength={10} maxLength={2000} value={question} onChange={(e) => setQuestion(e.target.value)} /></label>
      <div className="row wrap">{QUESTIONS.map((text, i) => <button key={text} onClick={() => setQuestion(text)}>{["Study requirements & uncertainties", "Platform comparison evidence gaps", "What can I research locally?"][i]}</button>)}</div>
      <button className="primary" disabled={busy || !selected.length || question.trim().length < 10} onClick={() => void run(async () => {
        await request<Brief>("/briefs", { question, source_ids: selected }); await load();
        setNotice("Local AI brief queued. Only the selected excerpts were snapshotted. This may take several minutes.");
      })}>Build source-grounded brief with local AI</button>
      <div className="hint">
        <h3>Reviewed research loop</h3>
        <p>Selected sources → cited brief → critical reading → evidence gaps → your approval of the next question.</p>
        <p className="small">Up to three cycles, with approval after each. Only the sources selected above are frozen and used. No web access, computational runs, treatment changes, self-modifying code or model training. Generated text never becomes a source.</p>
        <p className="small">The critic is a second pass by the same local model, not an independent expert. It can miss mistakes. The loop stops on flagged interpretations, repeated questions, no additional cited passages or a need for new sources. These are reading checks, not medical progress scores.</p>
        <button className="primary" disabled={busy || !selected.length || question.trim().length < 10} onClick={() => void run(async () => {
          await request<ResearchLoop>("/loops", { question, source_ids: selected }); await load();
          setNotice("Research loop started. Only cycle one is authorised; another cycle requires your approval.");
        })}>Start reviewed research loop</button>
      </div>
      <h3>Saved research loops</h3>
      <p className="small muted">Latest ten loops. Each retains its original sources, validated cycles, model identities and stop reason. Additional cycles do not create independent evidence.</p>
      {!data.loops.length && <p>No reviewed research loops yet.</p>}
      {data.loops.map((loop) => {
        const latest = loop.cycles.at(-1);
        return <article className="card" key={loop.id}>
          <h4>Research loop #{loop.id} · {loop.status.replaceAll("_", " ")}</h4>
          <p>{loop.question}</p>
          <p className="small">Cycles: {loop.cycles.length}/{loop.max_cycles} · source fingerprint <code>{loop.fingerprint.slice(0, 16)}</code></p>
          {loop.stop_reason && <p className="hint">{loop.stop_reason}</p>}
          {loop.closed && <p>Loop closed. A running cycle may finish, but no further cycle can be approved.</p>}
          {loop.cycles.map((cycle) => <details key={cycle.job_id} open={cycle.job_id === latest?.job_id}>
            <summary><strong>Cycle {cycle.cycle} · {cycle.status}</strong></summary>
            <p>{cycle.question}</p>
            {cycle.status === "skipped" && <p>{cycle.result.detail}</p>}
            {["queued", "running"].includes(cycle.status) && <p role="status">{cycle.result.detail ?? "Waiting for the local model."}</p>}
            {cycle.status === "failed" && <div className="alert urgent" role="alert">
              <p>{cycle.error}</p>
              <p>No completed cycle or next-step approval is available. The frozen inputs are retained.</p>
              {!loop.closed && <button disabled={busy} onClick={() => void run(async () => {
                await request(`/api/jobs/${cycle.job_id}/retry`, {}); await load();
              })}>Retry failed cycle {cycle.cycle}</button>}
            </div>}
            {cycle.status === "done" && cycle.result.brief && <>
              <p className="small">Brief model: {cycle.result.brief.model} · critique model: {cycle.result.critique?.model}</p>
              <p className="small">Additional cited passages: {cycle.result.progress?.additional_cited_passages}. This is source coverage, not new scientific evidence or patient benefit.</p>
              <BriefFindings result={cycle.result.brief} sources={loop.sources} />
              <h4>Model critique — review against originals</h4>
              <ul>{cycle.result.critique?.checks.map((check) => <li key={check.point_id}><strong>{check.point_id} · {check.verdict}</strong>: {check.reason}</li>)}</ul>
              <h4>Evidence gaps</h4>
              <ul>{cycle.result.critique?.gaps.map((gap, i) => <li key={i}>{gap.question} <span className="muted small">[{gap.source_ids.map((id) => `S${id}`).join(", ")}] · {gap.answerability.replaceAll("_", " ")}</span></li>)}</ul>
              <p className="small muted">{cycle.result.validation}</p>
            </>}
          </details>)}
          {loop.status === "awaiting_approval" && latest?.result.critique && <div className="hint">
            <strong>Proposed next question</strong>
            <p>{latest.result.critique.next_question}</p>
            <p className="small">Review the findings, critique and frozen sources first. Approval authorises one more local reading cycle, not a medical action.</p>
            <button disabled={busy} onClick={() => void run(async () => {
              await request(`/loops/${loop.id}/approve`, { previous_job_id: latest.job_id }); await load();
              setNotice(`One further cycle approved for loop #${loop.id}.`);
            })}>Approve next question and run one cycle</button>
          </div>}
          {!loop.closed && <button disabled={busy} onClick={() => void run(async () => {
            await request(`/loops/${loop.id}/close`, {}); await load();
          })}>Close loop #{loop.id}</button>}
          <details><summary>Frozen sources for loop #{loop.id}</summary>
            {loop.sources.map((item) => <div key={item.id}><strong>[S{item.id}] {item.title}</strong><p className="small">{item.kind} · {item.as_of} · unverified</p><pre className="draft">{item.text}</pre></div>)}
          </details>
        </article>;
      })}
      <h3>Saved research briefs</h3>
      <p className="small muted">The latest 20 briefs are shown. Each retains the question, selected source versions and model output. A citation match does not prove that the interpretation is correct.</p>
      {!data.briefs.length && <p>No source-grounded briefs yet.</p>}
      {data.briefs.map((brief) => <article key={brief.id} className="card">
        <h4>Research brief #{brief.id} · {brief.status}</h4>
        <p>{brief.question}</p>
        {["queued", "running"].includes(brief.status) && <p role="status">Local model {brief.status}; no treatment or pipeline settings are changed.</p>}
        {brief.status === "failed" && <div className="alert urgent" role="alert">
          {brief.error}
          <p className="small">This brief did not pass generation or validation. Your frozen sources and question are still saved; this is not a finding about the patient.</p>
          <button disabled={busy} onClick={() => void run(async () => {
            await request(`/api/jobs/${brief.id}/retry`, {});
            await load(); setNotice(`Brief #${brief.id} queued again using its original question and frozen sources.`);
          })}>Retry brief #{brief.id} with saved sources</button>
        </div>}
        {brief.status === "done" && <>
          <p className="small">Model: {brief.result.model} · saved {brief.created_at}</p>
          {!!brief.result.validation_repairs && <p className="small muted">The local model corrected an initial draft after validation feedback; the corrected draft passed all checks before saving.</p>}
          <BriefFindings result={brief.result} sources={brief.sources} />
          <button disabled={busy} onClick={() => void run(async () => {
            await navigator.clipboard.writeText(briefText(brief)); setNotice("Brief copied for your review. Nothing was sent automatically.");
          })}>Copy brief for review before sharing</button>
        </>}
        <details><summary>Frozen sources used in brief #{brief.id}</summary>
          {brief.sources.map((item) => <div key={item.id}><strong>[S{item.id}] {item.title}</strong><p className="small">{item.kind} · {item.as_of} {item.source_url}</p><pre className="draft">{item.text}</pre></div>)}
        </details>
      </article>)}
      <p className="small muted">{data.disclaimer}</p>
    </>}
  </section>;
}
