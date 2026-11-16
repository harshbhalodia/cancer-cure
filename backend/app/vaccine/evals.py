"""Evals for the vaccine pipeline.

What these show: the gates do what they say (against planted ground truth), the selection is deterministic and replayable, the
ranking does not depend on input order, tightening a threshold never adds candidates, the result really depends on the HLA type,
the predictor recovers published epitopes, and the dossier makes no efficacy claim.

What they do NOT show: that a selected peptide will provoke a useful immune response in a patient. That needs laboratory and
clinical evidence no software check can supply. A passing suite means the software behaves as documented.
"""
from __future__ import annotations

import random
import re

from app.vaccine import dossier, pipeline, synth
from app.vaccine.pipeline import Blocked, Params
from app.vaccine.predictor import Predictor

# published epitopes, used as positive controls for the predictor (verify against IEDB when reporting)
CONTROLS = [
    ("GILGFVFTL", "HLA-A*02:01", True, "influenza M1 58-66"),
    ("NLVPMVATV", "HLA-A*02:01", True, "CMV pp65 495-503"),
    ("VVVGADGVGK", "HLA-A*11:01", True, "KRAS G12D 9-mer (published neoepitope)"),
    ("GADGVGKSAL", "HLA-C*08:02", True, "KRAS G12D 10-mer (published neoepitope)"),
    ("GILGFVFTL", "HLA-A*11:01", False, "wrong allele for this epitope"),
]
CLAIMS = re.compile(r"\b(will cure|guarantee\w*|proven (to )?(work|effective)|safe and effective|effective vaccine|prevent(s)? recurrence)\b", re.I)


def _rows(seed: int = 7) -> tuple[list[dict], list[str], dict[int, str]]:
    rows, alleles, truth = synth.make(seed)
    out, tags = [], {}
    for i, r in enumerate(rows, start=1):
        r = dict(r)
        r["id"] = i
        tags[i] = truth[f"{r['gene']} {r['protein_change']}"]
        out.append(r)
    return out, alleles, tags


def _run(rows, alleles, predictor, **overrides) -> dict:
    return pipeline.execute(rows, alleles, Params().from_dict(overrides) if overrides else Params(), predictor, dataset="synthetic")


def _check(name: str, passed: bool, detail: str, kind: str = "software") -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail, "kind": kind}


def run_all(predictor: Predictor, controls: bool = True) -> dict:
    rows, alleles, tags = _rows()
    base = _run(rows, alleles, predictor)
    checks: list[dict] = []

    # 1. gates against planted ground truth
    rej = {(r["variant_id"]): r["stage"] for r in base["rejected"] if r["stage"] != "presentation"}
    bad, wrong = 0, []
    for vid, tag in tags.items():
        want = synth.expected_stage(tag)
        got = rej.get(vid)
        if want is None:
            if got is not None:
                wrong.append(f"{tag} #{vid} rejected at {got}")
        else:
            bad += 1
            if got != want:
                wrong.append(f"{tag} #{vid}: expected {want}, got {got}")
    checks.append(_check("gates_match_planted_truth", not wrong, f"{len(tags)} planted variants ({bad} that must be rejected); " + ("all fates as planted" if not wrong else "; ".join(wrong))))

    # 2. every candidate really spans the mutation
    broken = [c["id"] for c in base["candidates"]
              if not (c["peptide"][c["offset"]] != c["wt_peptide"][c["offset"]] and c["peptide"][:c["offset"]] + c["peptide"][c["offset"] + 1:] == c["wt_peptide"][:c["offset"]] + c["wt_peptide"][c["offset"] + 1:])]
    checks.append(_check("peptides_differ_only_at_the_mutation", not broken, f"{len(base['candidates'])} candidate peptides checked" + (f"; broken: {broken[:3]}" if broken else "")))

    # 3-4. determinism and replay
    again = _run(rows, alleles, predictor)
    checks.append(_check("deterministic", again["result_hash"] == base["result_hash"], f"two runs: {base['result_hash'][:12]} / {again['result_hash'][:12]}"))
    rp = pipeline.replay(base)
    checks.append(_check("replay_reproduces_selection", rp["result_hash"] == base["result_hash"], f"replayed from recorded predictions: {rp['result_hash'][:12]} vs {base['result_hash'][:12]}"))

    # 5. order invariance
    shuffled = rows[:]
    random.Random(3).shuffle(shuffled)
    sh = _run(shuffled, alleles, predictor)
    checks.append(_check("input_order_does_not_matter", [c["id"] for c in sh["selected"]] == [c["id"] for c in base["selected"]], "variants shuffled; selection compared"))

    # 6. tightening a threshold never adds candidates
    strict = _run(rows, alleles, predictor, min_vaf=0.30, max_pres_pct=0.5)
    sub = {c["id"] for c in strict["candidates"]} <= {c["id"] for c in base["candidates"]}
    checks.append(_check("tighter_thresholds_never_add_candidates", sub, f"{len(base['candidates'])} candidates → {len(strict['candidates'])} with VAF ≥ 0.30 and percentile ≤ 0.5"))

    # 7. the result depends on the HLA type
    other = _run(rows, ["HLA-A*03:01", "HLA-A*26:01", "HLA-B*35:01", "HLA-B*57:01", "HLA-C*03:04", "HLA-C*06:02"], predictor)
    differs = [c["id"] for c in other["selected"]] != [c["id"] for c in base["selected"]]
    checks.append(_check("result_depends_on_hla", differs, f"{len(base['selected'])} selected with the first HLA set, {len(other['selected'])} with a different set; selections {'differ' if differs else 'are identical (suspicious)'}"))

    # 8. input hash changes when an input changes, not otherwise
    tweaked = [dict(r) for r in rows]
    tweaked[0]["vaf"] = (tweaked[0]["vaf"] or 0.3) + 0.01
    h_changed = _run(tweaked, alleles, predictor)["input_hash"] != base["input_hash"]
    checks.append(_check("input_hash_tracks_inputs", h_changed and again["input_hash"] == base["input_hash"], "a changed VAF changes the hash; a re-run does not"))

    # 9. refuses to run without what it needs
    blocked = []
    for label, args in (("no variants", ([], alleles)), ("no HLA", (rows, []))):
        try:
            pipeline.execute(*args, Params(), predictor)
            blocked.append(f"{label}: ran")
        except Blocked:
            pass
    checks.append(_check("refuses_without_variants_or_hla", not blocked, "; ".join(blocked) or "blocked with a clear message in both cases"))

    # 10. the dossier makes no efficacy claim and carries its warnings
    text = dossier.build(base, synthetic=True)
    ok = not CLAIMS.search(text) and "not a vaccine" in text and "SYNTHETIC" in text and "investigational" in text
    checks.append(_check("dossier_has_no_efficacy_claims_and_is_watermarked", ok, "disclaimer, synthetic watermark and limits present; no claim wording"))

    # 11. the predictor recovers published epitopes (real predictor only)
    if controls:
        miss = []
        for pep, allele, should, label in CONTROLS:
            if not predictor.supported(allele):
                continue
            pct = predictor.predict([pep], [allele])[pep]["presentation_pct"]
            if (pct <= 2.0) != should:
                miss.append(f"{label} on {allele}: percentile {pct:g}")
        checks.append(_check("predictor_recovers_published_epitopes", not miss, f"{len(CONTROLS)} literature controls (positive and negative)" + (": " + "; ".join(miss) if miss else ": all as expected"), kind="predictor"))
    passed = sum(c["passed"] for c in checks)
    return {"predictor": predictor.name, "passed": passed, "total": len(checks), "checks": checks, "funnel": base["stages"], "result_hash": base["result_hash"],
            "note": "These show the software behaves as documented. They do not show that any peptide will work as a vaccine."}
