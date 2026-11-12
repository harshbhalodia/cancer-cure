"""Deterministic safety layer: red-flag triage before the model, output linter after it.

These rules are intentionally conservative starting points. Replace them with the patient's own
oncology-team instructions (and have a clinician review them) before relying on them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

EMERGENCY = "emergency"
URGENT = "urgent"


@dataclass(frozen=True)
class RedFlag:
    id: str
    level: str
    pattern: re.Pattern[str]
    message: str


def _rf(id_: str, level: str, pattern: str, message: str) -> RedFlag:
    return RedFlag(id_, level, re.compile(pattern, re.I), message)


RED_FLAGS: tuple[RedFlag, ...] = (
    _rf("chest-pain", EMERGENCY, r"\bchest (pain|pressure|tightness)\b", "Chest pain or pressure"),
    _rf(
        "breathing",
        EMERGENCY,
        r"\b(can'?t|cannot|unable to|hard to|difficulty|trouble|struggling to) breathe?\b|\bshort(ness)? of breath\b|\bbreathing (difficulty|problem)s?\b|\bgasping\b",
        "Difficulty breathing",
    ),
    _rf(
        "heavy-bleeding",
        EMERGENCY,
        r"\b(heavy|severe|uncontrolled|profuse|won'?t stop|not stopping)\b.{0,30}\bbleed\w*|\bbleed\w*.{0,30}\b(won'?t stop|not stopping|heavy|profuse|severe)\b|\b(vomit\w*|cough\w*|spit\w*) (up )?(blood|blood clots?)\b",
        "Heavy or uncontrolled bleeding",
    ),
    _rf(
        "stroke",
        EMERGENCY,
        r"\b(face|facial) (droop\w*|numb\w*)\b|\bslurred speech\b|\bsudden (weakness|numbness|confusion|loss of vision)\b|\bseizure\b|\bunconscious\b|\bfaint(ed|ing)\b|\bpass(ed)? out\b",
        "Possible stroke, seizure or loss of consciousness",
    ),
    _rf(
        "self-harm",
        EMERGENCY,
        r"\bsuicid\w*|\bkill (myself|himself|herself)\b|\bend (my|his|her) (own )?life\b|\bdon'?t want to (live|be alive)\b",
        "Thoughts of self-harm",
    ),
    _rf(
        "fever",
        URGENT,
        r"\bfever\b|\bchills\b|\btemperature (of |is |was )?(3[89]|10[0-9])\b|\b(38|39|40)(\.\d)? ?°? ?c\b|\b10[0-4](\.\d)? ?°? ?f\b",
        "Fever or chills (can signal infection during cancer treatment)",
    ),
    _rf(
        "clot-signs",
        URGENT,
        r"\b(swelling|swollen|redness|warm|pain)\b.{0,40}\b(leg|calf|arm|neck|face)\b|\b(leg|calf|arm|neck|face)\b.{0,40}\b(swelling|swollen|redness|warm|painful)\b",
        "New swelling, warmth or pain in a limb, neck or face (possible blood clot)",
    ),
    _rf(
        "cannot-hydrate",
        URGENT,
        r"\b(can'?t|cannot|unable to|not able to|couldn'?t) (keep|hold) (\w+ )?down\b|\b(can'?t|cannot|unable to|not able to) (swallow|eat|drink)\b|\bvomit\w* (for|since|all) ",
        "Unable to swallow, eat, drink or keep fluids down",
    ),
    _rf(
        "confusion",
        URGENT,
        r"\b(confus\w+|disorient\w+|very drowsy|can'?t stay awake|hard to wake)\b",
        "New confusion or unusual drowsiness",
    ),
    _rf(
        "uncontrolled-pain",
        URGENT,
        r"\b(severe|unbearable|worst|uncontrolled|excruciating) pain\b|\bpain (is |was )?(severe|unbearable|uncontrolled)\b",
        "Severe or uncontrolled pain",
    ),
    _rf(
        "new-lump-bleed",
        URGENT,
        r"\bblood\b.{0,25}\b(mouth|saliva|stool|urine)\b|\bblack (stool|stools|tarry)\b|\bnew (lump|swelling|ulcer|sore)\b",
        "Blood in mouth/stool/urine or a new lump/ulcer",
    ),
)


@dataclass(frozen=True)
class TriageResult:
    level: str | None
    hits: tuple[RedFlag, ...]

    @property
    def flag_ids(self) -> list[str]:
        return [h.id for h in self.hits]


def triage(text: str) -> TriageResult:
    hits = tuple(rf for rf in RED_FLAGS if rf.pattern.search(text or ""))
    if any(h.level == EMERGENCY for h in hits):
        return TriageResult(EMERGENCY, hits)
    if hits:
        return TriageResult(URGENT, hits)
    return TriageResult(None, ())


def triage_message(result: TriageResult, emergency_number: str) -> str:
    reasons = "; ".join(h.message for h in result.hits)
    if result.level == EMERGENCY:
        return (
            f"**This may be an emergency ({reasons}).** Please call your local emergency number "
            f"({emergency_number}) or go to the nearest emergency department now, and let someone nearby know. "
            "Tell the doctors about the cancer diagnosis and current treatment.\n\n"
            "I'm not able to assess this safely, so I'm pausing the chat answer. Once you are safe or "
            "someone is with you, you can continue here."
        )
    return (
        f"**Please contact your oncology team today ({reasons}).** During cancer treatment these can need "
        "same-day medical review. If they are unreachable or things get worse, go to the nearest emergency "
        f"department ({emergency_number}).\n\n"
        "I'll still answer your question below, but this is not a substitute for being seen."
    )


# --------------------------------------------------------------------------------------- linter

_NEGATION = re.compile(r"(\bnot\b|n't\b|\bnever\b|\bwithout\b|\bwhether\b|\bask\b|\bdiscuss\b|\bbefore\b|\bif your\b|\bunless\b|\bdo not\b)", re.I)
_TREATMENT = r"(chemo\w*|radiation|radiotherapy|immunotherapy|treatments?|therapy|medications?|medicines?|drugs?|surgery|cisplatin|carboplatin|pembrolizumab|nivolumab|cetuximab|paclitaxel|docetaxel|capecitabine)"

_STOP = re.compile(rf"\b(stop|discontinue|skip|quit|abandon|pause|delay|postpone)\b[^.\n]{{0,40}}\b{_TREATMENT}\b", re.I)
_REPLACE = re.compile(rf"\b(instead of|in place of|rather than|replace)\b[^.\n]{{0,25}}\b{_TREATMENT}\b", re.I)
_DOSE = re.compile(
    r"\b(take|taking|increase|decrease|reduce|double|raise|lower|start|use)\b[^.\n]{0,40}\b\d+(\.\d+)?\s?(mg|mcg|µg|ml|g|iu|units?|tablets?|pills?|capsules?)\b",
    re.I,
)
_DIAGNOSE = re.compile(
    r"\b(is|are|was|were)\s+(definitely|certainly|clearly|confirmed to be|undoubtedly)\s+(a |an )?(cancer\w*|metasta\w+|recurren\w+|malignan\w+|benign)\b",
    re.I,
)
_PROMISE = re.compile(
    r"\b(you will (definitely |certainly )?(be cured|recover|survive|die|live)|guaranteed (cure|recovery|survival)|\d+\s*(months?|years?|weeks?) (left )?to live|will (definitely|certainly) (cure|work))\b",
    re.I,
)


def lint(answer: str) -> list[str]:
    """Return rule ids violated by a model answer. Empty list means it may be shown."""
    violations: list[str] = []

    def hit(pattern: re.Pattern[str], rule: str, *, allow_negation: bool) -> None:
        for m in pattern.finditer(answer):
            if allow_negation:
                lead = answer[max(0, m.start() - 45) : m.start() + 6]
                if _NEGATION.search(lead):
                    continue
            violations.append(rule)
            return

    hit(_STOP, "stop-treatment", allow_negation=True)
    hit(_REPLACE, "replace-treatment", allow_negation=True)
    hit(_DOSE, "dosing-instruction", allow_negation=True)
    hit(_DIAGNOSE, "diagnosis-claim", allow_negation=False)
    hit(_PROMISE, "outcome-promise", allow_negation=False)
    return violations


SAFE_FALLBACK = (
    "I can't answer that in a way that is safe for me to give. Decisions about starting, stopping, "
    "changing or dosing treatment, and confirming a diagnosis or outlook, belong to your oncology team.\n\n"
    "What I can do: explain what your reports say, summarise what has changed, and prepare specific "
    "questions for your next visit. Tell me which of those would help."
)
