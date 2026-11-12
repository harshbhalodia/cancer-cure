"""Turns an imaging report into structured, verified measurements and findings.

The model only proposes. Each item is then checked against the document text:
- its quote must really appear in the document (tolerating PDF line-break noise),
- every number must appear in the document,
- dates must be dates the document contains.
Items that fail are returned in `rejected` with the reason, not silently dropped (yash-style: every
rejection is kept so a human can see what was discarded and why).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.services import llm

SCAN_SYSTEM = """You extract structured data from ONE imaging report into JSON for a patient's record. \
Use ONLY what the report states. Never infer, never estimate, never convert a finding into a diagnosis. \
Return a single JSON object with this shape:
{
 "study": {"modality": "PET-CT|CT|MRI|Ultrasound|X-ray|Other", "date": "YYYY-MM-DD or empty",
           "comparator": {"modality": "", "date": "YYYY-MM-DD or empty"}},
 "lesions": [{"name": "short label e.g. Left tongue lesion", "site": "", "is_target": true,
              "basis": "longest_diameter|short_axis|unknown", "size_mm_now": null, "size_mm_prior": null,
              "suv_max_now": null, "quote": "verbatim text from the report"}],
 "findings": [{"text": "plain restatement of one finding", "category": "primary|nodal|distant|vascular|other",
               "certainty": "definite|possible|absent", "quote": "verbatim text from the report"}],
 "reported_response": {"label": "", "criteria": "", "sum_prior_mm": null, "sum_now_mm": null,
                       "percent_change": null, "quote": ""}
}
Rules:
- Sizes are millimetres as numbers. If the report gives a target-lesion table, use its rows for "lesions" \
(is_target true) and use the table's measurement basis; otherwise use the sizes in the text.
- "possible" certainty when the report says appears, could be, suspicious, likely, may represent; \
"definite" when it states a finding plainly; "absent" for explicitly negative statements about a disease site \
(include only negatives that matter, e.g. no base-of-tongue involvement).
- Do not list normal organs. "vascular" is for clots/vessel findings.
- The report's IMPRESSION / CONCLUSION section is the most important part: add EACH conclusion there as its own \
finding, keeping the report's hedging. "appears to be", "could be", "likely", "suspicious" => certainty "possible". \
Do not turn a hedged conclusion into a plain statement. Prefer these impression findings over repeating the \
descriptive text from the body of the report.
- reported_response is only what the report itself concludes; leave fields empty if not stated.
- "quote" must be copied exactly from the report. No commentary, no code fences."""

_NUM = re.compile(r"\d+(?:\.\d+)?")
_HEDGE = re.compile(r"\b(possib\w*|appear\w*|could|likely|suspic\w*|may|might|probabl\w*|question\w*|cannot be excluded)\b", re.I)
_DATE_NUMERIC = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.]((?:20)?\d{2})\b|\b(20\d{2})-(\d{2})-(\d{2})\b")


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def document_text(db: Session, doc: Document) -> str:
    chunks = db.query(DocumentChunk).filter_by(document_id=doc.id).order_by(DocumentChunk.page, DocumentChunk.id).all()
    return "\n".join(c.text for c in chunks)


def find_dates(text: str) -> set[str]:
    found: set[str] = set()
    for m in _DATE_NUMERIC.finditer(text):
        if m.group(4):
            found.add(f"{m.group(4)}-{m.group(5)}-{m.group(6)}")
            continue
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
        year = year if len(year) == 4 else f"20{year}"
        if month > 12:
            day, month = month, day
        if 1 <= month <= 12 and 1 <= day <= 31:
            found.add(f"{year}-{month:02d}-{day:02d}")
    return found


def quote_supported(quote: str, text: str, threshold: float = 0.85) -> bool:
    q, t = _squash(quote), _squash(text)
    if len(q) < 8:
        return False
    if q in t:
        return True
    matcher = SequenceMatcher(None, t, q, autojunk=False)
    matched = sum(b.size for b in matcher.get_matching_blocks())
    return matched / len(q) >= threshold


def _numbers(text: str) -> set[str]:
    return {n.rstrip("0").rstrip(".") if "." in n else n for n in _NUM.findall(text)}


def _num_in(value, nums: set[str]) -> bool:
    if value is None:
        return True
    s = f"{float(value):g}"
    return s in nums


def _as_float(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def norm_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def validate(data: dict, text: str, doc_date: str) -> dict:
    nums = _numbers(text)
    dates = find_dates(text)
    if doc_date:
        dates.add(doc_date)
    rejected: list[dict] = []

    study = data.get("study") or {}
    comp = study.get("comparator") or {}
    scan_date = study.get("date") or doc_date
    if scan_date and scan_date not in dates:
        rejected.append({"item": f"study date {scan_date}", "reason": "date not found in the document"})
        scan_date = doc_date
    comp_date = comp.get("date") or ""
    if comp_date and comp_date not in dates:
        rejected.append({"item": f"comparison date {comp_date}", "reason": "date not found in the document"})
        comp_date = ""

    lesions = []
    for raw in data.get("lesions") or []:
        name = str(raw.get("name") or "").strip()
        now, prior, suv = _as_float(raw.get("size_mm_now")), _as_float(raw.get("size_mm_prior")), _as_float(raw.get("suv_max_now"))
        quote = str(raw.get("quote") or "")
        problems = []
        if not name:
            problems.append("no name")
        if not quote_supported(quote, text):
            problems.append("quote not found in the document")
        for label, v in (("current size", now), ("previous size", prior), ("SUVmax", suv)):
            if not _num_in(v, nums):
                problems.append(f"{label} {v:g} does not appear in the document")
        if now is None and prior is None:
            problems.append("no size")
        if problems:
            rejected.append({"item": f"lesion {name or '?'}", "reason": "; ".join(problems)})
            continue
        lesions.append({
            "name": name, "site": str(raw.get("site") or ""), "is_target": bool(raw.get("is_target", True)),
            "basis": raw.get("basis") if raw.get("basis") in ("longest_diameter", "short_axis") else "unknown",
            "size_mm_now": now, "size_mm_prior": prior, "suv_max_now": suv, "quote": quote,
        })

    findings = []
    for raw in data.get("findings") or []:
        quote = str(raw.get("quote") or "")
        text_ = str(raw.get("text") or "").strip()
        if not text_ or not quote_supported(quote, text):
            rejected.append({"item": f"finding {text_[:60] or '?'}", "reason": "quote not found in the document"})
            continue
        certainty = raw.get("certainty") if raw.get("certainty") in ("definite", "possible", "absent") else "possible"
        if certainty == "possible" and not _HEDGE.search(text_):
            text_ = f"Possible: {text_[0].lower()}{text_[1:]}"  # the wording itself must never read as certain
        findings.append({
            "text": text_,
            "category": raw.get("category") if raw.get("category") in ("primary", "nodal", "distant", "vascular", "other") else "other",
            "certainty": certainty,
            "quote": quote,
        })

    rr = data.get("reported_response") or {}
    reported = {
        "label": str(rr.get("label") or "").strip(), "criteria": str(rr.get("criteria") or "").strip(),
        "sum_prior_mm": _as_float(rr.get("sum_prior_mm")), "sum_now_mm": _as_float(rr.get("sum_now_mm")),
        "percent_change": _as_float(rr.get("percent_change")), "quote": str(rr.get("quote") or ""),
    }
    if reported["label"] and not quote_supported(reported["quote"], text):
        rejected.append({"item": f"reported response {reported['label']}", "reason": "quote not found in the document"})
        reported = {k: ("" if isinstance(v, str) else None) for k, v in reported.items()}
    elif not all(_num_in(reported[k], nums) for k in ("sum_prior_mm", "sum_now_mm", "percent_change")):
        rejected.append({"item": "reported response numbers", "reason": "a number does not appear in the document"})
        reported.update(sum_prior_mm=None, sum_now_mm=None, percent_change=None)

    return {
        "study": {"modality": str(study.get("modality") or ""), "date": scan_date or "",
                  "comparator_modality": str(comp.get("modality") or ""), "comparator_date": comp_date},
        "lesions": lesions, "findings": findings, "reported_response": reported, "rejected": rejected,
    }


def extract(db: Session, doc: Document) -> dict:
    text = document_text(db, doc)
    if not text.strip():
        raise llm.LLMError("This document has no readable text yet.")
    data = llm.chat_json(SCAN_SYSTEM, f"REPORT ({doc.filename}, {doc.doc_date or 'date unknown'}):\n{text[:14000]}")
    return validate(data, text, doc.doc_date)
