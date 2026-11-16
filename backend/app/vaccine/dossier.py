"""The hand-off document: what the pipeline found, how, and what it cannot say. Markdown for people, JSON for machines."""
from __future__ import annotations

import json

DISCLAIMER = (
    "This is a computational research shortlist, not a vaccine and not medical advice. Individualised neoantigen vaccines are "
    "investigational: they can only be made and given by qualified teams under an approved clinical trial or regulatory pathway. "
    "Nothing here is a protocol for making, buying or taking a vaccine. Predictions identify peptides that may be presented by the "
    "patient's HLA type; they do not show that the peptide will provoke an effective immune response, and none has been tested in the patient."
)


def build(run: dict, synthetic: bool = False) -> str:
    p = run["params"]
    lines = []
    if synthetic:
        lines += ["> **SYNTHETIC DATA: this is a software test, not a patient. Do not use any of it clinically.**", ""]
    lines += [
        "# Candidate antigen shortlist (research dossier)", "",
        f"*Pipeline {run['pipeline_version']} · predictor: {run['predictor']} · input hash `{run['input_hash'][:16]}` · result hash `{run['result_hash'][:16]}`*", "",
        f"> {DISCLAIMER}", "",
        "## What went in",
        f"- Tumour mutations supplied: **{run['stages'][0]['in']}**; HLA class I alleles used: {', '.join(run['alleles_used']) or 'none'}.",
    ]
    if run["alleles_unsupported"]:
        lines.append(f"- Not supported by the predictor and left out: {', '.join(run['alleles_unsupported'])}.")
    lines += [f"- Thresholds: VAF ≥ {p['min_vaf']}, depth ≥ {p['min_depth']}, expression ≥ {p['min_tpm']} TPM, matched-normal VAF < {p['max_normal_vaf']}, "
              f"presentation percentile ≤ {p['max_pres_pct']} (strong ≤ {p['strong_pct']}), peptide lengths {p['lengths']}.", ""]
    for w in run["warnings"]:
        lines.append(f"- ⚠ {w}")
    lines += ["", "## Funnel", "| Stage | In | Out |", "|---|---|---|"] + [f"| {s['name']} | {s['in']} | {s['out']} |" for s in run["stages"]] + [""]
    lines += ["## Selected candidates", ""]
    if run["selected"]:
        lines += ["| # | Gene | Change | Peptide (mutant) | Wild-type | HLA | Affinity nM | Presentation pct | VAF | TPM | Tier | Score |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for i, c in enumerate(run["selected"], 1):
            lines.append(f"| {i} | {c['gene']} | {c['change']} | `{c['peptide']}` | `{c['wt_peptide']}` | {c['allele']} | {c['affinity_nM']:g} | {c['presentation_pct']:g} | "
                         f"{'—' if c['vaf'] is None else c['vaf']} | {'—' if c['tpm'] is None else c['tpm']} | {c['tier']} | {c['score']:g}{' ★' if c['hotspot'] else ''} |")
        lines += ["", "Tier A: strongly predicted and every supporting measurement present. B: one of those missing. C: neither. ★ recurrent hotspot (curated list, verify). "
                  "Each score is the transparent weighted sum recorded with the candidate.", ""]
        for c in run["selected"]:
            if c["flags"]:
                lines.append(f"- **{c['gene']} {c['change']}** caveats: " + "; ".join(c["flags"]) + ".")
    else:
        lines.append("No candidate passed all stages.")
    lines += ["", "## Rejected, and why", ""]
    if run["rejected"]:
        lines += ["| Gene | Change | Stage | Reason |", "|---|---|---|---|"] + [f"| {r['gene']} | {r['change']} | {r['stage']} | {r['reason']} |" for r in run["rejected"]]
    else:
        lines.append("Nothing was rejected.")
    lines += ["", "## Limits of this analysis",
              "- Only single amino-acid substitutions are handled. Frameshifts, insertions/deletions, splice variants, fusions and self/cancer-testis antigens are not yet (they need transcript-level translation).",
              "- Class I only. Class II (CD4) help is not modelled.",
              "- Without a matched normal, inherited variants cannot be excluded; without RNA, expression is unknown. Such candidates are capped at tier B or C.",
              "- Binding/presentation is predicted, not measured. No peptide has been tested for T-cell reactivity.",
              "", "## For the care team",
              "Bring this to the tumour board or a clinical-trial centre. Ask whether the patient qualifies for an individualised neoantigen vaccine trial, and whether the sequencing "
              "(tumour, matched normal, RNA) and HLA typing on file are sufficient for them.", "",
              "## Reproducing this run",
              f"Stored predictions let the selection be replayed without the model; the replay must reproduce result hash `{run['result_hash'][:16]}` exactly."]
    return "\n".join(lines)


def to_json(run: dict) -> str:
    keep = {k: v for k, v in run.items() if k != "predictions"}
    return json.dumps(keep, indent=2, sort_keys=True)
