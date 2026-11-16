"""Reading a tumour's mutation list and HLA type into rows the pipeline can use.

Accepted: a plain table (TSV/CSV with a header: gene, protein_change, vaf, depth, normal_vaf, tpm, …) or a VCF whose
INFO carries SnpEff `ANN=` or VEP `CSQ=` annotation. Anything that cannot be read is reported, never guessed.
"""
from __future__ import annotations

import csv
import io
import re

THREE = {"Ala": "A", "Arg": "R", "Asn": "N", "Asp": "D", "Cys": "C", "Gln": "Q", "Glu": "E", "Gly": "G", "His": "H", "Ile": "I",
         "Leu": "L", "Lys": "K", "Met": "M", "Phe": "F", "Pro": "P", "Ser": "S", "Thr": "T", "Trp": "W", "Tyr": "Y", "Val": "V", "Ter": "*"}
AA = set("ACDEFGHIKLMNPQRSTVWY")
_MISSENSE = re.compile(r"^(?:p\.)?([A-Z])(\d+)([A-Z])$")
_MISSENSE3 = re.compile(r"^(?:p\.)?([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2})$")
HLA_RE = re.compile(r"(?:HLA-)?([ABC])\*?(\d{2,3}):(\d{2,3})", re.I)

COLUMN_ALIASES = {
    "gene": ("gene", "hugo_symbol", "symbol", "gene_name"),
    "protein_change": ("protein_change", "hgvsp_short", "hgvs_p", "aa_change", "protein", "amino_acid_change"),
    "consequence": ("consequence", "variant_classification", "effect", "annotation"),
    "vaf": ("vaf", "tumour_vaf", "tumor_vaf", "t_vaf", "allele_fraction"),
    "depth": ("depth", "t_depth", "dp", "coverage"),
    "normal_vaf": ("normal_vaf", "n_vaf"),
    "tpm": ("tpm", "expression", "expr_tpm"),
}


def parse_protein_change(text: str) -> tuple[str, int, str] | None:
    """('G', 12, 'D') for a simple amino-acid substitution, else None (frameshift, indel, stop, splice… are not handled here)."""
    t = (text or "").strip()
    m = _MISSENSE.match(t)
    if m and m.group(1) in AA and m.group(3) in AA:
        return m.group(1), int(m.group(2)), m.group(3)
    m = _MISSENSE3.match(t)
    if m and m.group(1) in THREE and m.group(3) in THREE and THREE[m.group(1)] in AA and THREE[m.group(3)] in AA:
        return THREE[m.group(1)], int(m.group(2)), THREE[m.group(3)]
    return None


def normalise_allele(text: str) -> str | None:
    m = HLA_RE.search(text or "")
    if not m:
        return None
    return f"HLA-{m.group(1).upper()}*{m.group(2)}:{m.group(3)}"


def parse_hla(text: str) -> tuple[list[str], list[str]]:
    """(alleles, problems). Two-field resolution is required; anything coarser is reported, not guessed."""
    alleles, problems = [], []
    for token in re.split(r"[\s,;/]+", text or ""):
        if not token.strip():
            continue
        a = normalise_allele(token)
        if a is None:
            problems.append(f"Could not read “{token}” as an HLA allele (use e.g. HLA-A*02:01).")
        elif a not in alleles:
            alleles.append(a)
    return alleles, problems


def _num(v: str | None) -> float | None:
    if v is None or str(v).strip() in ("", ".", "NA", "NaN", "None"):
        return None
    try:
        return float(str(v).strip().rstrip("%"))
    except ValueError:
        return None


def _frac(v: float | None) -> float | None:
    return None if v is None else (v / 100 if v > 1 else v)


def _pick(row: dict, key: str) -> str | None:
    for alias in COLUMN_ALIASES[key]:
        for col, val in row.items():
            if col and col.strip().lower() == alias:
                return val
    return None


def parse_table(text: str) -> tuple[list[dict], list[str]]:
    dialect = "excel-tab" if text.splitlines()[0].count("\t") >= 1 else "excel"
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows, problems = [], []
    for n, row in enumerate(reader, start=2):
        gene = (_pick(row, "gene") or "").strip()
        change = (_pick(row, "protein_change") or "").strip()
        if not gene or not change:
            problems.append(f"Line {n}: needs a gene and a protein change.")
            continue
        depth = _num(_pick(row, "depth"))
        rows.append({
            "gene": gene.upper(), "protein_change": change.replace("p.", ""), "consequence": (_pick(row, "consequence") or "").strip(),
            "vaf": _frac(_num(_pick(row, "vaf"))), "depth": int(depth) if depth is not None else None,
            "normal_vaf": _frac(_num(_pick(row, "normal_vaf"))), "tpm": _num(_pick(row, "tpm")),
            "wt_window": (row.get("wt_window") or "").strip().upper(), "wt_start": int(float(row.get("wt_start") or 1)),
        })
    return rows, problems


def _vcf_info(info: str) -> dict[str, str]:
    return {k: v for k, _, v in (p.partition("=") for p in info.split(";") if p)}


def parse_vcf(text: str) -> tuple[list[dict], list[str]]:
    rows, problems, csq_fields = [], [], []
    for line in text.splitlines():
        if line.startswith("##INFO=<ID=CSQ"):
            m = re.search(r"Format: ([^\">]+)", line)
            csq_fields = m.group(1).split("|") if m else []
        if line.startswith("#") or not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) < 8:
            problems.append("A VCF line had fewer than 8 columns and was skipped.")
            continue
        info = _vcf_info(cols[7])
        gene = change = cons = ""
        if "ANN" in info:
            f = info["ANN"].split(",")[0].split("|")
            cons, gene, change = (f[1] if len(f) > 1 else ""), (f[3] if len(f) > 3 else ""), (f[10] if len(f) > 10 else "")
        elif "CSQ" in info and csq_fields:
            f = info["CSQ"].split(",")[0].split("|")
            d = dict(zip(csq_fields, f))
            cons, gene, change = d.get("Consequence", ""), d.get("SYMBOL", ""), d.get("HGVSp", "").split(":")[-1]
        if not gene or not change:
            problems.append(f"{cols[0]}:{cols[1]} has no protein-level annotation (ANN/CSQ) and was skipped.")
            continue
        dp = _num(info.get("DP"))
        rows.append({"gene": gene.upper(), "protein_change": change.replace("p.", ""), "consequence": cons, "vaf": _frac(_num(info.get("VAF") or info.get("AF"))),
                     "depth": int(dp) if dp is not None else None, "normal_vaf": None, "tpm": None, "wt_window": "", "wt_start": 1})
    return rows, problems


def parse_variants(text: str) -> tuple[list[dict], list[str]]:
    text = (text or "").strip("\ufeff\r\n ")
    if not text:
        return [], ["The file is empty."]
    if text.lstrip().startswith("##fileformat=VCF") or text.lstrip().startswith("#CHROM"):
        return parse_vcf(text)
    return parse_table(text)
