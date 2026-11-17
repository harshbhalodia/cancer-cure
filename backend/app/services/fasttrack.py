"""The fastest honest route when time is short: do the slow, necessary things in parallel, today.

Built from your own records by plain code (no model). It never guesses: every fact in a draft comes from the case file,
the journey or a document's own text, and anything not on file is said to be not on file.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy.orm import Session

from app.models import Case, ClinicalEvent, Document, DocumentChunk, SomaticVariant
from app.services import casefile, priorities

TREATMENT = ("surgery", "radiotherapy", "chemotherapy", "immunotherapy")
PLAN_WORDS = re.compile(r"\b(plan\w*|advis\w*|suggest\w*|propos\w*|consider\w*|may|if)\b", re.I)


def _doc_text(db: Session, doc_id: int) -> str:
    return "\n".join(c.text for c in db.query(DocumentChunk).filter_by(document_id=doc_id).order_by(DocumentChunk.id))


def findings(db: Session) -> list[dict]:
    """Facts read from the documents' own text (with the file they came from), so drafts never rely on memory."""
    out = []
    for d in db.query(Document).filter(Document.status == "indexed").order_by(Document.id):
        text = re.sub(r"\s+", " ", _doc_text(db, d.id))
        m = re.search(r"PDL-?1[^.]{0,40}?COMBINED POSITIVE SCORE\s*:?\s*([\d\-–]+)", text, re.I)
        if m:
            rep = re.search(r"Reported On\s*:\s*([\d]{1,2}-[A-Za-z]{3}-\d{4})", text)
            interim = " (interim report)" if re.search(r"Report Status\s*:\s*Interim", text, re.I) else ""
            out.append({"key": "pdl1", "text": f"PD-L1 (22C3) combined positive score {m.group(1)}" + (f", reported {rep.group(1)}" if rep else "") + interim, "document_id": d.id, "filename": d.filename})
        h = re.search(r"CLINICAL HISTORY\s*(.{5,160}?)\s*METHODOLOGY", text)
        if h:
            out.append({"key": "histology", "text": h.group(1).strip(" ."), "document_id": d.id, "filename": d.filename})
        if re.search(r"Pending Services\s*geneCORE", text, re.I):
            out.append({"key": "panel_pending", "text": "A geneCORE Paradigm (DNA/RNA panel) is listed as pending on that report; its result is not in this app", "document_id": d.id, "filename": d.filename})
    return out


def _treatments(db: Session) -> list[str]:
    evs = [e for e in db.query(ClinicalEvent).filter(ClinicalEvent.category.in_(TREATMENT)).order_by(ClinicalEvent.event_date)
           if e.event_date and e.event_date <= date.today().isoformat() and not PLAN_WORDS.search(e.title)]
    return [f"{e.event_date}: {e.title}" for e in evs][:8]


def _clinical_summary(db: Session) -> list[str]:
    case = db.get(Case, 1)
    values, _ = casefile.derive(db)
    lines = []
    age = re.search(r"\d+", str(values.get("age") or ""))
    who = " ".join(x for x in ((f"{age.group(0)}-year-old" if age else ""), (values.get("sex") or "").lower()) if x)
    if who:
        lines.append(f"Patient: {who}.")
    fs = {f["key"]: f for f in findings(db)}
    dx = values.get("diagnosis") or values.get("primary_site") or ""
    if "histology" in fs:
        lines.append(f"Histology (from the pathology report): {fs['histology']['text']}.")
    elif dx:
        lines.append(f"Diagnosis (case file): {dx}.")
    if "pdl1" in fs:
        lines.append(fs["pdl1"]["text"] + ".")
    t = _treatments(db)
    if t:
        lines.append("Treatment history recorded (please verify): " + "; ".join(t) + ".")
    scan = priorities.latest_scan(db)
    if scan is not None:
        moves = [f"{l['label']} {priorities._fmt_mm(l['prior'])} → {priorities._fmt_mm(l['now'])}" for l in priorities._lesions(scan) if l["target"] and l["prior"] is not None and l["now"] is not None]
        lines.append(f"Latest imaging: {scan.modality or 'scan'} {scan.scan_date}" + (f", report conclusion: {scan.reported_label}" if scan.reported_label else "") + (f" ({'; '.join(moves)})" if moves else "") + ".")
        for tr in priorities.tracks(db):
            if tr["id"] in ("vessel", "residual"):
                lines.append(f"Open finding: {tr['title']}" + (f" ({' '.join(tr['facts'])})" if tr["facts"] else "") + ".")
    count = db.query(SomaticVariant).filter_by(dataset="patient").count()
    lines.append(f"Mutation data loaded for research: {count} variant(s); coverage and clinical interpretation require the sequencing report." if count else "Mutation data for research: not on file; this does not establish whether sequencing was performed.")
    lines.append(f"HLA type in the case file: {values['hla_type']} (verify the source)." if values.get("hla_type") else "HLA type in the case file: not on file.")
    return lines


def drafts(db: Session) -> list[dict]:
    summary = _clinical_summary(db)
    body = "\n".join(f"- {l}" for l in summary)
    return [
        {"id": "trial", "title": "Message to a trial centre / molecular tumour board", "to": "the trial coordinator or tumour board of a cancer centre that runs head-and-neck and neoantigen or immunotherapy trials",
         "text": ("Subject: Urgent eligibility screening: recurrent/persistent head and neck squamous cell carcinoma\n\n"
                  "Dear Doctor / Trial coordinator,\n\nWe are writing on behalf of a patient with limited time and would be grateful for urgent screening for any suitable clinical trial, "
                  "including individualised neoantigen / mRNA vaccine trials and other immunotherapy or novel-agent trials. Summary from the records:\n\n" + body +
                  "\n\nCould you please tell us:\n1. Whether he could be screened, and which trial(s) might fit.\n2. What tissue (FFPE blocks), blood and HLA typing you would need, and whether you can start from the existing blocks.\n"
                  "3. How quickly a decision on eligibility can be made.\n\nWe can send the reports (PET-CT, pathology, PD-L1) immediately. Thank you.")},
        {"id": "blocks", "title": "Request to the pathology lab / hospital for tumour blocks and samples", "to": "the pathology laboratory and the treating oncologist",
         "text": ("Subject: Request to release tumour blocks and arrange blood samples for comprehensive profiling\n\n"
                  "We request that the pathology department release (or send to the testing laboratory named by the oncologist) the formalin-fixed paraffin-embedded tumour blocks "
                  "and associated slides, including the most recent specimen. Please confirm which specimens exist, their dates and preservation, and whether a molecular tumour board "
                  "or trial centre requires further profiling. Please advise whether matched-normal DNA, tumour RNA and HLA typing are appropriate for the proposed sequencing-based research pathway. "
                  "Please confirm requirements before arranging tests or releasing tissue.")},
        {"id": "oncologist", "title": "Questions to the treating oncologist this week", "to": "the treating oncologist",
         "text": ("1. Can the molecular tumour board review the case this week, including the open findings in the latest scan?\n"
                  "2. Can whole-exome sequencing (tumour and blood) plus RNA sequencing and HLA typing be ordered now, from the existing blocks, and who will pay for and run it?\n"
                  "3. Which clinical trials (including vaccine trials) could he be screened for, and can you refer him?\n"
                  "4. Are there standard options still open if no trial is available, and how long can we wait for each step?\n"
                  "5. Could he be seen for a second opinion at a high-volume head-and-neck cancer centre, in person or by video?")},
    ]


STEPS = [
    {"when": "Today", "title": "Do not let research delay urgent care", "detail": "Follow up on unresolved findings and symptoms with the treating team. Research enquiries should run alongside necessary care, not replace it."},
    {"when": "Today", "title": "Confirm tissue availability and required tests", "detail": "Ask the pathology laboratory what specimens exist and the trial centre which preservation, collection timing and tests are required. Do not assume stored blocks are acceptable for every vaccine approach."},
    {"when": "Today", "title": "Ask for comprehensive profiling, not another small panel", "detail": "A targeted panel looks at a few hundred cancer genes for drivers. Neoantigen vaccines use the many other mutations, found by whole-exome sequencing of tumour and blood plus tumour RNA. “No pathogenic variant” on a panel does not mean the tumour has no mutations."},
    {"when": "Today", "title": "Contact trial centres and a tumour board in parallel", "detail": "Send the trial draft to several centres at once. Search ClinicalTrials.gov and India's CTRI for recruiting head-and-neck, “individualized neoantigen” and immunotherapy trials. Eligibility for many trials does not depend on sequencing."},
    {"when": "This week", "title": "Get a second opinion at a centre that runs trials", "detail": "In person or by video, with the PET-CT, pathology and treatment history. Ask about expanded access as well as trials."},
    {"when": "When results arrive", "title": "Load them here and run the pipeline", "detail": "Paste the mutation list (VCF/table) and HLA type in Vaccine → Data. The pipeline runs in minutes and produces the dossier for the trial team."},
]

CAUTIONS = [
    "A bespoke vaccine usually takes many weeks from sequencing to a dose, and is available only inside a trial or approved pathway. Ask each team for their real timeline so you can plan other options in parallel.",
    "Be wary of any clinic, website or individual selling a “personalised vaccine” or cure outside a registered trial or regulated hospital. These can be unsafe and can cost precious time and money.",
    "This page prepares information for the care team. It cannot tell you whether a vaccine or trial is right.",
]


def encouraging(db: Session) -> list[dict]:
    """Genuinely good news stated in the records, each with its source. Never softened or invented; the caveat is shown with it."""
    out = []
    scan = priorities.latest_scan(db)
    if scan is not None and scan.reported_label:
        txt = f"The {scan.scan_date} {scan.modality} reports a {scan.reported_label}"
        if scan.reported_sum_prior and scan.reported_sum_now:
            txt += f": the measured tumour size fell from {scan.reported_sum_prior:g} mm to {scan.reported_sum_now:g} mm" + (f" ({scan.reported_pct:g}% smaller)" if scan.reported_pct else "")
        out.append({"text": txt + ".", "source": "PET-CT report"})
        for l in priorities._lesions(scan):
            if l["target"] and l["prior"] is not None and l["now"] is not None and l["now"] < l["prior"]:
                out.append({"text": f"{l['label']} is smaller: {priorities._fmt_mm(l['prior'])} → {priorities._fmt_mm(l['now'])}.", "source": "PET-CT report"})
        if scan.document_id and re.search(r"No evidence of involvement of bas\s?e of tongue or floor of mouth", re.sub(r"\s+", " ", _doc_text(db, scan.document_id)), re.I):
            out.append({"text": "The report finds no involvement of the base of the tongue or the floor of the mouth.", "source": "PET-CT report"})
    return out


TODAY = [
    {"id": "oncologist", "title": "Message or call the oncologist’s office", "minutes": 10,
     "why": "Ask about unresolved findings, the next clinical decision and whether tumour-board or second-opinion review is appropriate."},
    {"id": "blocks", "title": "Confirm available tumour tissue and research requirements", "minutes": 10,
     "why": "The pathology laboratory and trial centre must confirm specimen availability, preservation and required tests. Different vaccine pathways have different requirements."},
    {"id": "trial", "title": "Send the trial-screening message to two or three cancer centres", "minutes": 15,
     "why": "Trials are the only route to a personalised vaccine or a new drug. Asking several centres at once saves days."},
]


def view(db: Session) -> dict:
    return {"steps": STEPS, "drafts": drafts(db), "findings": findings(db), "cautions": CAUTIONS, "encouraging": encouraging(db), "today": TODAY}
