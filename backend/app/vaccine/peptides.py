"""Peptide windows that contain a mutation, and the reference sequences they come from."""
from __future__ import annotations

import hashlib

import httpx

LENGTHS = (8, 9, 10, 11)
UNIPROT = "https://rest.uniprot.org/uniprotkb/search"
STANDARD = set("ACDEFGHIKLMNPQRSTVWY")


def peptides_for(window: str, window_start: int, position: int, wt: str, mut: str, lengths=LENGTHS) -> list[dict]:
    """Every peptide of the given lengths that covers the mutated residue, as (mutant, wild-type) pairs.

    `position` is the 1-based protein position; `window_start` is the position of window[0]. Raises ValueError if the
    stated wild-type residue is not what the reference has there (wrong isoform or build): such a variant is rejected."""
    i = position - window_start
    if i < 0 or i >= len(window):
        raise ValueError("the mutated position is outside the reference sequence")
    if window[i] != wt:
        raise ValueError(f"reference has {window[i]} at position {position}, not {wt}")
    mutseq = window[:i] + mut + window[i + 1:]
    out = []
    for length in lengths:
        for start in range(max(0, i - length + 1), min(i, len(window) - length) + 1):
            m, w = mutseq[start:start + length], window[start:start + length]
            if set(m) <= STANDARD:
                out.append({"mut": m, "wt": w, "length": length, "offset": i - start})
    return out


def sequence_hash(seq: str) -> str:
    return hashlib.sha256(seq.encode()).hexdigest()[:12]


def fetch_reference(gene: str) -> tuple[str, str]:
    """(sequence, source) for a human gene from UniProt (reviewed entry). Only the gene symbol is sent."""
    resp = httpx.get(UNIPROT, params={"query": f"gene_exact:{gene} AND organism_id:9606 AND reviewed:true", "format": "fasta", "size": 1}, timeout=20)
    resp.raise_for_status()
    lines = resp.text.strip().splitlines()
    if not lines or not lines[0].startswith(">"):
        raise LookupError(f"no reviewed human protein found for {gene}")
    accession = lines[0].split("|")[1] if "|" in lines[0] else lines[0][1:20]
    return "".join(lines[1:]), f"uniprot:{accession}"
