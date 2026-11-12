"""Deterministic tumour-response arithmetic. No model involved.

Categories follow RECIST 1.1 *thresholds* but are computed against the previous scan only, because
that is all a single report quotes. Formal RECIST compares with baseline/nadir and also considers
non-target and new lesions, so a computed label is a size summary — the report's own label is always
shown next to it.
"""
from __future__ import annotations

from dataclasses import dataclass

PR_THRESHOLD = -30.0  # % change in sum of target diameters
PD_THRESHOLD = 20.0  # % increase ...
PD_MIN_ABS_MM = 5.0  # ... and at least this many mm absolute


@dataclass(frozen=True)
class Point:
    lesion: str
    label: str
    size_mm: float


@dataclass(frozen=True)
class Comparison:
    lesions: tuple[str, ...]
    sum_prior: float
    sum_now: float
    pct_change: float
    category: str  # partial_response | progressive_disease | stable_disease
    caveat: str

    @property
    def category_label(self) -> str:
        return {
            "partial_response": "Partial response (size)",
            "progressive_disease": "Progressive disease (size)",
            "stable_disease": "Stable disease (size)",
        }[self.category]


def classify(sum_prior: float, sum_now: float) -> tuple[float, str]:
    pct = (sum_now - sum_prior) / sum_prior * 100
    if pct <= PR_THRESHOLD:
        return pct, "partial_response"
    if pct >= PD_THRESHOLD and (sum_now - sum_prior) >= PD_MIN_ABS_MM:
        return pct, "progressive_disease"
    return pct, "stable_disease"


def compare(prior: list[Point], now: list[Point]) -> Comparison | None:
    """Sum only target lesions that were measured in BOTH studies, so the sums are like for like."""
    prior_by = {p.lesion: p for p in prior if p.size_mm is not None and p.size_mm >= 0}
    now_by = {p.lesion: p for p in now if p.size_mm is not None and p.size_mm >= 0}
    shared = sorted(set(prior_by) & set(now_by))
    if not shared:
        return None
    sum_prior = sum(prior_by[k].size_mm for k in shared)
    sum_now = sum(now_by[k].size_mm for k in shared)
    if sum_prior <= 0:
        return None
    pct, category = classify(sum_prior, sum_now)
    return Comparison(
        lesions=tuple(now_by[k].label for k in shared),
        sum_prior=round(sum_prior, 1),
        sum_now=round(sum_now, 1),
        pct_change=round(pct, 1),
        category=category,
        caveat="Computed from target-lesion sizes versus the previous study only; new or non-target lesions are not included.",
    )
