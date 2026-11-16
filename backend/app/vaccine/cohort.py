"""A large synthetic cohort to stress-test the vaccine pipeline, run as a long background process.

What this is for: the patient's own sequencing and HLA type do not exist yet. Before they do, thousands of *made-up*
tumours shaped like the case (see `profile`) are pushed through the exact same pipeline with the real predictor, to learn
how many strongly presented candidates to expect, how that depends on the number of mutations and on the HLA type,
and what the missing pieces (tumour RNA, matched normal, a small gene panel instead of an exome) cost. It answers
"which tests are worth asking for" and "what would a result look like".

What it cannot do: every outcome here is produced by the predictor on invented mutations. It says nothing about whether a
vaccine would work, nor which treatment is better. Nothing in this file produces or ranks treatments.

Speed: the predictor is run once per (peptide, allele) over a pool of synthetic mutations and kept in a table; each
scenario then samples mutations and an HLA genotype from that pool and runs the real pipeline code on table lookups.
`check_equivalence` proves the lookup reproduces the real predictor's multi-allele answer before any scenario is run.

Run:  python -m app.vaccine.cohort run --n 10000 --workers 12
Files (under <data_dir>/cohort): status.json, table.pkl, scenarios.jsonl, summary.json, STOP (flag to stop early).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import os
import pickle
import random
import time
from pathlib import Path

from app.vaccine import pipeline, peptides
from app.vaccine.pipeline import Params

AA = "ACDEFGHIKLMNPQRSTVWY"
POOL_SIZE = 300
# Common class I alleles (A, B, C). Equal weights: these are NOT population frequencies, so cohort numbers describe a
# range of plausible HLA types, not the probability for any one population.
PANEL = {
    "A": ["HLA-A*01:01", "HLA-A*02:01", "HLA-A*02:06", "HLA-A*03:01", "HLA-A*11:01", "HLA-A*24:02", "HLA-A*26:01", "HLA-A*31:01", "HLA-A*33:03", "HLA-A*68:01"],
    "B": ["HLA-B*07:02", "HLA-B*08:01", "HLA-B*13:01", "HLA-B*15:01", "HLA-B*35:01", "HLA-B*40:01", "HLA-B*44:02", "HLA-B*44:03", "HLA-B*51:01", "HLA-B*52:01", "HLA-B*57:01", "HLA-B*58:01"],
    "C": ["HLA-C*01:02", "HLA-C*03:03", "HLA-C*03:04", "HLA-C*04:01", "HLA-C*05:01", "HLA-C*06:02", "HLA-C*07:01", "HLA-C*07:02", "HLA-C*08:01", "HLA-C*12:03", "HLA-C*15:02"],
}
VIEWS = ("full", "no_rna", "no_normal", "panel_only")
VIEW_LABEL = {"full": "Exome + tumour RNA + matched normal", "no_rna": "Exome + matched normal, no tumour RNA", "no_normal": "Exome + RNA, no matched normal",
              "panel_only": "Small gene panel only (tumour DNA)"}

DEFAULT_PROFILE = {
    "label": "generic solid tumour",
    "median_burden": 60,       # coding missense mutations after exome sequencing: an assumption, wide spread on purpose
    "burden_sigma": 0.9,
    "purity": [0.25, 0.85],    # share of cells in the sample that are tumour
    "subclonal_frac": 0.3,
    "depth_median": 100,
    "germline_frac": 0.04,     # inherited variants mixed in (only a matched normal can remove them)
    "silent_frac": 0.25,       # genes not expressed in the tumour
    "median_tpm": 8.0,
    "panel_frac": 0.05,        # a few-hundred-gene panel covers roughly this share of exome mutations
}


def cohort_dir() -> Path:
    from app.config import get_settings  # noqa: PLC0415

    d = get_settings().data_dir / "cohort"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------------------------------------ pool and table
def make_pool(seed: int = 11, n: int = POOL_SIZE) -> list[dict]:
    rng = random.Random(seed)
    pool = []
    for k in range(n):
        seq = "M" + "".join(rng.choice(AA) for _ in range(260))
        pos = rng.randint(30, 230)
        wt = seq[pos - 1]
        mut = rng.choice([a for a in AA if a != wt])
        pool.append({"id": k + 1, "gene": f"SYP{k + 1:03d}", "protein_change": f"{wt}{pos}{mut}", "wt_window": seq, "wt_start": 1, "pos": pos, "wt": wt, "mut": mut})
    return pool


def pool_peptides(pool: list[dict], lengths=(8, 9, 10, 11)) -> list[str]:
    out: set[str] = set()
    for v in pool:
        for p in peptides.peptides_for(v["wt_window"], 1, v["pos"], v["wt"], v["mut"], lengths):
            out.add(p["mut"])
            out.add(p["wt"])
    return sorted(out)


class Lookup:
    """Predictor interface served from the table. For several alleles the best (lowest affinity) allele wins, as in the real predictor."""

    def __init__(self, table: dict, name: str) -> None:
        self.table, self.name = table, name

    def supported(self, allele: str) -> bool:
        return allele in self.table

    def predict(self, peps: list[str], alleles: list[str]) -> dict[str, dict]:
        out = {}
        for p in set(peps):
            best = None
            for a in sorted(alleles):
                rec = self.table[a][p]
                if best is None or rec[0] < best[1][0]:
                    best = (a, rec)
            a, (aff, score, pct) = best
            out[p] = {"allele": a, "affinity_nM": aff, "presentation_score": score, "presentation_pct": pct}
        return out


def build_table(pool: list[dict], say=print) -> tuple[dict, dict]:
    from app.vaccine import predictor  # noqa: PLC0415

    real = predictor.load_default()
    peps = pool_peptides(pool)
    alleles = [a for loc in PANEL.values() for a in loc if real.supported(a)]
    say(f"predicting {len(peps)} peptides x {len(alleles)} alleles with {real.name}")
    table: dict[str, dict] = {}
    t0 = time.time()
    for n, a in enumerate(alleles, 1):
        got = real.predict(peps, [a])
        table[a] = {p: (r["affinity_nM"], r["presentation_score"], r["presentation_pct"]) for p, r in got.items()}
        say(f"  {a} ({n}/{len(alleles)}, {time.time() - t0:.0f}s)")
    check = check_equivalence(real, table, peps)
    return table, {"predictor": real.name, "alleles": alleles, "peptides": len(peps), "equivalence": check}


def check_equivalence(real, table: dict, peps: list[str], trials: int = 40, seed: int = 5) -> dict:
    """The lookup must give the real multi-allele answer; compare on random genotypes before trusting 10,000 runs."""
    rng = random.Random(seed)
    look = Lookup(table, "lookup")
    alleles = sorted(table)
    worst_aff = worst_pct = 0.0
    same_allele = total = 0
    for _ in range(trials):
        geno = rng.sample(alleles, 6)
        sample = rng.sample(peps, 40)
        a, b = real.predict(sample, geno), look.predict(sample, geno)
        for p in sample:
            total += 1
            same_allele += a[p]["allele"] == b[p]["allele"]
            worst_aff = max(worst_aff, abs(a[p]["affinity_nM"] - b[p]["affinity_nM"]) / max(a[p]["affinity_nM"], 1))
            worst_pct = max(worst_pct, abs(a[p]["presentation_pct"] - b[p]["presentation_pct"]))
    return {"compared": total, "same_best_allele": round(same_allele / total, 4), "max_relative_affinity_diff": round(worst_aff, 4), "max_percentile_diff": round(worst_pct, 4),
            "ok": same_allele / total > 0.995 and worst_aff < 0.02 and worst_pct < 0.05}


# ------------------------------------------------------------------------------------------------ scenarios
def make_scenario(i: int, seed: int, pool: list[dict], profile: dict, alleles: list[str]) -> dict:
    rng = random.Random(f"{seed}:{i}")
    burden = int(min(len(pool), max(5, rng.lognormvariate(math.log(profile["median_burden"]), profile["burden_sigma"]))))
    purity = rng.uniform(*profile["purity"])
    rows, germline = [], {}
    for k in rng.sample(range(len(pool)), burden):
        pv = pool[k]
        inherited = rng.random() < profile["germline_frac"]
        if inherited:
            vaf, normal = rng.uniform(0.4, 0.6), rng.uniform(0.4, 0.6)
        else:
            frac = 1.0 if rng.random() > profile["subclonal_frac"] else rng.uniform(0.15, 0.7)
            vaf, normal = purity / 2 * frac * rng.uniform(0.8, 1.2), 0.0
        depth = max(3, int(rng.lognormvariate(math.log(profile["depth_median"]), 0.45)))
        vaf = min(max(vaf + rng.gauss(0, math.sqrt(max(vaf * (1 - vaf), 1e-4) / depth)), 0.0), 1.0)
        tpm = 0.0 if rng.random() < profile["silent_frac"] else rng.lognormvariate(math.log(profile["median_tpm"]), 1.0)
        rows.append({"id": pv["id"], "gene": pv["gene"], "protein_change": pv["protein_change"], "consequence": "missense_variant", "vaf": round(vaf, 4),
                     "depth": depth, "normal_vaf": round(normal, 4), "tpm": round(tpm, 2), "wt_window": pv["wt_window"], "wt_start": 1})
        germline[pv["id"]] = inherited
    geno = [rng.choice(_of_locus(alleles, loc)) for loc in ("A", "A", "B", "B", "C", "C")]
    panel_rows = [dict(r, tpm=None, normal_vaf=None) for r in rows if rng.random() < profile["panel_frac"]]
    return {"i": i, "burden": burden, "purity": round(purity, 3), "hla": geno, "germline": germline,
            "views": {"full": rows, "no_rna": [dict(r, tpm=None) for r in rows], "no_normal": [dict(r, normal_vaf=None) for r in rows], "panel_only": panel_rows}}


def _of_locus(alleles: list[str], locus: str) -> list[str]:
    return [a for a in alleles if a.startswith(f"HLA-{locus}*")]


def measure(result: dict | None, germline: dict, n_in: int) -> dict:
    if result is None:
        return {"in": n_in, "cands": 0, "selected": 0, "strong": 0, "strong_v": 0, "tierA": 0, "top": 0.0, "top5": 0.0, "germline_selected": 0, "genes": 0}
    sel = result["selected"]
    top = [c["score"] for c in sel]
    return {"in": n_in, "cands": len(result["candidates"]), "selected": len(sel), "strong": sum(1 for c in sel if c["presentation_pct"] <= result["params"]["strong_pct"]),
            "strong_v": len({c["variant_id"] for c in result["candidates"] if c["presentation_pct"] <= result["params"]["strong_pct"]}),
            "tierA": result["tiers"]["A"], "top": top[0] if top else 0.0, "top5": round(sum(top[:5]) / max(len(top[:5]), 1), 3),
            "germline_selected": sum(1 for c in sel if germline.get(c["variant_id"])), "genes": len({c["gene"] for c in sel})}


_W: dict = {}


def _init(table_path: str, seed: int, profile: dict) -> None:
    with open(table_path, "rb") as f:
        table = pickle.load(f)
    _W.update(look=Lookup(table, "lookup"), alleles=sorted(table), seed=seed, profile=profile, pool=make_pool(), params=Params())


def run_scenario(i: int) -> dict:
    sc = make_scenario(i, _W["seed"], _W["pool"], _W["profile"], _W["alleles"])
    out = {"i": i, "burden": sc["burden"], "purity": sc["purity"], "hla": sc["hla"], "views": {}}
    for view, rows in sc["views"].items():
        try:
            res = pipeline.execute(rows, sc["hla"], _W["params"], _W["look"]) if rows else None
        except pipeline.Blocked:
            res = None
        out["views"][view] = measure(res, sc["germline"], len(rows))
    return out


def _chunk(idx: list[int]) -> list[dict]:
    return [run_scenario(i) for i in idx]


# ------------------------------------------------------------------------------------------------ summary
def _pct(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return float(s[min(len(s) - 1, int(q * len(s)))])


def summarize(rows: list[dict]) -> dict:
    out: dict = {"scenarios": len(rows), "views": {}, "burden_bins": [], "alleles": [], "paired": {}}
    for v in VIEWS:
        m = [r["views"][v] for r in rows]
        strong = [x["strong_v"] for x in m]
        out["views"][v] = {
            "label": VIEW_LABEL[v], "n": len(m),
            "strong_p10": _pct(strong, 0.1), "strong_median": _pct(strong, 0.5), "strong_p90": _pct(strong, 0.9),
            "selected_median": _pct([x["selected"] for x in m], 0.5),
            "p_strong_ge": {str(k): round(sum(1 for s in strong if s >= k) / max(len(m), 1), 4) for k in (1, 3, 5, 10, 20)},
            "p_none": round(sum(1 for x in m if x["selected"] == 0) / max(len(m), 1), 4),
            "tierA_median": _pct([x["tierA"] for x in m], 0.5), "p_tierA_ge3": round(sum(1 for x in m if x["tierA"] >= 3) / max(len(m), 1), 4),
            "top_score_median": round(_pct([x["top"] for x in m], 0.5), 2),
            "germline_selected_mean": round(sum(x["germline_selected"] for x in m) / max(len(m), 1), 3),
            "median_genes": _pct([x["genes"] for x in m], 0.5),
        }
    edges = [(5, 20), (20, 50), (50, 100), (100, 200), (200, 10**6)]
    for lo, hi in edges:
        sub = [r for r in rows if lo <= r["burden"] < hi]
        if not sub:
            continue
        full = [r["views"]["full"]["strong_v"] for r in sub]
        panel = [r["views"]["panel_only"]["strong_v"] for r in sub]
        out["burden_bins"].append({"label": f"{lo}–{hi - 1}" if hi < 10**6 else f"{lo}+", "n": len(sub), "full_strong_median": _pct(full, 0.5),
                                   "p_full_strong_ge3": round(sum(1 for s in full if s >= 3) / len(sub), 4), "p_full_none": round(sum(1 for r in sub if r["views"]["full"]["selected"] == 0) / len(sub), 4),
                                   "p_panel_strong_ge1": round(sum(1 for s in panel if s >= 1) / len(sub), 4)})
    overall = sum(r["views"]["full"]["strong_v"] for r in rows) / max(len(rows), 1)
    counts: dict[str, list[int]] = {}
    for r in rows:
        for a in set(r["hla"]):
            counts.setdefault(a, []).append(r["views"]["full"]["strong_v"])
    for a, xs in counts.items():
        if len(xs) >= 30:
            out["alleles"].append({"allele": a, "n": len(xs), "mean_strong": round(sum(xs) / len(xs), 2), "delta_vs_all": round(sum(xs) / len(xs) - overall, 2)})
    out["alleles"].sort(key=lambda d: -d["delta_vs_all"])
    full = out["views"]["full"]
    pair = lambda v, key: round(sum(r["views"][v][key] - r["views"]["full"][key] for r in rows) / max(len(rows), 1), 3)  # noqa: E731
    out["paired"] = {
        "no_rna_selected_change": pair("no_rna", "selected"), "no_rna_germline_change": pair("no_rna", "germline_selected"),
        "no_normal_germline_change": pair("no_normal", "germline_selected"), "no_normal_selected_change": pair("no_normal", "selected"),
        "panel_strong_change": pair("panel_only", "strong_v"), "full_mean_strong": round(overall, 3), "full_p_ge3": full["p_strong_ge"]["3"],
    }
    return out


def history(rows_path: Path) -> list[dict]:
    if not rows_path.exists():
        return []
    out = []
    for line in rows_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _write(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj), encoding="utf-8")
    os.replace(tmp, path)


def config_key(n: int, seed: int, profile: dict) -> str:
    return hashlib.sha256(json.dumps({"seed": seed, "profile": profile, "pool": POOL_SIZE, "v": pipeline.PIPELINE_VERSION, "params": Params().as_dict()}, sort_keys=True).encode()).hexdigest()[:12]


def run(n: int, workers: int, seed: int, profile: dict, flush: int = 200) -> None:
    d = cohort_dir()
    status_path, rows_path, table_path, stop = d / "status.json", d / "scenarios.jsonl", d / "table.pkl", d / "STOP"
    stop.unlink(missing_ok=True)
    key = config_key(n, seed, profile)
    started = time.time()

    def st(state: str, **kw) -> None:
        _write(status_path, {"state": state, "pid": os.getpid(), "heartbeat": time.time(), "started": started, "target": n, "seed": seed, "key": key, "profile": profile, **kw})

    try:
        prior = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
        resumed = prior.get("key") == key and rows_path.exists()
        if not resumed:
            rows_path.unlink(missing_ok=True)
            (d / "summary.json").unlink(missing_ok=True)
        meta = prior.get("meta") if resumed else None
        if not (resumed and table_path.exists() and meta):
            st("building", message="Predicting binding for the synthetic mutation pool (a few minutes, once)", done=0)
            table, meta = build_table(make_pool(), say=lambda s: st("building", message=s, done=0))
            with open(table_path, "wb") as f:
                pickle.dump(table, f, protocol=pickle.HIGHEST_PROTOCOL)
            del table
            if not meta["equivalence"]["ok"]:
                st("failed", message="The lookup table did not reproduce the real predictor; no scenarios were run.", meta=meta, done=0)
                return
        done_idx = {r["i"] for r in history(rows_path)}
        todo = [i for i in range(n) if i not in done_idx]
        chunks = [todo[k:k + 25] for k in range(0, len(todo), 25)]
        done = len(done_idx)
        st("running", message="Running scenarios", done=done, meta=meta)
        last = time.time()
        with mp.get_context("spawn").Pool(workers, initializer=_init, initargs=(str(table_path), seed, profile)) as pool, open(rows_path, "a", encoding="utf-8") as out:
            for res in pool.imap_unordered(_chunk, chunks):
                for r in res:
                    out.write(json.dumps(r) + "\n")
                out.flush()
                done += len(res)
                if time.time() - last > 3:
                    last = time.time()
                    elapsed = max(time.time() - started, 1)
                    st("running", message="Running scenarios", done=done, meta=meta, rate=round((done - len(done_idx)) / elapsed, 2))
                if stop.exists():
                    pool.terminate()
                    rows = history(rows_path)
                    _write(d / "summary.json", {"complete": False, **summarize(rows), "meta": meta})
                    st("stopped", message=f"Stopped early at {len(rows)} scenarios; results so far are saved and the run can be resumed.", done=len(rows), meta=meta)
                    return
        rows = history(rows_path)
        summ = {"complete": len(rows) >= n, **summarize(rows), "meta": meta, "profile": profile, "seed": seed, "pipeline": pipeline.PIPELINE_VERSION, "seconds": round(time.time() - started, 1)}
        summ["hash"] = hashlib.sha256(json.dumps({k: v for k, v in summ.items() if k != "seconds"}, sort_keys=True).encode()).hexdigest()[:12]
        _write(d / "summary.json", summ)
        st("done", message=f"Finished {len(rows)} scenarios", done=len(rows), meta=meta)
    except Exception as exc:  # noqa: BLE001 - the status file is how the app learns about it
        st("failed", message=f"{type(exc).__name__}: {exc}", done=0)
        raise


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--n", type=int, default=10000)
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4) // 3))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--profile", default="")
    a = ap.parse_args()
    profile = {**DEFAULT_PROFILE, **(json.loads(Path(a.profile).read_text(encoding="utf-8")) if a.profile else {})}
    run(a.n, a.workers, a.seed, profile)


if __name__ == "__main__":
    main()

