"""Binding/presentation predictors behind one small interface.

`Mhcflurry` is the real predictor (class I presentation: binding affinity + antigen processing, trained on mass-spec
data). `Replay` serves the recorded numbers of an earlier run so a run can be re-checked without the model. If no
real predictor is installed the pipeline refuses to select candidates; it never substitutes a made-up score.
"""
from __future__ import annotations

import threading
from typing import Protocol

_lock = threading.Lock()
_cache: dict = {}


class Predictor(Protocol):
    name: str

    def supported(self, allele: str) -> bool: ...

    def predict(self, peptides: list[str], alleles: list[str]) -> dict[str, dict]:
        """peptide -> {allele (best), affinity_nM, presentation_score, presentation_pct}."""


class Mhcflurry:
    def __init__(self) -> None:
        import mhcflurry  # noqa: PLC0415  (heavy import, only when used)
        from mhcflurry import Class1PresentationPredictor  # noqa: PLC0415

        self.name = f"mhcflurry {mhcflurry.__version__} class1-presentation"
        self._p = Class1PresentationPredictor.load()
        self._supported = set(self._p.supported_alleles)

    def supported(self, allele: str) -> bool:
        return allele in self._supported

    def predict(self, peptides: list[str], alleles: list[str]) -> dict[str, dict]:
        uniq = sorted(set(peptides))
        if not uniq or not alleles:
            return {}
        df = self._p.predict(peptides=uniq, alleles=sorted(alleles), verbose=0)
        return {r.peptide: {"allele": r.best_allele, "affinity_nM": round(float(r.affinity), 3), "presentation_score": round(float(r.presentation_score), 4),
                            "presentation_pct": round(float(r.presentation_percentile), 4)} for r in df.itertuples()}


class Replay:
    """Serves recorded predictions (key `allele-set|peptide`) so a stored run can be re-selected byte for byte."""

    def __init__(self, recorded: dict, name: str) -> None:
        self.name, self._rec = name, recorded

    def supported(self, allele: str) -> bool:  # support was checked when the run was recorded
        return True

    def predict(self, peptides: list[str], alleles: list[str]) -> dict[str, dict]:
        key = "+".join(sorted(alleles))
        out = {}
        for p in set(peptides):
            rec = self._rec.get(f"{key}|{p}")
            if rec is None:
                raise KeyError(f"no recorded prediction for {p} on {key}")
            out[p] = rec
        return out


def available() -> bool:
    try:
        import mhcflurry  # noqa: F401, PLC0415
        from mhcflurry.downloads import get_path  # noqa: PLC0415

        get_path("models_class1_presentation")
        return True
    except Exception:  # not installed, or its models were never downloaded
        return False


def load_default() -> Predictor:
    """The real predictor, loaded once per process (loading takes about 20 s)."""
    with _lock:
        if "mhcflurry" not in _cache:
            _cache["mhcflurry"] = Mhcflurry()
        return _cache["mhcflurry"]
