"""A synthetic tumour for testing the pipeline end to end.

Nothing here is real: genes are named SYN###, proteins are random, and every row is stored with dataset="synthetic" so it
can never mix with the patient's data. Variants are planted with a known fate, so the gates can be checked against ground
truth ("this one must be rejected at the germline stage"), which is what makes this useful as an eval rather than a demo.
"""
from __future__ import annotations

import random

AA = "ACDEFGHIKLMNPQRSTVWY"
# common class I alleles the predictor supports
HLA = ["HLA-A*02:01", "HLA-A*24:02", "HLA-B*07:02", "HLA-B*44:02", "HLA-C*07:02", "HLA-C*05:01"]
PLANTS = [
    # tag, expected stage where it must fail (None = must pass all gates), count
    ("good", None, 8), ("synonymous", "variants", 1), ("frameshift", "variants", 1), ("low_vaf", "quality", 1), ("low_depth", "quality", 1),
    ("germline", "germline", 1), ("silent_gene", "expression", 1), ("ref_mismatch", "reference", 1),
]


def make(seed: int = 7) -> tuple[list[dict], list[str], dict[str, str]]:
    """(variant rows, HLA alleles, truth) where truth maps 'GENE protein_change' to the planted tag."""
    rng = random.Random(seed)
    rows: list[dict] = []
    truth: dict[str, str] = {}
    n = 0
    for tag, _stage, count in PLANTS:
        for _ in range(count):
            n += 1
            gene = f"SYN{n:03d}"
            seq = "M" + "".join(rng.choice(AA) for _ in range(260))
            pos = rng.randint(30, 230)
            wt = seq[pos - 1]
            mut = rng.choice([a for a in AA if a != wt])
            change = f"{wt}{pos}{mut}"
            row = {"gene": gene, "protein_change": change, "consequence": "missense_variant", "vaf": round(rng.uniform(0.2, 0.45), 3),
                   "depth": rng.randint(80, 200), "normal_vaf": 0.0, "tpm": round(rng.uniform(5, 60), 1), "wt_window": seq, "wt_start": 1}
            if tag == "synonymous":
                row.update(protein_change=f"{wt}{pos}{wt}", consequence="synonymous_variant")
                change = row["protein_change"]
            elif tag == "frameshift":
                row.update(protein_change=f"{wt}{pos}fs", consequence="frameshift_variant")
                change = row["protein_change"]
            elif tag == "low_vaf":
                row["vaf"] = 0.03
            elif tag == "low_depth":
                row["depth"] = 5
            elif tag == "germline":
                row["normal_vaf"] = 0.49
            elif tag == "silent_gene":
                row["tpm"] = 0.1
            elif tag == "ref_mismatch":
                other = rng.choice([a for a in AA if a not in (wt, mut)])
                row["protein_change"] = f"{other}{pos}{mut}"
                change = row["protein_change"]
            row["source"] = f"synthetic:{tag}"
            rows.append(row)
            truth[f"{gene} {change}"] = tag
    return rows, list(HLA), truth


def expected_stage(tag: str) -> str | None:
    return next(stage for t, stage, _ in PLANTS if t == tag)
