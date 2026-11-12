"""Clinical requirements catalogue: what a complete record needs, and which decisions depend on it.

This is data, not model output. The entries are conservative STARTING rules written from general
oncology practice and must be reviewed and edited by the treating oncologist before being relied on.
Each requirement says *why* it matters so the app can explain a gap instead of just listing it.
"""
from __future__ import annotations

from dataclasses import dataclass

ALL = "all"
ORAL = "oral_cavity"  # tongue, mouth, gum, cheek, lip


@dataclass(frozen=True)
class Requirement:
    key: str
    label: str
    group: str
    why: str
    ask: str  # how to put it to the oncologist
    profiles: tuple[str, ...] = (ALL,)
    # Case-file fields / regexes that can answer this without a structured fact (user-entered text).
    case_field: str = ""
    case_regex: str = ""
    # A document type on file counts as evidence that the item exists (value still to be structured).
    doc_type: str = ""


REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement("histology", "Histology / tumour type", "Diagnosis",
        "Every treatment and trial decision starts from the exact tumour type and grade.",
        "Can I have a copy of the full pathology report, including grade?", case_field="histology", doc_type="pathology"),
    Requirement("stage", "Stage (TNM)", "Diagnosis",
        "Stage determines the treatment intent and which trials are open.",
        "What is the current stage, and was it re-staged after the latest scan?", case_field="stage"),
    Requirement("margins", "Surgical margin status", "Pathology details",
        "Close or positive margins change what treatment is recommended after surgery.",
        "Were the surgical margins clear, close or positive?", profiles=(ORAL,)),
    Requirement("depth_of_invasion", "Depth of invasion", "Pathology details",
        "Depth of invasion is part of staging for oral-cavity cancers.",
        "What was the depth of invasion in the pathology report?", profiles=(ORAL,)),
    Requirement("pni_lvi", "Perineural / lymphovascular invasion", "Pathology details",
        "These are recurrence-risk features that influence follow-up treatment.",
        "Did the pathology show perineural or lymphovascular invasion?", profiles=(ORAL,)),
    Requirement("ene", "Extranodal extension", "Pathology details",
        "Spread beyond the lymph-node capsule is a high-risk feature.",
        "Was there extranodal extension in any removed lymph node?", profiles=(ORAL,)),
    Requirement("pdl1", "PD-L1 (CPS / TPS)", "Biomarkers",
        "PD-L1 is used to guide immunotherapy options and is often required for trial screening.",
        "Has PD-L1 been tested, and what was the CPS?", case_regex=r"pd-?l1"),
    Requirement("msi_tmb", "MSI / mismatch repair and TMB", "Biomarkers",
        "These identify tumours that may respond to immunotherapy and are common trial criteria.",
        "Have MSI/mismatch-repair status and tumour mutational burden been tested?", case_regex=r"\b(msi|tmb|mismatch)\b"),
    Requirement("ngs_tumour", "Tumour genomic profiling (NGS panel)", "Precision medicine",
        "Lists the tumour's mutations; needed for targeted-therapy and trial matching and as the starting point for any personalised vaccine.",
        "Can tumour genomic profiling be run on the surgical or biopsy tissue (or on blood)?",
        case_regex=r"\b(ngs|caris|foundation ?one|guardant|genomic|sequencing)\b", doc_type="genomics"),
    Requirement("ngs_normal", "Matched-normal DNA (e.g. blood)", "Precision medicine",
        "Comparing tumour with the patient's normal DNA separates true tumour mutations from inherited ones; personalised vaccine designs depend on it.",
        "If sequencing is done, can normal blood DNA be sequenced alongside the tumour?"),
    Requirement("tumour_rna", "Tumour RNA sequencing", "Precision medicine",
        "Shows which mutated genes are actually expressed and detects gene fusions.",
        "Can RNA sequencing be done on the tumour tissue?"),
    Requirement("hla", "HLA typing (class I, high resolution)", "Precision medicine",
        "HLA type decides which mutation fragments the immune system can present; required for vaccine design.",
        "Has HLA typing been done, or can it be added to a blood draw?", case_field="hla_type"),
    Requirement("treatment_history", "Treatment history with dates", "Treatment",
        "Prior lines of therapy determine what comes next and trial eligibility.",
        "Can we write down each treatment given, with start and end dates and the response?", case_field="treatment_history"),
    Requirement("current_regimen", "Current treatment / follow-up plan", "Treatment",
        "Needed to interpret scans and side effects in context.",
        "What is the current plan and when is the next review?", case_field="current_treatment"),
    Requirement("ecog", "Performance status (ECOG)", "Fitness",
        "Almost all treatment and trial decisions depend on how well the patient is functioning.",
        "What is the current performance status?"),
    Requirement("labs_recent", "Recent blood tests (last 45 days)", "Fitness",
        "Blood counts, kidney and liver function are checked before treatment and for trial screening.",
        "When were the last blood counts, kidney and liver tests, and can I have them?", doc_type="lab"),
    Requirement("nutrition", "Weight and swallowing / nutrition status", "Fitness",
        "Weight loss and difficulty eating are common and treatable in head-and-neck cancer.",
        "Should we see a dietitian or speech-and-swallow therapist?", profiles=(ORAL,)),
    Requirement("recent_imaging", "Recent imaging (last 90 days)", "Imaging",
        "Current disease status is read from the latest scan compared with the previous one.",
        "Is the next scan scheduled?"),
    Requirement("imaging_trend", "At least two timepoints for target lesions", "Imaging",
        "A trend needs two measurements of the same lesion.",
        "Can the radiologist measure the same lesions on each scan?"),
    Requirement("allergies", "Allergies and drug reactions", "Safety",
        "Needed before any new medicine or trial.", "", case_field="allergies"),
)

BY_KEY = {r.key: r for r in REQUIREMENTS}


@dataclass(frozen=True)
class Decision:
    id: str
    title: str
    question: str
    needs: tuple[str, ...]
    hard: tuple[str, ...] = ()  # without these the decision cannot proceed at all


DECISIONS: tuple[Decision, ...] = (
    Decision("interpret_response", "Understand how treatment is working",
        "Is the disease responding, and how sure are we?",
        ("recent_imaging", "imaging_trend", "treatment_history", "current_regimen"),
        hard=("recent_imaging", "imaging_trend")),
    Decision("oncologist_visit", "Prepare for the next oncologist visit",
        "Do we have the basics the oncologist will ask for?",
        ("histology", "stage", "treatment_history", "current_regimen", "recent_imaging", "labs_recent", "ecog")),
    Decision("second_opinion", "Get a second opinion",
        "Can another expert review the case from the records alone?",
        ("histology", "stage", "margins", "depth_of_invasion", "pni_lvi", "ene", "treatment_history", "recent_imaging"),
        hard=("histology", "recent_imaging")),
    Decision("trial_screening", "Screen for clinical trials",
        "Do we have what trial coordinators check first?",
        ("histology", "stage", "treatment_history", "ecog", "labs_recent", "pdl1", "msi_tmb", "ngs_tumour", "recent_imaging", "allergies"),
        hard=("histology", "stage")),
    Decision("vaccine_feasibility", "Explore a personalised vaccine (research)",
        "Is there enough sequencing to even start a neoantigen design?",
        ("histology", "ngs_tumour", "ngs_normal", "tumour_rna", "hla"),
        hard=("ngs_tumour", "ngs_normal", "hla")),
)


def profile_for(case_text: str) -> str:
    text = case_text.lower()
    if any(w in text for w in ("tongue", "oral cavity", "mouth", "gingiv", "buccal", "floor of mouth", "lip ", "palate")):
        return ORAL
    return ALL


def applicable(profile: str) -> list[Requirement]:
    return [r for r in REQUIREMENTS if ALL in r.profiles or profile in r.profiles]
