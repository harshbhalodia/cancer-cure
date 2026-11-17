import { Fragment, useCallback, useEffect, useState } from "react";
import { api, workspaceUrl, type PackInfo, type ResearchAIJob, type VaxCandidate, type VaxRun, type Vaccine as VaccineData } from "../api";
import { PackPanel } from "./PlanTab";
import { CohortTab, OptionsTab } from "./Cohort";
import StartHere from "./StartHere";
import TrialsTab from "./Trials";

type Tab = "fast" | "trials" | "options" | "cohort" | "start" | "data" | "candidates" | "review";
const PACK_ID = "carecompanion.vaccine_board";
const TIER_HELP: Record<string, string> = { A: "strongly predicted, every supporting measurement present", B: "one of those is missing", C: "weaker and incomplete" };

function Funnel({ run }: { run: VaxRun }) {
  const max = Math.max(...run.stages.map((s) => s.in), 1);
  return (
    <div className="funnel">
      {run.stages.map((s) => (
        <div key={s.name} className="funnel-row">
          <span className="funnel-name">{s.name}</span>
          <div className="meter"><div style={{ width: `${(s.out / max) * 100}%` }} /></div>
          <span className="small">{s.in} → <b>{s.out}</b></span>
        </div>
      ))}
    </div>
  );
}

function CandidateTable({ items }: { items: VaxCandidate[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (items.length === 0) return <p className="muted">No candidate passed all stages.</p>;
  return (
    <div className="vtable-wrap">
      <table className="vtable">
        <thead><tr><th>#</th><th>Mutation</th><th>Peptide</th><th>HLA</th><th>Affinity nM</th><th>Presented (pct)</th><th>VAF</th><th>TPM</th><th>Tier</th><th>Score</th></tr></thead>
        <tbody>
          {items.map((c, i) => (
            <Fragment key={c.id}>
              <tr onClick={() => setOpen(open === c.id ? null : c.id)} className="clickable">
                <td>{i + 1}</td>
                <td><b>{c.gene}</b> {c.change}{c.hotspot ? " ★" : ""}</td>
                <td><code>{c.peptide}</code><div className="muted small">wt <code>{c.wt_peptide}</code></div></td>
                <td>{c.allele.replace("HLA-", "")}</td>
                <td>{c.affinity_nM}</td>
                <td>{c.presentation_pct}</td>
                <td>{c.vaf ?? "—"}</td>
                <td>{c.tpm ?? "—"}</td>
                <td><span className={`badge tier-${c.tier}`} title={TIER_HELP[c.tier]}>{c.tier}</span></td>
                <td><b>{c.score}</b></td>
              </tr>
              {open === c.id && (
                <tr className="vdetail">
                  <td colSpan={10}>
                    <div className="small"><b>How the score is made:</b> {Object.entries(c.components).map(([k, v]) => `${k} ${(v * 100).toFixed(0)}%`).join(" · ")}{c.hotspot ? " · +5 recurrent hotspot (curated list, verify)" : ""}</div>
                    {c.flags.length > 0 ? <ul className="small">{c.flags.map((f, j) => <li key={j}>⚠ {f}</li>)}</ul> : <div className="small muted">No caveats recorded.</div>}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Vaccine() {
  const [data, setData] = useState<VaccineData | null>(null);
  const [tab, setTab] = useState<Tab>("fast");
  const [dataset, setDataset] = useState<"patient" | "synthetic">("patient");
  const [varText, setVarText] = useState("");
  const [hlaText, setHlaText] = useState("");
  const [msg, setMsg] = useState("");
  const [msgOk, setMsgOk] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const [pack, setPack] = useState<PackInfo | null>(null);
  const [verify, setVerify] = useState("");
  const [board, setBoard] = useState(false);
  const [selectedRun, setSelectedRun] = useState<VaxRun | null>(null);
  const [hypothesis, setHypothesis] = useState("");
  const [assistant, setAssistant] = useState<ResearchAIJob | null>(null);
  const activeRun = selectedRun?.dataset === dataset ? selectedRun : data?.latest[dataset];
  const runId = activeRun?.id;
  const [experimentParams, setExperimentParams] = useState({ min_vaf: "0.10", min_tpm: "1", max_pres_pct: "2", n_select: "12" });
  const runExperiment = async () => {
    const params = Object.fromEntries(Object.entries(experimentParams).map(([key, value]) => [key, Number(value)]));
    if (Object.values(experimentParams).some((v) => !v.trim()) || Object.values(params).some((v) => !Number.isFinite(v))) {
      throw new Error("Enter a finite value for each experiment parameter.");
    }
    if (!hypothesis.trim()) throw new Error("Enter the computational question this scenario tests.");
    await api.vaxRun(dataset, { ...activeRun?.params, ...params }, hypothesis.trim());
    setSelectedRun(null);
    say("Scenario queued. A new run and immutable Research snapshot will be saved when it completes.", true);
  };
  useEffect(() => {
    let active = true;
    setAssistant(null);
    if (!runId) return;
    void api.researchHypotheses(runId).then((r) => { if (active) setAssistant(r.job); }).catch((e: Error) => { if (active) setMsg(e.message); });
    return () => { active = false; };
  }, [runId]);
  useEffect(() => {
    if (!runId || !assistant || !["queued", "running"].includes(assistant.status)) return;
    let active = true;
    const timer = setInterval(() => {
      void api.researchHypotheses(runId).then((r) => { if (active) setAssistant(r.job); }).catch((e: Error) => { if (active) setMsg(e.message); });
    }, 4000);
    return () => { active = false; clearInterval(timer); };
  }, [runId, assistant?.status]);

  const load = useCallback(() => api.vaccine().then(setData).catch((e: Error) => { setMsg(e.message); setMsgOk(false); }), []);
  const loadPack = useCallback(() => api.advisors().then((r) => setPack(r.packs.find((p) => p.id === PACK_ID) ?? null)), []);
  useEffect(() => { void load(); void loadPack(); }, [load, loadPack]);
  const busy = !!data?.jobs.some((j) => j.status === "queued" || j.status === "running") || !!pack?.running;
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => { void load(); void loadPack(); }, 4000);
    return () => clearInterval(t);
  }, [busy, load, loadPack]);
  const choose = (t: Tab) => { setTab(t); localStorage.setItem("cc-vax-tab", t); };
  const say = (m: string, ok = false) => { setMsg(m); setMsgOk(ok); };
  const guard = async (fn: () => Promise<unknown>) => { try { await fn(); await load(); } catch (e) { say((e as Error).message); } };

  async function loadDemo() {
    setDemoBusy(true);
    try {
      const r = await api.vaxSynthetic();
      setDataset("synthetic");
      choose("candidates");
      try {
        await api.vaxRun("synthetic");
        say(`Synthetic demo loaded (${r.variants} fake mutations, ${r.hla.length} HLA alleles). The pipeline is running; results appear below in a few seconds.`, true);
      } catch (e) {
        say(`Synthetic demo loaded (${r.variants} fake mutations). ${(e as Error).message}`, true);
      }
      await load();
    } catch (e) {
      say(`Could not load the demo: ${(e as Error).message}`);
    } finally {
      setDemoBusy(false);
    }
  }

  if (!data) return <section className="page">{msg ? <div className="alert urgent" role="alert">{msg}<button onClick={() => void load()}>Retry</button></div> : <p className="muted">Loading…</p>}</section>;
  const mine = data[dataset];
  const run = activeRun;
  const failed = data.jobs.find((j) => j.status === "failed");
  const running = data.jobs.find((j) => j.status === "queued" || j.status === "running");

  return (
    <section className="page">
      <header className="page-head">
        <h1>Vaccine &amp; next-step research</h1>
        <p>Start with “Start here”: three things you can do today. The other tabs are for when test results arrive.</p>
      </header>
      <div className="tabs" role="tablist">
        {([["fast", "Start here"], ["trials", "Clinical trials"], ["options", "Treatment options"], ["cohort", "What to expect (simulation)"]] as [Tab, string][]).map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "tab on" : "tab"} onClick={() => choose(id)}>{label}</button>
        ))}
        <span className="muted small" style={{ alignSelf: "center", padding: "0 8px" }}>When results arrive:</span>
        {([["start", "What is needed"], ["data", "Add results"], ["candidates", "Ranked targets"], ["review", "Checks"]] as [Tab, string][]).map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "tab on" : "tab"} onClick={() => choose(id)}>{label}</button>
        ))}
      </div>
      <div className="card vax-warn">
        <b>Please read:</b> a personalised cancer vaccine can only be made and given by a qualified team inside an approved clinical trial or regulatory pathway. This tool cannot make one, and nothing here is a protocol for making, buying or taking a vaccine. Predictions show which peptides <i>may be presented</i>; they do not show that a vaccine would work.
      </div>
      {msg && <div className={msgOk ? "alert ok" : "alert urgent"} onClick={() => setMsg("")}>{msg}</div>}

      {tab === "fast" && <StartHere onNext={choose} />}
      {tab === "options" && <OptionsTab />}
      {tab === "trials" && <TrialsTab />}
      {tab === "cohort" && <CohortTab />}

      {tab === "start" && (
        <div>
          <div className="card">
            <div className="card-head"><h3>What the pipeline needs from the patient</h3>
              <span className={`badge ${data.readiness?.status === "ready" ? "ready" : data.readiness?.status === "blocked" ? "attention" : "partial"}`}>{data.readiness?.status ?? "unknown"}</span></div>
            <ul className="plain">
              {data.asks.map((a) => (
                <li key={a.key} className="ask-row">
                  <span aria-hidden>{a.met ? "✅" : "⬜"}</span>
                  <div className="grow"><b>{a.label}</b> <span className="muted small">— {a.status.replace("_", " ")}</span>
                    <div className="small muted">{a.why}</div>
                    {!a.met && a.ask && <div className="small">Ask: “{a.ask}”</div>}
                  </div>
                </li>
              ))}
            </ul>
            <p className="muted small" style={{ marginBottom: 0 }}>These support this computational neoantigen pipeline, not every vaccine approach. Ask the oncologist and trial centre which tests are appropriate; TMV/tumour-derived trials have separate tissue requirements.</p>
          </div>
          <div className="card">
            <div className="card-head"><h3>The realistic path</h3></div>
            <ol className="small" style={{ paddingLeft: 20 }}>
              <li>Get the sequencing and HLA typing done (above), through the oncologist or a molecular tumour board.</li>
              <li>Load the mutation list and HLA type in the <b>Data</b> tab. The pipeline selects and ranks candidate peptides with a real binding predictor.</li>
              <li>Take the <b>dossier</b> (Review &amp; evals) to the tumour board or a trial centre and ask whether the patient is eligible for an individualised neoantigen vaccine trial.</li>
              <li>Manufacturing, safety testing and administration happen only under that trial or pathway.</li>
            </ol>
          </div>
          <div className="card">
            <div className="card-head"><h3>Try it first, without any patient data</h3></div>
            <p className="muted small">Load a clearly labelled <b>synthetic</b> tumour (fake genes, planted good and bad mutations with known answers). One click loads it, runs the whole pipeline with the real predictor and shows the results. It is never mixed with the patient’s data.</p>
            <div className="row wrap" style={{ justifyContent: "flex-start" }}>
              <button className="primary" disabled={demoBusy || !!running} onClick={loadDemo}>{demoBusy ? "Loading…" : data.synthetic.variants > 0 ? "Run the synthetic demo again" : "Load the synthetic demo and run it"}</button>
              {data.synthetic.variants > 0 && <span className="small">✅ {data.synthetic.variants} synthetic mutations loaded{data.latest.synthetic ? " · results ready" : ""}. <button className="link" onClick={() => { setDataset("synthetic"); choose("candidates"); }}>Open the results</button></span>}
            </div>
          </div>
          <p className="muted small">Predictor: {data.predictor.available ? <>✅ {data.predictor.name} installed</> : <>⚠ not installed: nothing can be selected. Run <code>pip install mhcflurry</code> then <code>mhcflurry-downloads fetch models_class1_presentation</code>.</>}</p>
        </div>
      )}

      {tab === "data" && (
        <div>
          <div className="card">
            <div className="card-head"><h3>Patient’s tumour mutations</h3><span className="muted small">{data.patient.variants} loaded · {data.patient.with_normal} with matched-normal · {data.patient.with_rna} with RNA</span></div>
            <p className="muted small">Paste a table (tab- or comma-separated, header row: <code>gene, protein_change, vaf, depth, normal_vaf, tpm</code>) or a VCF annotated with SnpEff/VEP. Rows that cannot be read are listed, never guessed.</p>
            <textarea rows={6} value={varText} placeholder={"gene\tprotein_change\tvaf\tdepth\tnormal_vaf\ttpm\nKRAS\tp.G12D\t0.31\t120\t0\t14.2"} onChange={(e) => setVarText(e.target.value)} />
            <div className="row wrap" style={{ justifyContent: "flex-start", marginTop: 8 }}>
              <button className="primary" disabled={!varText.trim()} onClick={() => guard(async () => { const r = await api.vaxAddVariants(varText); setVarText(""); say(`Read ${r.read} mutation(s), ${r.added} new.${r.problems.length ? ` ${r.problems.length} problem(s): ${r.problems.slice(0, 3).join(" · ")}` : ""}`); })}>Add mutations</button>
              {data.patient.variants > 0 && <button className="danger" onClick={() => guard(() => api.vaxClear("patient"))}>Remove all patient data</button>}
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h3>HLA type (class I)</h3><span className="muted small">{data.patient.hla.length ? data.patient.hla.join(", ") : "none yet"}</span></div>
            <p className="muted small">Two-field resolution, for example <code>HLA-A*02:01 HLA-B*07:02 HLA-C*07:02</code>.</p>
            <input value={hlaText} placeholder="HLA-A*02:01, HLA-A*24:02, HLA-B*07:02 …" onChange={(e) => setHlaText(e.target.value)} />
            <div className="row wrap" style={{ justifyContent: "flex-start", marginTop: 8 }}>
              <button className="primary" disabled={!hlaText.trim()} onClick={() => guard(async () => { const r = await api.vaxSetHla(hlaText); say(r.alleles.length ? `Saved ${r.alleles.length} allele(s).` : r.problems.join(" ")); })}>Save HLA type</button>
              {data.case_hla.length > 0 && <button onClick={() => guard(() => api.vaxHlaFromCase())}>Use the HLA type from the case file ({data.case_hla.length})</button>}
            </div>
          </div>
          {data.patient.need_reference.length > 0 && (
            <div className="card">
              <div className="card-head"><h3>Reference proteins needed</h3></div>
              <p className="muted small">{data.patient.need_reference.join(", ")} need a reference protein sequence. Looking them up sends <b>only the gene symbols</b> to uniprot.org; no tumour data leave this computer. You can instead add a <code>wt_window</code> column.</p>
              <button onClick={() => guard(async () => { const r = await api.vaxFetchRefs(); say(Object.entries(r).map(([g, s]) => `${g}: ${s}`).join(" · ")); })}>Look up now</button>
            </div>
          )}
          {data.synthetic.variants > 0 && (
            <div className="card"><div className="card-head"><h3>Synthetic demo data</h3><span className="muted small">{data.synthetic.variants} fake mutations · never used for the patient</span></div>
              <button className="danger" onClick={() => guard(() => api.vaxClear("synthetic"))}>Remove the synthetic data</button></div>
          )}
        </div>
      )}

      {tab === "candidates" && (
        <div>
          <div className="card">
            <div className="card-head"><h3>Run history · {dataset === "patient" ? "Patient" : "Synthetic demo"}</h3></div>
            <p className="small muted">Every completed execution is a new run. Identical data and settings should produce identical targets—not new biological scenarios. To test a different assumption, change a parameter and save a scenario below.</p>
            <label>View completed run<select value={selectedRun?.dataset === dataset ? selectedRun.id : ""} onChange={(e) => {
              const id = Number(e.target.value);
              if (!id) { setSelectedRun(null); setVerify(""); return; }
              void guard(async () => { setSelectedRun(await api.vaxGetRun(id)); setVerify(""); });
            }}>
              <option value="">Latest {run ? `(#${data.latest[dataset]?.id})` : "(none)"}</option>
              {data.runs.filter((r) => r.dataset === dataset).map((r) => <option key={r.id} value={r.id}>Run #{r.id} · {r.selected} selected · {r.created_at}</option>)}
            </select></label>
            {run && <p className="small">Viewing run #{run.id} · {run.created_at} · {run.selected.length} selected targets.</p>}
          </div>
          <details className="card">
            <summary><strong>Run a computational parameter experiment</strong></summary>
            <p className="small">Change selection assumptions, not patient facts. These parameters affect computational shortlists, not vaccine efficacy. Save completed runs with a hypothesis in the Research workspace to compare them.</p>
            <div className="form-grid">
              <label>Minimum tumour VAF (0–1)<input type="number" min="0" max="1" step="0.01" value={experimentParams.min_vaf} onChange={(e) => setExperimentParams({ ...experimentParams, min_vaf: e.target.value })} /></label>
              <label>Minimum expression TPM<input type="number" min="0" step="0.1" value={experimentParams.min_tpm} onChange={(e) => setExperimentParams({ ...experimentParams, min_tpm: e.target.value })} /></label>
              <label>Maximum presentation percentile (0.5–100)<input type="number" min="0.5" max="100" step="0.1" value={experimentParams.max_pres_pct} onChange={(e) => setExperimentParams({ ...experimentParams, max_pres_pct: e.target.value })} /></label>
              <label>Maximum selected candidates (1–100)<input type="number" min="1" max="100" step="1" value={experimentParams.n_select} onChange={(e) => setExperimentParams({ ...experimentParams, n_select: e.target.value })} /></label>
            </div>
            <label>Scenario hypothesis / question<textarea maxLength={2000} rows={2} value={hypothesis} onChange={(e) => setHypothesis(e.target.value)} placeholder="Which computational assumption are you testing?" /></label>
            <p className="small muted">Dataset: {dataset === "synthetic" ? "synthetic software test" : "this patient's loaded data"}. Other settings retain the viewed run's values, or pipeline defaults if no run exists. Execution uses the currently loaded inputs; changed inputs will be flagged in Research comparisons.</p>
            <button disabled={!!running || mine.variants === 0 || !mine.hla.length || !hypothesis.trim()} onClick={() => void guard(runExperiment)}>Run parameter experiment and save scenario</button>
            {run && <div>
              <p className="small">Local AI can draft questions about bounded filter variations. It cannot add patient mutations, HLA types or efficacy scores. Nothing runs until you approve it.</p>
              <button disabled={!!assistant && ["queued", "running"].includes(assistant.status)} onClick={() => void guard(async () => { setAssistant((await api.researchHypotheses(run.id, true)).job); })}>Draft scenario hypotheses with local AI</button>
              {assistant && ["queued", "running"].includes(assistant.status) && <p role="status">Local AI {assistant.status}; this may take several minutes.</p>}
              {assistant?.status === "failed" && <div className="alert urgent" role="alert">{assistant.error}</div>}
              {assistant?.result.proposals?.map((proposal) => <div key={proposal.id} className="card">
                <p>{proposal.hypothesis}</p>
                <p className="small">VAF {String(proposal.params.min_vaf)} · TPM {String(proposal.params.min_tpm)} · maximum presentation percentile {String(proposal.params.max_pres_pct)} · selection count {String(proposal.params.n_select)}</p>
                <button onClick={() => {
                  setHypothesis(proposal.hypothesis);
                  setExperimentParams({ min_vaf: String(proposal.params.min_vaf), min_tpm: String(proposal.params.min_tpm), max_pres_pct: String(proposal.params.max_pres_pct), n_select: String(proposal.params.n_select) });
                }}>Use this draft (review before running)</button>
              </div>)}
              {assistant?.result.model && <p className="small muted">{assistant.result.model} · {assistant.result.note}</p>}
            </div>}
          </details>
          <div className="row wrap" style={{ justifyContent: "space-between" }}>
            <div className="tabs small-tabs">
              {(["patient", "synthetic"] as const).map((d) => <button key={d} className={dataset === d ? "tab on" : "tab"} onClick={() => setDataset(d)}>{d === "patient" ? "Patient" : "Synthetic demo"}</button>)}
            </div>
            <button className="primary" disabled={!!running || mine.variants === 0 || !mine.hla.length} onClick={() => guard(async () => {
              await api.vaxRun(dataset); setSelectedRun(null);
              say("New default-parameter run queued. Same inputs and settings should give the same targets; parameter scenarios are saved separately in Research.", true);
            })}>{running ? "Running…" : run ? "Run again" : "Run the pipeline"}</button>
          </div>
          {mine.variants === 0 && <p className="muted">No {dataset === "patient" ? "patient mutations loaded yet. Add them in the Data tab" : "synthetic data yet. Load it in Where you are"}.</p>}
          {!mine.hla.length && <p className="muted">HLA typing is missing for this dataset. Add class I HLA typing before running; it is never inferred or substituted.</p>}
          {running && <div className="progress-card card"><div className="spinner small" /><div className="small">{running.detail || "Starting (the binding model takes a few seconds to load)…"}</div></div>}
          {failed && !running && <div className="alert urgent">The last run could not finish: {failed.error}</div>}
          {run && (
            <>
              {dataset === "synthetic" && <div className="alert urgent">SYNTHETIC DATA — a software test, not the patient.</div>}
              <div className="card">
                <div className="card-head"><h3>What happened to each mutation</h3><span className="muted small">{run.predictor} · result <code>{run.result_hash.slice(0, 12)}</code></span></div>
                <Funnel run={run} />
                {run.warnings.map((w, i) => <div key={i} className="hint">⚠ {w}</div>)}
              </div>
              <div className="card">
                <div className="card-head"><h3>Selected candidates <span className="muted small">— tap a row for its score breakdown and caveats</span></h3>
                  <span className="muted small">A {run.tiers.A} · B {run.tiers.B} · C {run.tiers.C}</span></div>
                <CandidateTable items={run.selected} />
                <p className="muted small" style={{ marginBottom: 0 }}>Tier A: strongly predicted with every supporting measurement. B: one is missing. C: neither. ★ recurrent hotspot (curated list, verify). Computed by code; the AI never changes a score.</p>
              </div>
              <details className="card">
                <summary><strong>{run.rejected.length} mutation(s) rejected, and why</strong></summary>
                <ul className="small">{run.rejected.map((r, i) => <li key={i}><b>{r.gene} {r.change}</b> — {r.stage}: {r.reason}</li>)}</ul>
              </details>
              <div className="row wrap" style={{ justifyContent: "flex-start" }}>
                <a className="btn-link" href={workspaceUrl(`/api/vaccine/runs/${run.id}/dossier`)}>Download dossier (.md)</a>
                <a className="btn-link" href={workspaceUrl(`/api/vaccine/runs/${run.id}/dossier?fmt=json`)}>Download data (.json)</a>
                <button onClick={() => api.vaxVerify(run.id).then((r) => setVerify(r.ok ? `✅ Replayed from the recorded predictions: identical (${r.replayed.slice(0, 12)}).` : `❌ ${r.detail}`))}>Verify by replay</button>
                {verify && <span className="small">{verify}</span>}
              </div>
            </>
          )}
        </div>
      )}

      {tab === "review" && (
        <div>
          <p className="muted" style={{ marginTop: 10 }}>The local model acts as a review board: specialists read the computed numbers and write a memo for the tumour board. Their opinion never changes a score, and the memo is checked for invented numbers and efficacy claims.</p>
          {pack ? <PackPanel pack={pack} runningDetail="" onRun={() => guard(() => api.runAdvisor(PACK_ID).then(loadPack))} /> : <p className="muted small">The review pack is not available.</p>}
          <div className="card">
            <div className="card-head"><h3>Evals</h3>
              {data.eval && <span className={`badge ${data.eval.passed === data.eval.total ? "ready" : "attention"}`}>{data.eval.passed}/{data.eval.total} passed</span>}</div>
            <p className="muted small">Checks that the gates match planted ground truth, the selection is deterministic and replayable, the ranking ignores input order, tighter thresholds never add candidates, the result really depends on HLA, the predictor recovers published epitopes, and the dossier makes no efficacy claim. They show the software behaves as documented, <b>not</b> that any peptide would work as a vaccine.</p>
            <div className="row wrap" style={{ justifyContent: "flex-start" }}>
              <button className="primary" disabled={!!running} onClick={() => guard(() => api.vaxEvals(board))}>{running?.detail?.includes("evals") ? "Running…" : "Run the evals"}</button>
              <label className="check"><input type="checkbox" checked={board} onChange={(e) => setBoard(e.target.checked)} /> also test the local-model memo (several minutes)</label>
            </div>
            {data.eval && (
              <ul className="plain evals">
                {data.eval.checks.map((c) => <li key={c.name}><span aria-hidden>{c.passed ? "✅" : "❌"}</span> <b>{c.name.replace(/_/g, " ")}</b><div className="small muted">{c.detail}</div></li>)}
              </ul>
            )}
          </div>
          <details className="card">
            <summary><strong>What is not built, and why</strong></summary>
            <ul className="small">
              <li><b>Frameshifts, insertions/deletions, splice variants, fusions and self/cancer-testis antigens</b> (which yash also uses) need transcript-level translation. They are rejected with that reason, never guessed.</li>
              <li><b>Class II (helper T-cell) targets</b> are not modelled.</li>
              <li><b>No model fine-tuning.</b> There is no real labelled data here, and training a model on labels the pipeline itself invented would be circular and would only make the output look more convincing. Real validation needs published T-cell assay data (for example IEDB or the TESLA consortium) and then laboratory testing.</li>
              <li><b>No mRNA/DNA construct design and no manufacturing or dosing information.</b> That belongs to the trial or manufacturing team.</li>
            </ul>
          </details>
        </div>
      )}
    </section>
  );
}
