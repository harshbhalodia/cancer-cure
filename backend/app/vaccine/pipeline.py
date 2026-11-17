"""Candidate-antigen selection for a personalised vaccine, as an auditable pipeline.

Stages (each records what went in, what came out, and the reason for every rejection, in the spirit of the yash
project's explicit gates and provenance):

  1 variants   simple amino-acid substitutions only (frameshift/indel/splice/fusion are NOT handled yet)
  2 quality    depth and tumour VAF (subclonal or noisy calls are dropped)
  3 germline   present in the matched normal means inherited, so not a tumour target
  4 expression tumour RNA (TPM) must show the gene is switched on
  5 reference  the stated wild-type residue must match the reference protein (wrong isoform/build is dropped)
  6 presentation  peptides covering the mutation are scored by a real predictor against the patient's own HLA type
  7 selection  transparent score, evidence tier, at most N candidates, at most k per variant

Everything is deterministic: same inputs + parameters + predictor numbers give the same selection, and a stored run
can be replayed from its recorded predictions and must match byte for byte. The output is a research shortlist for the
treating team, not a vaccine and not an instruction to make or take one.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from app.vaccine import ingest, peptides
from app.vaccine.predictor import Predictor, Replay

PIPELINE_VERSION = "vax-0.1"

# Recurrent hotspot positions from the literature: a starter list to be verified against COSMIC / OncoKB, used only as a small, logged bonus.
HOTSPOTS: dict[str, set[int]] = {
    "KRAS": {12, 13, 61, 146}, "NRAS": {12, 13, 61}, "HRAS": {12, 13, 61}, "BRAF": {600}, "PIK3CA": {542, 545, 1047}, "IDH1": {132},
    "TP53": {175, 245, 248, 249, 273, 282}, "EGFR": {719, 790, 858, 861}, "CTNNB1": {33, 37, 41, 45}, "AKT1": {17}, "FGFR3": {249, 373},
}


@dataclass
class Params:
    min_vaf: float = 0.10
    min_depth: int = 10
    min_tpm: float = 1.0
    max_normal_vaf: float = 0.02
    max_pres_pct: float = 2.0  # presentation percentile at or below which a peptide counts as likely presented
    strong_pct: float = 0.5
    lengths: tuple = (8, 9, 10, 11)
    n_select: int = 12
    per_variant: int = 2
    w_presentation: float = 0.40
    w_affinity: float = 0.15
    w_differential: float = 0.15
    w_vaf: float = 0.15
    w_expression: float = 0.15
    unknown_value: float = 0.3  # credit given when VAF or expression is not known
    hotspot_points: float = 5.0

    def as_dict(self) -> dict:
        d = asdict(self)
        d["lengths"] = list(self.lengths)
        return d

    @classmethod
    def from_dict(cls, d: dict | None) -> "Params":
        base = cls()
        for k, v in (d or {}).items():
            if k not in base.as_dict():
                raise ValueError(f"Unknown pipeline parameter: {k}")
            if k == "lengths":
                if not isinstance(v, (list, tuple)) or not v or any(type(n) is not int or n not in (8, 9, 10, 11) for n in v):
                    raise ValueError("Peptide lengths must be a nonempty list of integers from 8 to 11.")
                base.lengths = tuple(sorted(set(v)))
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"{k} must be a finite number.")
            current = getattr(base, k)
            if isinstance(current, int) and int(v) != v:
                raise ValueError(f"{k} must be a whole number.")
            setattr(base, k, type(current)(v))
        for key in ("min_vaf", "max_normal_vaf", "unknown_value"):
            if not 0 <= getattr(base, key) <= 1:
                raise ValueError(f"{key} must be between 0 and 1.")
        if base.min_depth < 1 or base.min_tpm < 0 or not 1 <= base.n_select <= 100 or not 1 <= base.per_variant <= 100:
            raise ValueError("Depth must be positive, TPM nonnegative, and selection limits between 1 and 100.")
        if not 0 < base.max_pres_pct <= 100 or not 0 <= base.strong_pct <= base.max_pres_pct:
            raise ValueError("Presentation percentiles must be ordered between 0 and 100, with a positive maximum.")
        weights = [base.w_presentation, base.w_affinity, base.w_differential, base.w_vaf, base.w_expression]
        if any(w < 0 for w in weights) or not math.isclose(sum(weights), 1.0, abs_tol=1e-6) or not 0 <= base.hotspot_points <= 100:
            raise ValueError("Nonnegative ranking weights must sum to 1, and hotspot points must be between 0 and 100.")
        return base


class Blocked(Exception):
    """The pipeline cannot run (missing inputs or predictor). The message says exactly what is missing."""


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _hash(obj) -> str:
    return hashlib.sha256(_canon(obj).encode()).hexdigest()


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ------------------------------------------------------------------------------------------------ gates
def gate_variants(variants: list[dict], params: Params, ref: Callable[[str], tuple[str, str] | None]) -> tuple[list[dict], list[dict], dict]:
    """Returns (passed, rejected, reference_info). `passed` items carry their peptide pairs and any caveat flags."""
    rejected: list[dict] = []
    passed: list[dict] = []
    refs: dict[str, dict] = {}
    resolved: dict[int, dict] = {}

    def reject(v: dict, stage: str, reason: str) -> None:
        rejected.append({"variant_id": v["id"], "gene": v["gene"], "change": v["protein_change"], "stage": stage, "reason": reason})

    stage_counts = {"variants": [len(variants), 0], "quality": [0, 0], "germline": [0, 0], "expression": [0, 0], "reference": [0, 0]}
    stage1 = []
    for v in variants:
        parsed = ingest.parse_protein_change(v["protein_change"])
        if parsed is None:
            reject(v, "variants", "not a simple amino-acid substitution (frameshift, indel, stop, splice and fusion targets need transcript-level translation and are not supported yet)")
        elif "synonymous" in (v.get("consequence") or "").lower():
            reject(v, "variants", "synonymous change: the protein is unchanged")
        else:
            stage1.append((v, parsed))
    stage_counts["variants"][1] = len(stage1)

    stage2 = []
    stage_counts["quality"][0] = len(stage1)
    for v, parsed in stage1:
        if v.get("depth") is not None and v["depth"] < params.min_depth:
            reject(v, "quality", f"depth {v['depth']} is below {params.min_depth}")
        elif v.get("vaf") is not None and v["vaf"] < params.min_vaf:
            reject(v, "quality", f"tumour VAF {v['vaf']:.3f} is below {params.min_vaf:g} (subclonal or noise)")
        else:
            stage2.append((v, parsed))
    stage_counts["quality"][1] = len(stage2)

    stage3 = []
    stage_counts["germline"][0] = len(stage2)
    for v, parsed in stage2:
        if v.get("normal_vaf") is not None and v["normal_vaf"] >= params.max_normal_vaf:
            reject(v, "germline", f"also seen in the matched normal (VAF {v['normal_vaf']:.3f}), so likely inherited")
        else:
            stage3.append((v, parsed))
    stage_counts["germline"][1] = len(stage3)

    stage4 = []
    stage_counts["expression"][0] = len(stage3)
    for v, parsed in stage3:
        if v.get("tpm") is not None and v["tpm"] < params.min_tpm:
            reject(v, "expression", f"expression {v['tpm']:g} TPM is below {params.min_tpm:g}, so the mutant protein is unlikely to be made")
        else:
            stage4.append((v, parsed))
    stage_counts["expression"][1] = len(stage4)

    stage_counts["reference"][0] = len(stage4)
    for v, (wt, pos, mut) in stage4:
        window, start = v.get("wt_window") or "", int(v.get("wt_start") or 1)
        if not window:
            got = ref(v["gene"])
            if got is None:
                reject(v, "reference", f"no reference protein sequence for {v['gene']} (look it up, or supply one with the variant)")
                continue
            window, source = got
            start = 1
            refs[v["gene"]] = {"source": source, "sha": peptides.sequence_hash(window)}
        i = pos - start
        lo = max(0, i - max(params.lengths))
        trimmed = window[lo: i + max(params.lengths) + 1] if 0 <= i < len(window) else window
        resolved[v["id"]] = {"wt_window": trimmed, "wt_start": start + lo if 0 <= i < len(window) else start}
        try:
            pairs = peptides.peptides_for(window, start, pos, wt, mut, params.lengths)
        except ValueError as exc:
            reject(v, "reference", str(exc))
            continue
        flags = []
        if v.get("normal_vaf") is None:
            flags.append("no matched normal: inherited variants cannot be excluded")
        if v.get("tpm") is None:
            flags.append("expression unknown")
        if v.get("vaf") is None:
            flags.append("VAF unknown")
        passed.append({**v, "wt": wt, "pos": pos, "mut": mut, "pairs": pairs, "flags": flags})
    stage_counts["reference"][1] = len(passed)
    stages = [{"name": k, "in": a, "out": b} for k, (a, b) in stage_counts.items()]
    return passed, rejected, {"refs": refs, "stages": stages, "resolved": resolved}


# ------------------------------------------------------------------------------------------------ scoring
def score_candidate(c: dict, params: Params) -> tuple[float, dict]:
    pres = _clamp(1 - c["presentation_pct"] / params.max_pres_pct) if params.max_pres_pct else 0.0
    aff = _clamp((math.log10(5000) - math.log10(max(c["affinity_nM"], 1))) / (math.log10(5000) - math.log10(10)))
    diff = _clamp(math.log10(max(c["wt_affinity_nM"], 1) / max(c["affinity_nM"], 1)) / 2)
    vaf = params.unknown_value if c["vaf"] is None else _clamp(c["vaf"] / 0.5)
    expr = params.unknown_value if c["tpm"] is None else _clamp(math.log10(1 + c["tpm"]) / math.log10(51))
    comps = {"presentation": pres, "affinity": aff, "differential": diff, "vaf": vaf, "expression": expr}
    weighted = (params.w_presentation * pres + params.w_affinity * aff + params.w_differential * diff + params.w_vaf * vaf + params.w_expression * expr)
    total = (100 - params.hotspot_points) * weighted + (params.hotspot_points if c["hotspot"] else 0.0)
    return round(total, 3), {k: round(v, 4) for k, v in comps.items()}


def tier_for(c: dict, params: Params) -> str:
    strong = c["presentation_pct"] <= params.strong_pct
    complete = not c["flags"]
    if strong and complete:
        return "A"
    if strong or complete:
        return "B"
    return "C"


def select(cands: list[dict], params: Params) -> list[dict]:
    ordered = sorted(cands, key=lambda c: (-c["score"], c["peptide"], c["variant_id"]))
    chosen: list[dict] = []
    per: dict[int, list[str]] = {}
    for c in ordered:
        if len(chosen) >= params.n_select:
            break
        mine = per.setdefault(c["variant_id"], [])
        if len(mine) >= params.per_variant or any(c["peptide"] in p or p in c["peptide"] for p in mine):
            continue  # nested peptides from the same mutation add nothing
        mine.append(c["peptide"])
        chosen.append(c)
    return chosen


# ------------------------------------------------------------------------------------------------ the run
class Recording:
    """Wraps a predictor and records every number it returns, keyed by the allele set queried, for later replay."""

    def __init__(self, inner: Predictor) -> None:
        self.inner, self.name, self.recorded = inner, inner.name, {}

    def supported(self, allele: str) -> bool:
        return self.inner.supported(allele)

    def predict(self, peps: list[str], alleles: list[str]) -> dict[str, dict]:
        out = self.inner.predict(peps, alleles)
        key = "+".join(sorted(alleles))
        for p, rec in out.items():
            self.recorded[f"{key}|{p}"] = rec
        return out


def execute(variants: list[dict], alleles: list[str], params: Params, predictor: Predictor,
            ref: Callable[[str], tuple[str, str] | None] = lambda g: None, dataset: str = "patient",
            progress: Callable[[str], None] | None = None) -> dict:
    say = progress or (lambda _s: None)
    if not variants:
        raise Blocked("No tumour mutations have been added yet.")
    if not alleles:
        raise Blocked("No HLA type has been added yet; presentation cannot be predicted without it.")
    usable = [a for a in alleles if predictor.supported(a)]
    unsupported = [a for a in alleles if a not in usable]
    if not usable:
        raise Blocked("None of the HLA alleles are supported by the predictor.")
    warnings = []
    if unsupported:
        warnings.append("Predictor does not support: " + ", ".join(unsupported) + "; they were left out.")
    if len(usable) < 3:
        warnings.append(f"Only {len(usable)} HLA class I allele(s) usable; a full type has up to six, so coverage is incomplete.")

    keys = ("id", "gene", "protein_change", "consequence", "vaf", "depth", "normal_vaf", "tpm", "wt_window", "wt_start")
    references = {gene: ref(gene) for gene in sorted({v["gene"] for v in variants if not v.get("wt_window") and ingest.parse_protein_change(v["protein_change"])})}
    research_inputs = {
        "variants_all": [{k: v.get(k) for k in keys} for v in sorted(variants, key=lambda v: v["id"])],
        "alleles": sorted(alleles),
        "refs": {gene: {"source": value[1], "sha": peptides.sequence_hash(value[0])} if value else {"missing": True} for gene, value in references.items()},
    }
    say("gating variants")
    passed, rejected, info = gate_variants(variants, params, lambda gene: references.get(gene))
    rec = Recording(predictor)
    cands: list[dict] = []
    if passed:
        say("scoring peptides against the patient's HLA type")
        mut_peps = sorted({p["mut"] for v in passed for p in v["pairs"]})
        mut_pred = rec.predict(mut_peps, usable)
        by_allele: dict[str, set[str]] = {}
        for v in passed:
            for p in v["pairs"]:
                by_allele.setdefault(mut_pred[p["mut"]]["allele"], set()).add(p["wt"])
        wt_pred = {a: rec.predict(sorted(ws), [a]) for a, ws in sorted(by_allele.items())}
        for v in passed:
            best_pct = None
            for p in v["pairs"]:
                mp = mut_pred[p["mut"]]
                best_pct = mp["presentation_pct"] if best_pct is None else min(best_pct, mp["presentation_pct"])
                if mp["presentation_pct"] > params.max_pres_pct:
                    continue
                wp = wt_pred[mp["allele"]][p["wt"]]
                c = {
                    "variant_id": v["id"], "gene": v["gene"], "change": v["protein_change"], "peptide": p["mut"], "wt_peptide": p["wt"], "length": p["length"],
                    "offset": p["offset"], "allele": mp["allele"], "affinity_nM": mp["affinity_nM"], "presentation_pct": mp["presentation_pct"],
                    "presentation_score": mp["presentation_score"], "wt_affinity_nM": wp["affinity_nM"], "wt_presentation_pct": wp["presentation_pct"],
                    "vaf": v.get("vaf"), "tpm": v.get("tpm"), "normal_vaf": v.get("normal_vaf"), "depth": v.get("depth"),
                    "hotspot": v["pos"] in HOTSPOTS.get(v["gene"], set()), "flags": list(v["flags"]),
                }
                if wp["presentation_pct"] <= params.max_pres_pct:
                    c["flags"].append("the wild-type peptide is also predicted to be presented, so tolerance may blunt the response")
                c["score"], c["components"] = score_candidate(c, params)
                c["tier"] = tier_for(c, params)
                c["id"] = f"{v['gene']}-{v['protein_change']}-{p['mut']}"
                cands.append(c)
            if not any(c["variant_id"] == v["id"] for c in cands):
                rejected.append({"variant_id": v["id"], "gene": v["gene"], "change": v["protein_change"], "stage": "presentation",
                                 "reason": f"no peptide is predicted to be presented by this patient's HLA type (best percentile {best_pct:g}, limit {params.max_pres_pct:g})"})
    stages = info["stages"] + [{"name": "presentation", "in": len(passed), "out": len({c["variant_id"] for c in cands})}]
    say("selecting")
    selected = select(cands, params)
    stages.append({"name": "selection", "in": len(cands), "out": len(selected)})

    all_vars = []
    for v in sorted(variants, key=lambda d: d["id"]):
        row = {k: v.get(k) for k in keys}
        row.update(info["resolved"].get(v["id"], {}))  # the exact reference stretch the run used, so it can be replayed
        all_vars.append(row)
    inputs = {"variants_all": all_vars, "alleles": sorted(alleles)}
    rejected.sort(key=lambda r: (r["variant_id"], r["stage"]))
    result = {
        "pipeline_version": PIPELINE_VERSION, "dataset": dataset, "params": params.as_dict(), "predictor": predictor.name, "alleles_used": sorted(usable),
        "alleles_unsupported": unsupported, "refs": info["refs"], "stages": stages, "rejected": rejected, "candidates": sorted(cands, key=lambda c: (-c["score"], c["id"])),
        "selected": selected, "warnings": warnings, "inputs": inputs, "research_inputs": research_inputs, "predictions": rec.recorded,
        "tiers": {t: sum(1 for c in selected if c["tier"] == t) for t in "ABC"},
    }
    result["input_hash"] = _hash({"inputs": inputs["variants_all"], "alleles": inputs["alleles"], "params": result["params"], "version": PIPELINE_VERSION, "refs": info["refs"]})
    result["result_hash"] = result_hash(result)
    return result


def result_hash(result: dict) -> str:
    """Hash of what the run decided, independent of storage order or timestamps."""
    return _hash({"selected": [(c["id"], c["score"], c["tier"], c["allele"]) for c in result["selected"]],
                  "rejected": [(r["variant_id"], r["stage"], r["reason"]) for r in result["rejected"]],
                  "stages": result["stages"], "candidates": [(c["id"], c["score"]) for c in result["candidates"]]})


def replay(result: dict) -> dict:
    """Re-run gating, scoring and selection from the stored inputs and recorded predictor numbers; no model is called."""
    params = Params.from_dict(result["params"])
    variants = [dict(v) for v in result["inputs"]["variants_all"]]
    return execute(variants, result["alleles_used"], params, Replay(result["predictions"], result["predictor"]), dataset=result["dataset"])
