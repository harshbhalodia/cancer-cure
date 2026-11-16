"""The vaccine workbench's glue to the database: your tumour data in, runs and dossiers out.

Patient data and synthetic demo data live in separate datasets and are never mixed.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import timezone

from sqlalchemy.orm import Session

from app.models import Case, Document, HlaAllele, Job, RefSeq, Setting, SomaticVariant, VaccineRun
from app.services import readiness
from app.vaccine import dossier, evals, ingest, peptides, pipeline, predictor, synth
from app.vaccine.pipeline import Blocked, Params

DATASETS = ("patient", "synthetic")
# tests (and other callers) may replace how the predictor is obtained
predictor_factory: Callable[[], predictor.Predictor] = predictor.load_default
predictor_available: Callable[[], bool] = predictor.available


# ------------------------------------------------------------------------------------ data in
def add_variants(db: Session, dataset: str, rows: list[dict], source: str = "") -> int:
    existing = {(v.gene, v.protein_change): v for v in db.query(SomaticVariant).filter_by(dataset=dataset)}
    added = 0
    for r in rows:
        key = (r["gene"], r["protein_change"])
        v = existing.get(key)
        if v is None:
            v = SomaticVariant(dataset=dataset, gene=r["gene"], protein_change=r["protein_change"])
            db.add(v)
            existing[key] = v
            added += 1
        for f in ("consequence", "vaf", "depth", "normal_vaf", "tpm", "wt_window", "wt_start", "source", "note"):
            if r.get(f) not in (None, ""):
                setattr(v, f, r[f])
        if source and not v.source:
            v.source = source
    db.commit()
    return added


def set_hla(db: Session, dataset: str, alleles: list[str], source: str = "") -> None:
    db.query(HlaAllele).filter_by(dataset=dataset).delete()
    for a in alleles:
        db.add(HlaAllele(dataset=dataset, allele=a, source=source))
    db.commit()


def clear(db: Session, dataset: str) -> None:
    db.query(SomaticVariant).filter_by(dataset=dataset).delete()
    db.query(HlaAllele).filter_by(dataset=dataset).delete()
    db.query(VaccineRun).filter_by(dataset=dataset).delete()
    db.commit()


def load_synthetic(db: Session) -> dict:
    clear(db, "synthetic")
    rows, alleles, _truth = synth.make()
    add_variants(db, "synthetic", rows, "synthetic test data")
    set_hla(db, "synthetic", alleles, "synthetic test data")
    return {"variants": len(rows), "hla": alleles}


def hla_from_case(db: Session) -> tuple[list[str], list[str]]:
    case = db.get(Case, 1)
    return ingest.parse_hla(case.hla_type if case else "")


# ------------------------------------------------------------------------------------ reference sequences
def ref_lookup(db: Session) -> Callable[[str], tuple[str, str] | None]:
    cache = {r.gene: (r.sequence, r.source) for r in db.query(RefSeq)}
    return lambda gene: cache.get(gene)


def missing_references(db: Session, dataset: str) -> list[str]:
    have = {r.gene for r in db.query(RefSeq)}
    return sorted({v.gene for v in db.query(SomaticVariant).filter_by(dataset=dataset) if not v.wt_window and v.gene not in have
                   and ingest.parse_protein_change(v.protein_change)})


def fetch_references(db: Session, dataset: str) -> dict:
    """Look up reference proteins for genes that need one. Only gene symbols are sent (to uniprot.org). Opt-in, never automatic."""
    out = {}
    for gene in missing_references(db, dataset):
        try:
            seq, source = peptides.fetch_reference(gene)
            db.add(RefSeq(gene=gene, sequence=seq, source=source))
            db.commit()
            out[gene] = source
        except Exception as exc:  # network down, unknown gene…
            db.rollback()
            out[gene] = f"failed: {exc}"
    return out


# ------------------------------------------------------------------------------------ running
def _variant_rows(db: Session, dataset: str) -> list[dict]:
    return [{"id": v.id, "gene": v.gene, "protein_change": v.protein_change, "consequence": v.consequence, "vaf": v.vaf, "depth": v.depth,
             "normal_vaf": v.normal_vaf, "tpm": v.tpm, "wt_window": v.wt_window, "wt_start": v.wt_start}
            for v in db.query(SomaticVariant).filter_by(dataset=dataset).order_by(SomaticVariant.id)]


def run(db: Session, dataset: str, params: dict | None = None, progress: Callable[[str], None] | None = None) -> VaccineRun:
    if dataset not in DATASETS:
        raise Blocked("Unknown dataset.")
    if not predictor_available():
        raise Blocked("The binding predictor is not installed (pip install mhcflurry, then mhcflurry-downloads fetch models_class1_presentation). "
                      "Without it nothing can be selected, and the app will not substitute a made-up score.")
    alleles = [h.allele for h in db.query(HlaAllele).filter_by(dataset=dataset).order_by(HlaAllele.id)]
    result = pipeline.execute(_variant_rows(db, dataset), alleles, Params.from_dict(params), predictor_factory(), ref_lookup(db), dataset, progress)
    row = VaccineRun(dataset=dataset, status="done", params=result["params"], input_hash=result["input_hash"], result_hash=result["result_hash"],
                     predictor=result["predictor"], result=result)
    db.add(row)
    db.commit()
    return row


def summary(row: VaccineRun | None) -> dict | None:
    if row is None:
        return None
    r = {k: v for k, v in row.result.items() if k not in ("predictions", "inputs")}
    return {"id": row.id, "dataset": row.dataset, "created_at": row.created_at.replace(tzinfo=row.created_at.tzinfo or timezone.utc).isoformat(), **r}


def latest(db: Session, dataset: str) -> VaccineRun | None:
    return db.query(VaccineRun).filter_by(dataset=dataset).order_by(VaccineRun.id.desc()).first()


def verify(db: Session, run_id: int) -> dict:
    row = db.get(VaccineRun, run_id)
    if row is None:
        raise LookupError("Run not found.")
    again = pipeline.replay(row.result)
    ok = again["result_hash"] == row.result_hash
    return {"ok": ok, "stored": row.result_hash, "replayed": again["result_hash"],
            "detail": "The selection was rebuilt from the stored inputs and recorded predictions and matches exactly." if ok else "The replay differs from the stored run."}


def dossier_text(db: Session, run_id: int, fmt: str = "md") -> str:
    row = db.get(VaccineRun, run_id)
    if row is None:
        raise LookupError("Run not found.")
    return dossier.to_json(row.result) if fmt == "json" else dossier.build(row.result, synthetic=row.dataset == "synthetic")


# ------------------------------------------------------------------------------------ the review board's facts
def facts_for(result: dict, dataset: str) -> str:
    """What the local-model reviewers are allowed to read: the computed run, as plain lines."""
    p = result["params"]
    lines = [f"Dataset: {'SYNTHETIC (a software test, not a real patient)' if dataset == 'synthetic' else 'the patient'}",
             f"Pipeline {result['pipeline_version']}; predictor: {result['predictor']}; result hash {result['result_hash'][:12]}",
             f"HLA class I alleles used: {', '.join(result['alleles_used'])}" + (f"; not supported: {', '.join(result['alleles_unsupported'])}" if result["alleles_unsupported"] else ""),
             f"Thresholds: VAF at least {p['min_vaf']}, depth at least {p['min_depth']}, expression at least {p['min_tpm']} TPM, presentation percentile at most {p['max_pres_pct']}",
             "Funnel: " + "; ".join(f"{s['name']} {s['in']} to {s['out']}" for s in result["stages"])]
    lines += [f"Warning: {w}" for w in result["warnings"]]
    lines.append("Selected candidates (best first):")
    for i, c in enumerate(result["selected"], 1):
        extra = (" recurrent hotspot (curated list);" if c["hotspot"] else "") + ("".join(f" caveat: {f};" for f in c["flags"]))
        lines.append(f"- #{i} {c['gene']} {c['change']}, peptide {c['peptide']} (wild-type {c['wt_peptide']}), {c['allele']}, affinity {c['affinity_nM']:g} nM, "
                     f"presentation percentile {c['presentation_pct']:g}, wild-type affinity {c['wt_affinity_nM']:g} nM, VAF {c['vaf'] if c['vaf'] is not None else 'unknown'}, "
                     f"expression {c['tpm'] if c['tpm'] is not None else 'unknown'} TPM, tier {c['tier']}, score {c['score']:g};{extra}")
    if not result["selected"]:
        lines.append("- (none passed all stages)")
    lines.append("Rejected:")
    lines += [f"- {r['gene']} {r['change']}: stage {r['stage']}, {r['reason']}" for r in result["rejected"][:20]]
    lines.append("Not handled by this pipeline: frameshifts, insertions or deletions, splice variants, fusions, self or cancer-testis antigens, class II.")
    return "\n".join(lines)


def board_facts(db: Session) -> str:
    row = latest(db, "patient") or latest(db, "synthetic")
    if row is None:
        return "(no candidate selection has been run yet)"
    return facts_for(row.result, row.dataset)


def board_check(db: Session, result: dict) -> dict:
    """Run the local-model board on a run and check it only cites genes, peptides and numbers that are in the facts."""
    import re  # noqa: PLC0415

    from app.services import advisors  # noqa: PLC0415

    facts = facts_for(result, result["dataset"])
    pack = advisors.load_packs().get("carecompanion.vaccine_board")
    if pack is None:
        return {"name": "local_model_memo_is_faithful", "passed": False, "detail": "the review pack is not available", "kind": "model"}
    run = advisors.run_pack(db, pack, facts_override={"vaccine": facts})
    text = run.markdown
    upper = facts.upper()
    peps = {t for t in re.findall(r"\b[ACDEFGHIKLMNPQRSTVWY]{8,11}\b", text) if t.upper() not in upper}
    genes = {t for t in re.findall(r"\bSYN\d{3}\b", text) if t not in facts}
    problems = []
    if run.used_fallback:
        problems.append("the model's draft failed the safety/number checks and the plain fallback was used (" + "; ".join(run.flags)[:160] + ")")
    if peps:
        problems.append("peptides not in the facts: " + ", ".join(sorted(peps)[:4]))
    if genes:
        problems.append("genes not in the facts: " + ", ".join(sorted(genes)[:4]))
    if "not a vaccine" not in text.lower():
        problems.append("the not-a-vaccine disclaimer is missing")
    return {"name": "local_model_memo_is_faithful", "passed": not problems, "kind": "model",
            "detail": "memo cites only genes, peptides and numbers present in the computed facts, and passes the safety lint" if not problems else "; ".join(problems)}


# ------------------------------------------------------------------------------------ evals
def run_evals(db: Session, include_board: bool = False) -> dict:
    if not predictor_available():
        raise Blocked("The binding predictor is not installed, so the evals cannot run.")
    pred = predictor_factory()
    report = evals.run_all(pred)
    if include_board:
        rows, alleles, _ = evals._rows()
        base = pipeline.execute(rows, alleles, Params(), pred, dataset="synthetic")
        try:
            report["checks"].append(board_check(db, base))
        except Exception as exc:  # the local model may be offline
            report["checks"].append({"name": "local_model_memo_is_faithful", "passed": False, "kind": "model", "detail": f"could not run: {exc}"})
        report["passed"], report["total"] = sum(c["passed"] for c in report["checks"]), len(report["checks"])
    db.merge(Setting(key="vaccine:last_eval", value=json.dumps(report)))
    db.commit()
    return report


def last_eval(db: Session) -> dict | None:
    row = db.get(Setting, "vaccine:last_eval")
    return json.loads(row.value) if row and row.value else None


# ------------------------------------------------------------------------------------ the page
def _counts(db: Session, dataset: str) -> dict:
    variants = db.query(SomaticVariant).filter_by(dataset=dataset).all()
    return {"variants": len(variants), "hla": [h.allele for h in db.query(HlaAllele).filter_by(dataset=dataset).order_by(HlaAllele.id)],
            "with_normal": sum(v.normal_vaf is not None for v in variants), "with_rna": sum(v.tpm is not None for v in variants),
            "need_reference": missing_references(db, dataset), "sources": sorted({v.source for v in variants if v.source})[:5]}


def workbench(db: Session) -> dict:
    ready = readiness.readiness(db)
    decision = next((d for d in ready["decisions"] if d["id"] == "vaccine_feasibility"), None)
    items = {i["key"]: i for i in ready["requirements"]}
    asks = [{"key": k, "label": items[k]["label"], "status": items[k]["status"], "met": items[k]["met"], "why": items[k]["why"], "ask": items[k]["ask"]}
            for k in ("ngs_tumour", "ngs_normal", "tumour_rna", "hla") if k in items]
    runs = db.query(VaccineRun).order_by(VaccineRun.id.desc()).limit(10).all()
    jobs = [{"id": j.id, "kind": j.kind, "status": j.status, "detail": (j.result or {}).get("detail", ""), "error": j.error}
            for j in db.query(Job).filter(Job.kind.in_(("vaccine", "vaccine_eval")), Job.status.in_(("queued", "running", "failed"))).order_by(Job.id.desc()).limit(3)]
    return {
        "predictor": {"available": predictor_available(), "name": "MHCflurry class I presentation"},
        "readiness": decision, "asks": asks, "patient": _counts(db, "patient"), "synthetic": _counts(db, "synthetic"),
        "runs": [{"id": r.id, "dataset": r.dataset, "created_at": r.created_at.isoformat(), "selected": len(r.result.get("selected", [])), "tiers": r.result.get("tiers"),
                  "result_hash": r.result_hash[:12]} for r in runs],
        "latest": {"patient": summary(latest(db, "patient")), "synthetic": summary(latest(db, "synthetic"))},
        "eval": last_eval(db), "jobs": jobs,
        "case_hla": hla_from_case(db)[0],
    }
