import { useCallback, useEffect, useState } from "react";
import { api, type Cohort, type TreatmentOptions } from "../api";

const pct = (x: number) => `${Math.round(x * 100)}%`;
const mins = (s: number) => (s >= 3600 ? `${(s / 3600).toFixed(1)} h` : `${Math.max(1, Math.round(s / 60))} min`);

export function CohortTab() {
  const [c, setC] = useState<Cohort | null>(null);
  const [n, setN] = useState(10000);
  const [err, setErr] = useState("");
  const load = useCallback(() => api.cohort().then(setC).catch(() => undefined), []);
  useEffect(() => { void load(); }, [load]);
  const state = c?.status.state ?? "none";
  const auditRunning = c?.audit.status.state === "running";
  const active = state === "running" || state === "building" || auditRunning;
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => { void load(); }, 5000);
    return () => clearInterval(t);
  }, [active, load]);
  if (!c) return <p className="muted">Loading…</p>;
  const s = c.summary;
  const done = c.status.done ?? 0;
  const target = c.status.target ?? n;
  const rate = c.status.rate ?? 0;
  const eta = rate > 0 ? mins((target - done) / rate) : "";
  const start = async () => { setErr(""); try { await api.cohortStart(n); await load(); } catch (e) { setErr((e as Error).message); } };
  const full = s?.views.full;
  const panel = s?.views.panel_only;

  return (
    <div>
      <div className="card">
        <div className="card-head"><h3>Synthetic cohort: stress-testing the pipeline on thousands of made-up tumours</h3></div>
        <p className="small">Your father’s sequencing and HLA type do not exist yet. This builds thousands of <b>invented</b> tumours shaped like his situation, runs every one through the same pipeline with the real binding predictor, and shows what to expect and <b>which missing tests matter most</b>, so the right ones are requested first.</p>
        <p className="small"><b>What it cannot do:</b> it cannot say a vaccine will work, and it cannot say which treatment is better, because every outcome here is produced by a computer on invented mutations. Treatment options are on the next tab and do not come from this.</p>
        <details className="small"><summary>How the case shaped the simulation</summary>
          <ul>{c.situation.map((w) => <li key={w}>{w}</li>)}</ul>
        </details>
        <div className="row wrap" style={{ justifyContent: "flex-start", marginTop: 8 }}>
          {!active && (
            <>
              <select value={n} onChange={(e) => setN(Number(e.target.value))} aria-label="Number of scenarios">
                <option value={1000}>1,000 scenarios (under a minute)</option>
                <option value={10000}>10,000 scenarios (about 5 minutes, plus 2 the first time)</option>
                <option value={25000}>25,000 scenarios</option>
              </select>
              <button className="primary" onClick={start}>{state === "done" ? "Run again" : state === "stopped" || state === "interrupted" ? "Resume" : "Start the cohort run"}</button>
            </>
          )}
          {active && !auditRunning && <button onClick={() => api.cohortStop().then(load)}>Stop (results so far are kept)</button>}
        </div>
        {err && <div className="alert urgent">{err}</div>}
        {(active || state === "stopped" || state === "interrupted" || state === "failed") && (
          <div style={{ marginTop: 10 }}>
            <div className="meter"><div style={{ width: `${Math.min(100, (done / Math.max(target, 1)) * 100)}%` }} /></div>
            <div className="small muted">{c.status.message} · {done.toLocaleString()} of {target.toLocaleString()} scenarios{eta ? ` · about ${eta} left` : ""}. You can keep using the app; this runs in a separate process.</div>
          </div>
        )}
      </div>

      {s && full && panel && (
        <>
          <div className="card">
            <div className="card-head"><h3>Local-model review (uses LM Studio)</h3></div>
            <p className="small">The 10,000 scenarios above are arithmetic on a binding predictor, so they run on the CPU and LM Studio stays idle. The model is used here, where judgement is needed, and it is <b>scored against known answers</b> instead of trusted. On simulated tumours with no matched normal sample, it reads each ranked shortlist and flags candidates that look inherited rather than tumour-specific. Because the tumours are simulated, we know which picks truly were inherited. Its flags are compared with a one-line rule (VAF at least 0.40). It then writes a plain-language memo of the cohort, in which every number is checked against the facts. It never changes a score.</p>
            {c.audit.status.state === "running" ? (
              <>
                <div className="meter"><div style={{ width: `${Math.min(100, ((c.audit.status.done ?? 0) / Math.max(c.audit.status.target ?? 1, 1)) * 100)}%` }} /></div>
                <div className="small muted">{c.audit.status.message} · {c.audit.status.done ?? 0} of about {c.audit.status.target ? c.audit.status.target - 1 : "?"} cases. LM Studio is working on this now (roughly 30 seconds per case).</div>
                <button onClick={() => api.cohortStop().then(load)} style={{ marginTop: 6 }}>Stop</button>
              </>
            ) : (
              <div className="row wrap" style={{ justifyContent: "flex-start" }}>
                <button className="primary" onClick={async () => { setErr(""); try { await api.cohortAudit(60); await load(); } catch (e) { setErr((e as Error).message); } }}>
                  {c.audit.summary ? "Run the model review again (60 cases)" : "Run the model review (60 cases, about 15–20 minutes)"}
                </button>
                {c.audit.status.state === "failed" && <span className="small">⚠ {c.audit.status.message}</span>}
              </div>
            )}
            {c.audit.summary && (
              <div style={{ marginTop: 10 }}>
                <div className="vtable-wrap">
                  <table className="vtable">
                    <thead><tr><th></th><th>Inherited variants caught</th><th>Missed</th><th>False flags</th><th>Precision</th><th>Recall</th><th>Clean shortlists falsely flagged</th></tr></thead>
                    <tbody>
                      {([["Local model", c.audit.summary.model], ["Simple rule (VAF ≥ 0.40)", c.audit.summary.rule]] as const).map(([name, m]) => (
                        <tr key={name}><td><b>{name}</b></td><td>{m.true_flags}</td><td>{m.missed}</td><td>{m.false_flags}</td><td>{pct(m.precision)}</td><td>{pct(m.recall)}</td><td>{pct(m.clean_cases_with_false_alarm)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="small"><b>{c.audit.summary.verdict}</b> ({c.audit.summary.answered} shortlists answered of {c.audit.summary.cases}; {c.audit.summary.failed} failed; about {Math.round(c.audit.summary.median_secs)} s each.)</p>
                {c.audit.summary.memo && (c.audit.summary.memo.passed
                  ? <div className="card" style={{ background: "var(--bg, #f6f6f4)" }}><div className="small muted">Memo written by the local model; every number was checked against the results above.</div><p className="small" style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>{c.audit.summary.memo.text}</p></div>
                  : <p className="small muted">The model’s memo was rejected by the checks ({c.audit.summary.memo.problems.join("; ")}), so it is not shown.</p>)}
              </div>
            )}
          </div>
          <div className="card">
            <div className="card-head"><h3>What to expect {s.complete ? "" : "(partial: still running)"} <span className="muted small">· {s.scenarios.toLocaleString()} scenarios</span></h3></div>
            <p className="small">Yield below is the number of mutations with at least one <i>strongly presented</i> peptide for the person’s HLA type. It is a count of candidates to look at, not a prediction that they would work: many predicted peptides never trigger an immune response.</p>
            <div className="vtable-wrap">
              <table className="vtable">
                <thead><tr><th>Data available</th><th>Typical yield (10th / median / 90th)</th><th>≥3 candidates</th><th>≥10</th><th>Nothing usable</th></tr></thead>
                <tbody>
                  {Object.values(s.views).map((v) => (
                    <tr key={v.label}>
                      <td><b>{v.label}</b></td>
                      <td>{v.strong_p10} / <b>{v.strong_median}</b> / {v.strong_p90}</td>
                      <td>{pct(v.p_strong_ge["3"])}</td><td>{pct(v.p_strong_ge["10"])}</td><td>{pct(v.p_none)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="small">
              <li><b>A small gene panel is not enough.</b> In {pct(1 - panel.p_strong_ge["1"])} of simulated tumours it leaves no strongly presented candidate at all, and the median yield falls from {full.strong_median} to {panel.strong_median}.</li>
              <li><b>Tumour RNA</b> filters out mutations in genes that are switched off. Without it the list looks longer (median {s.views.no_rna.strong_median} against {full.strong_median}) but includes candidates that may never be made, and none can reach the top evidence tier.</li>
              <li><b>A matched normal (blood)</b> is needed to remove inherited variants: without it, an average of {s.paired.no_normal_germline_change} inherited variant(s) per shortlist were wrongly selected.</li>
              <li>Most important input: <b>the number of tumour mutations found</b> (below), then the HLA type.</li>
            </ul>
          </div>

          <div className="card">
            <div className="card-head"><h3>Yield by number of mutations found (exome)</h3></div>
            <div className="vtable-wrap">
              <table className="vtable">
                <thead><tr><th>Mutations</th><th>Scenarios</th><th>Median yield</th><th>≥3 candidates</th><th>Nothing usable</th><th>Panel gives ≥1</th></tr></thead>
                <tbody>{s.burden_bins.map((b) => <tr key={b.label}><td>{b.label}</td><td>{b.n}</td><td>{b.full_strong_median}</td><td>{pct(b.p_full_strong_ge3)}</td><td>{pct(b.p_full_none)}</td><td>{pct(b.p_panel_strong_ge1)}</td></tr>)}</tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h3>Where your father sits</h3></div>
            {c.compare ? (
              <p className="small">With his loaded data ({c.compare.view_label}; {c.compare.mutations} mutations) he has <b>{c.compare.strong_variants}</b> mutations with a strongly presented peptide and a shortlist of {c.compare.selected}. That is higher than {c.compare.percentile}% of {c.compare.basis} (their median: {c.compare.median_similar}).</p>
            ) : (
              <p className="small">No real mutation list or HLA type is loaded yet, so there is nothing to compare. When his results arrive, load them in the <b>Data</b> tab and run the pipeline: this card will then show where his result sits among the simulated tumours.</p>
            )}
          </div>

          <div className="card">
            <div className="card-head"><h3>Does the HLA type matter?</h3></div>
            <p className="small">Difference in yield when a person carries each allele (HLA types in the simulation are equal-weighted, so this shows sensitivity, not how common each is). Highest and lowest:</p>
            <div className="row wrap" style={{ justifyContent: "flex-start", gap: 6 }}>
              {[...s.alleles.slice(0, 4), ...s.alleles.slice(-4)].map((a) => <span key={a.allele} className="badge">{a.allele.replace("HLA-", "")}: {a.delta_vs_all > 0 ? "+" : ""}{a.delta_vs_all}</span>)}
            </div>
          </div>

          <p className="muted small">
            Reproducible: predictor {s.meta?.predictor ?? "—"}; lookup check vs the real predictor on {s.meta?.equivalence.compared} peptides: {s.meta?.equivalence.ok ? "identical" : "MISMATCH"}{s.hash ? ` · result ${s.hash}` : ""}{s.seconds ? ` · ${mins(s.seconds)}` : ""}.
            Assumptions (mutation count, purity, expression, equal-weight HLA) are those listed above, not measurements.
          </p>
        </>
      )}
    </div>
  );
}

export function OptionsTab() {
  const [o, setO] = useState<TreatmentOptions | null>(null);
  useEffect(() => { void api.treatmentOptions().then(setO).catch(() => undefined); }, []);
  if (!o) return <p className="muted">Loading…</p>;
  return (
    <div>
      <div className="card vax-warn">
        <b>Ten options to discuss with the oncologist: not a ranking and not advice.</b> {o.note}
        <ol className="small" style={{ paddingLeft: 20 }}>{o.first.map((f) => <li key={f}>{f}</li>)}</ol>
      </div>
      {o.options.map((x, i) => (
        <div className="card" key={x.id}>
          <div className="card-head"><h3>{i + 1}. {x.title}</h3><span className="badge">{x.evidence}</span></div>
          <p className="small">{x.what}</p>
          {x.records.length > 0 && <div className="small"><b>In your records:</b><ul>{x.records.map((r) => <li key={r}>{r}</li>)}</ul></div>}
          <div className="small"><b>Ask:</b><ul>{x.ask.map((q) => <li key={q}>{q}</li>)}</ul></div>
        </div>
      ))}
    </div>
  );
}
