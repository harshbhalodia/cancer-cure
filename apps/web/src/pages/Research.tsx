import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, workspaceUrl, type ResearchAIJob, type Vaccine } from "../api";
import ResearchNotebook from "./ResearchNotebook";

type Evidence = {
  id: number;
  source_url: string;
  study_id: string;
  platform: string;
  disease: string;
  setting: string;
  prior_pd1: string;
  endpoint_result: string;
  n: number | null;
  followup: string;
  evidence_level: string;
  limitations: string;
  as_of: string;
  user_entered_unverified: boolean;
  comparison: {
    resembles: string[];
    differs: string[];
    unknown: string[];
    note: string;
  };
};
type Profile = { disease: string; setting: string; prior_pd1: string; reported_unverified: boolean };
type Run = { id: number; dataset: string; created_at: string; selected: number };
type Selected = { id: string; rank: number; score: number; caveats: string[] };
type Experiment = {
  id: number;
  source_run_id: number;
  hypothesis: string;
  input_hash: string;
  result_hash: string;
  predictor: string;
  dataset: string;
  candidate_counts: { candidate_count: number; selected_count: number; rejected_count: number };
  selected: Selected[];
  caveats: string[];
  params: Record<string, unknown>;
  created_at: string;
  computational_only: boolean;
};
type Comparison = {
  controlled: boolean;
  warning: string | null;
  added_ids: string[];
  removed_ids: string[];
  shared_ids: string[];
  shared_differences: { id: string; left_rank: number; right_rank: number; rank_delta: number; left_score: number; right_score: number; score_delta: number }[];
  changed_params: { name: string; left: unknown; right: unknown; left_present: boolean; right_present: boolean }[];
  counts: { left_selected: number; right_selected: number; added: number; removed: number; shared: number };
  note: string;
};

const SETTINGS = ["active_recurrent", "postoperative", "other", "unknown"];
const PD1 = ["yes", "no", "unknown"];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(workspaceUrl(path), {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    const text = await response.text();
    try {
      if (text) {
        const body = JSON.parse(text);
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
      }
    } catch {
      if (text) detail = text;
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function today(): string {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function label(value: string) {
  return value.replaceAll("_", " ");
}

function SnapshotReview({ id }: { id: number }) {
  const [job, setJob] = useState<ResearchAIJob | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    void api.researchReview(id).then((r) => { if (active) setJob(r.job); }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [id]);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let active = true;
    const timer = setInterval(() => {
      void api.researchReview(id).then((r) => { if (active) setJob(r.job); }).catch((e: Error) => { if (active) setError(e.message); });
    }, 4000);
    return () => { active = false; clearInterval(timer); };
  }, [id, job?.status]);
  const queue = async () => {
    setBusy(true); setError("");
    try { setJob((await api.researchReview(id, true)).job); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const pending = !!job && ["queued", "running"].includes(job.status);
  return <div>
    <p className="small muted">The local AI reviews this immutable snapshot only. Its interpretation never changes the candidate scores or supplies missing patient facts.</p>
    <button disabled={busy || pending} onClick={() => void queue()}>Review snapshot #{id} with local AI</button>
    {pending && <p role="status">Local AI {job.status}; this may take several minutes.</p>}
    {(error || job?.status === "failed") && <div className="alert urgent" role="alert">{error || job?.error}</div>}
    {job?.status === "done" && job.result.markdown && <div>
      <p className="small">AI interpretation · {job.result.model} · snapshot #{id}</p>
      <pre className="draft">{job.result.markdown}</pre>
    </div>}
  </div>;
}

export default function Research() {
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [profile, setProfile] = useState<Profile>({ disease: "", setting: "unknown", prior_pd1: "unknown", reported_unverified: true });
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [leftId, setLeftId] = useState("");
  const [rightId, setRightId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [card, setCard] = useState({
    source_url: "", study_id: "", platform: "", disease: "", setting: "unknown",
    prior_pd1: "unknown", endpoint_result: "", n: "", followup: "", evidence_level: "peer_reviewed",
    limitations: "", as_of: today(),
  });
  const [hypothesis, setHypothesis] = useState("");
  const [sourceRun, setSourceRun] = useState("");
  const [runProgress, setRunProgress] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [evidenceResult, profileResult, experimentResult, vaccineResult] = await Promise.all([
        request<{ items: Evidence[] }>("/api/research/evidence"),
        request<Profile>("/api/research/profile"),
        request<{ items: Experiment[] }>("/api/research/experiments"),
        request<Vaccine>("/api/vaccine"),
      ]);
      setEvidence(evidenceResult.items);
      setProfile(profileResult);
      setExperiments(experimentResult.items);
      setRuns(vaccineResult.runs);
      const pending = vaccineResult.jobs.find((job) => ["queued", "running"].includes(job.status));
      setRunProgress(pending ? `${pending.status}: ${pending.detail || "computing run"}` : "");
    } catch (e) {
      setError(`Could not load the research workspace: ${(e as Error).message}`);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!runProgress) return;
    let active = true;
    const timer = setInterval(() => {
      void Promise.all([request<{ items: Experiment[] }>("/api/research/experiments"), request<Vaccine>("/api/vaccine")])
        .then(([saved, vaccine]) => {
          if (!active) return;
          setExperiments(saved.items); setRuns(vaccine.runs);
          const pending = vaccine.jobs.find((job) => ["queued", "running"].includes(job.status));
          setRunProgress(pending ? `${pending.status}: ${pending.detail || "computing run"}` : "");
          const failed = vaccine.jobs.find((job) => job.status === "failed");
          if (!pending && failed) setError(`A computational job failed: ${failed.error}`);
        }).catch((e: Error) => { if (active) setError(e.message); });
    }, 4000);
    return () => { active = false; clearInterval(timer); };
  }, [!!runProgress]);

  async function submitEvidence(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await request("/api/research/evidence", {
        method: "POST",
        body: JSON.stringify({ ...card, n: card.n === "" ? null : Number(card.n) }),
      });
      setNotice("Citation card saved locally. Its details are user-entered and unverified.");
      setCard({ source_url: "", study_id: "", platform: "", disease: "", setting: "unknown", prior_pd1: "unknown", endpoint_result: "", n: "", followup: "", evidence_level: "peer_reviewed", limitations: "", as_of: today() });
      await load();
    } catch (e) {
      setError(`Could not save the citation card: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updated = await request<Profile>("/api/research/profile", {
        method: "PUT",
        body: JSON.stringify({ disease: profile.disease, setting: profile.setting, prior_pd1: profile.prior_pd1 }),
      });
      setProfile(updated);
      setNotice("Comparison profile saved on this device. These details are user-reported and unverified.");
      await load();
    } catch (e) {
      setError(`Could not save the comparison profile: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function removeEvidence(id: number) {
    if (!window.confirm("Remove this local citation card?")) return;
    setBusy(true);
    setError("");
    try {
      await request(`/api/research/evidence/${id}`, { method: "DELETE" });
      await load();
      setNotice("Citation card removed.");
    } catch (e) {
      setError(`Could not remove the citation card: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function snapshotRun(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await request("/api/research/experiments", {
        method: "POST",
        body: JSON.stringify({ source_run_id: Number(sourceRun), hypothesis }),
      });
      setHypothesis("");
      await load();
      setNotice("Immutable computational snapshot saved. It contains no treatment outcome or efficacy claim.");
    } catch (e) {
      setError(`Could not save the run snapshot: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function compareRuns(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setComparison(null);
    try {
      const result = await request<Comparison>(`/api/research/experiments/compare?left_id=${encodeURIComponent(leftId)}&right_id=${encodeURIComponent(rightId)}`);
      setComparison(result);
    } catch (e) {
      setError(`Could not compare snapshots: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>Research workspace</h1>
        <p>Keep source-linked evidence notes and compare saved computational runs on this workspace.</p>
      </header>
      <div className="card vax-warn">
        <b>Research only:</b> citations are entered by you and are not independently verified. Similarity is descriptive,
        not clinical matching or treatment advice. Run comparisons describe software outputs only—not benefit, response,
        or personal success. No patient information is sent to search services; this page does not search the web.
      </div>
      {error && <div className="alert urgent" role="alert">{error}</div>}
      {notice && <div className="alert ok" role="status">{notice}</div>}

      <ResearchNotebook />

      <div className="card">
        <div className="card-head"><h2>Local comparison profile</h2><span className="badge partial">reported · unverified</span></div>
        <p className="small muted">Used only to describe similarities and differences against evidence cards. Unknown is the default; no clinical conclusions are made.</p>
        <form onSubmit={saveProfile}>
          <div className="row wrap">
            <label className="grow">Disease / histology reported for comparison
              <input value={profile.disease} maxLength={300} onChange={(e) => setProfile({ ...profile, disease: e.target.value })} placeholder="Optional; e.g. disease or histology" />
            </label>
            <label>Setting
              <select value={profile.setting} onChange={(e) => setProfile({ ...profile, setting: e.target.value })}>{SETTINGS.map((x) => <option key={x} value={x}>{label(x)}</option>)}</select>
            </label>
            <label>Prior PD-1
              <select value={profile.prior_pd1} onChange={(e) => setProfile({ ...profile, prior_pd1: e.target.value })}>{PD1.map((x) => <option key={x} value={x}>{x}</option>)}</select>
            </label>
            <button className="primary" disabled={busy}>Save profile</button>
          </div>
        </form>
      </div>

      <div className="card">
        <div className="card-head"><h2>Add an evidence card</h2><span className="small muted">Stored locally · user-entered · unverified</span></div>
        <form onSubmit={submitEvidence}>
          <div className="row wrap">
            <label className="grow">Public source URL
              <input required type="url" maxLength={2000} placeholder="https://…" value={card.source_url} onChange={(e) => setCard({ ...card, source_url: e.target.value })} />
            </label>
            <label>Study / NCT ID
              <input maxLength={100} value={card.study_id} onChange={(e) => setCard({ ...card, study_id: e.target.value })} />
            </label>
            <label>Evidence level
              <select value={card.evidence_level} onChange={(e) => setCard({ ...card, evidence_level: e.target.value })}>
                <option value="registry">Registry</option><option value="conference">Conference</option><option value="peer_reviewed">Peer reviewed</option>
              </select>
            </label>
          </div>
          <div className="row wrap">
            <label className="grow">Platform <input required maxLength={200} value={card.platform} onChange={(e) => setCard({ ...card, platform: e.target.value })} /></label>
            <label className="grow">Disease / histology <input required maxLength={300} value={card.disease} onChange={(e) => setCard({ ...card, disease: e.target.value })} /></label>
            <label>Study setting <select value={card.setting} onChange={(e) => setCard({ ...card, setting: e.target.value })}>{SETTINGS.map((x) => <option key={x} value={x}>{label(x)}</option>)}</select></label>
            <label>Prior PD-1 <select value={card.prior_pd1} onChange={(e) => setCard({ ...card, prior_pd1: e.target.value })}>{PD1.map((x) => <option key={x} value={x}>{x}</option>)}</select></label>
          </div>
          <label>Endpoint / result text
            <textarea required maxLength={5000} rows={3} value={card.endpoint_result} onChange={(e) => setCard({ ...card, endpoint_result: e.target.value })} />
          </label>
          <div className="row wrap">
            <label>n (optional, positive whole number) <input type="number" min={1} step={1} value={card.n} onChange={(e) => setCard({ ...card, n: e.target.value })} /></label>
            <label>Follow-up (optional) <input maxLength={200} value={card.followup} onChange={(e) => setCard({ ...card, followup: e.target.value })} /></label>
            <label>As-of date <input required type="date" max={today()} value={card.as_of} onChange={(e) => setCard({ ...card, as_of: e.target.value })} /></label>
          </div>
          <label>Limitations <textarea rows={2} maxLength={5000} value={card.limitations} onChange={(e) => setCard({ ...card, limitations: e.target.value })} /></label>
          <button className="primary" disabled={busy}>Save citation card</button>
        </form>
      </div>

      <div className="card">
        <div className="card-head"><h2>Evidence cards</h2><span className="small muted">{evidence.length} saved</span></div>
        {evidence.length === 0 ? <p className="muted">No evidence cards yet. Add a public citation above; the app will not fetch it automatically.</p> : evidence.map((item) => (
          <article key={item.id} className="card">
            <div className="card-head">
              <h3>{item.platform} · {item.disease}</h3>
              <button className="link" disabled={busy} onClick={() => void removeEvidence(item.id)}>Remove</button>
            </div>
            <p className="small"><a href={item.source_url} target="_blank" rel="noopener noreferrer">{item.study_id || item.source_url}</a> · {item.evidence_level} · as of {item.as_of} · n={item.n ?? "unknown"} · follow-up {item.followup || "unknown"}</p>
            <p>{item.endpoint_result}</p>
            {item.limitations && <p className="small"><b>Limitations:</b> {item.limitations}</p>}
            <p className="small"><b>Setting:</b> {label(item.setting)} · <b>Prior PD-1:</b> {item.prior_pd1}</p>
            <div className="small">
              <b>Descriptive comparison:</b> resembles {item.comparison.resembles.join(", ") || "none"};
              {" "}differs {item.comparison.differs.join(", ") || "none"};
              {" "}unknown {item.comparison.unknown.join(", ") || "none"}.
              <div className="muted">{item.comparison.note}</div>
            </div>
            <span className="badge partial">user-entered · unverified</span>
          </article>
        ))}
      </div>

      <div className="card">
        <div className="card-head"><h2>Computational experiment snapshots</h2><span className="badge partial">computational only</span></div>
        {runProgress && <p role="status">Computational run {runProgress}. Saved scenarios appear here automatically when complete.</p>}
        <p className="small muted">Snapshots copy selected IDs, ranks, scores, parameters, counts, hashes, and caveats from a completed run. They are immutable and remain after the source run is removed. Use the existing vaccine pipeline to run new parameters; this page does not run or recommend them.</p>
        <form onSubmit={snapshotRun}>
          <div className="row wrap">
            <label>Completed run
              <select required value={sourceRun} onChange={(e) => setSourceRun(e.target.value)}>
                <option value="">Choose a run…</option>
                {runs.map((run) => <option key={run.id} value={run.id}>Run #{run.id} · {run.dataset} · {run.selected} selected · {run.created_at}</option>)}
              </select>
            </label>
            <label className="grow">Hypothesis / note <input required maxLength={2000} value={hypothesis} onChange={(e) => setHypothesis(e.target.value)} placeholder="What computational assumption are you recording?" /></label>
            <button className="primary" disabled={busy || !runs.length}>Save snapshot</button>
          </div>
        </form>
        {runs.length === 0 && <p className="muted small">No completed runs are available in the vaccine workspace.</p>}
        {experiments.length === 0 ? <p className="muted">No experiment snapshots yet.</p> : experiments.map((experiment) => (
          <article key={experiment.id} className="card">
            <h3>Snapshot #{experiment.id} · run #{experiment.source_run_id} · {experiment.dataset}</h3>
            <p>{experiment.hypothesis}</p>
            <p className="small">Predictor: {experiment.predictor} · selected {experiment.candidate_counts.selected_count} / {experiment.candidate_counts.candidate_count} candidates · rejected {experiment.candidate_counts.rejected_count}</p>
            <p className="small">Input hash <code>{experiment.input_hash.slice(0, 16)}</code> · result hash <code>{experiment.result_hash.slice(0, 16)}</code></p>
            {experiment.selected.length > 0 && <ol className="small">{experiment.selected.map((candidate) => <li key={candidate.id}><code>{candidate.id}</code> — rank {candidate.rank}, score {candidate.score}{candidate.caveats.length ? ` · caveats: ${candidate.caveats.join("; ")}` : ""}</li>)}</ol>}
            {experiment.caveats.length > 0 && <p className="small"><b>Caveats:</b> {experiment.caveats.join(" · ")}</p>}
            <span className="badge partial">stored computational output · not efficacy</span>
            <SnapshotReview id={experiment.id} />
          </article>
        ))}
      </div>

      <div className="card">
        <h2>Compare two snapshots</h2>
        <p className="small muted">Controlled comparison requires matching stored data/reference fingerprints, pipeline version, dataset and predictor, while parameters may differ. Missing provenance is non-controlled; no efficacy claim is made.</p>
        <form onSubmit={compareRuns}>
          <div className="row wrap">
            <label>First snapshot <select required value={leftId} onChange={(e) => setLeftId(e.target.value)}><option value="">Choose…</option>{experiments.map((x) => <option key={x.id} value={x.id}>Snapshot #{x.id} · run #{x.source_run_id}</option>)}</select></label>
            <label>Second snapshot <select required value={rightId} onChange={(e) => setRightId(e.target.value)}><option value="">Choose…</option>{experiments.map((x) => <option key={x.id} value={x.id}>Snapshot #{x.id} · run #{x.source_run_id}</option>)}</select></label>
            <button className="primary" disabled={busy || experiments.length < 2}>Compare snapshots</button>
          </div>
        </form>
        {comparison && <div className="card" role="status">
          <h3>{comparison.controlled ? "Controlled computational comparison" : "Non-controlled computational comparison"}</h3>
          {comparison.warning && <div className="alert urgent">{comparison.warning}</div>}
          <p>Selected: {comparison.counts.left_selected} → {comparison.counts.right_selected}. Added {comparison.counts.added}; removed {comparison.counts.removed}; shared {comparison.counts.shared}.</p>
          <p className="small"><b>Added:</b> {comparison.added_ids.join(", ") || "none"} · <b>Removed:</b> {comparison.removed_ids.join(", ") || "none"}</p>
          {comparison.changed_params.length > 0 && <p className="small"><b>Changed parameters:</b> {comparison.changed_params.map((p) => `${p.name}: ${p.left_present ? JSON.stringify(p.left) : "not set"} → ${p.right_present ? JSON.stringify(p.right) : "not set"}`).join(" · ")}</p>}
          {comparison.shared_differences.length > 0 && <ul className="small">{comparison.shared_differences.map((x) => <li key={x.id}><code>{x.id}</code>: score {x.left_score} → {x.right_score} (Δ {x.score_delta}), rank {x.left_rank} → {x.right_rank} (Δ {x.rank_delta})</li>)}</ul>}
          <p className="small muted">{comparison.note}</p>
        </div>}
      </div>
    </section>
  );
}
