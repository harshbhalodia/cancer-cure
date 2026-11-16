"""Treatment options to discuss with the oncologist, matched against what the records show.

This is education and a question list, not advice and not a ranking. Options are written once, by hand, from widely
established practice in recurrent or persistent head-and-neck squamous cell carcinoma; they are NOT derived from the
synthetic cohort (which cannot say anything about treatment results). The only patient-specific parts are the "in your
records" lines, which are read from the case. Whether any option is suitable depends on facts the treating team holds
(previous doses and agents, kidney and hearing function, fitness, the exact site of disease, what the next scan and
biopsy show).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ClinicalEvent
from app.services import fasttrack, priorities

EST = "Established standard"
PRACTICE = "Used in practice; evidence more limited"
TRIAL = "Clinical trial only"

OPTIONS = [
    {"id": "salvage_surgery", "title": "Surgery for the remaining tongue or neck disease (salvage surgery)", "evidence": EST,
     "what": "Removing residual or recurrent cancer when it can be taken out completely and the patient is fit for it.",
     "ask": ["Is the 18 mm tongue lesion removable with clear margins, and what would it cost in speech and swallowing?", "Does the right neck need surgery, and was the planned neck dissection actually done?"],
     "records": ["surgery", "residual"]},
    {"id": "radiation", "title": "More radiotherapy to a limited area (re-irradiation, focused or implant radiotherapy)", "evidence": PRACTICE,
     "what": "Treating a small area again, in selected cases, depending on the earlier dose, the time since it, and nearby structures.",
     "ask": ["What dose was given before, and is a second course safe at this site?", "Would focused (stereotactic) or implant (brachytherapy) treatment suit this lesion?"],
     "records": ["radiotherapy"]},
    {"id": "checkpoint", "title": "Immunotherapy with an immune checkpoint inhibitor (for example pembrolizumab or nivolumab)", "evidence": EST,
     "what": "Drugs that release the immune system's brake. In recurrent or metastatic head and neck cancer they are used alone or with chemotherapy, and the PD-L1 score helps guide the choice.",
     "ask": ["Has he had any immunotherapy already, and if so, did the cancer progress while on it?", "Given a PD-L1 CPS of 1–2 (interim report), is he a candidate, and is the final PD-L1 report out?"],
     "records": ["pdl1", "immunotherapy"]},
    {"id": "platinum", "title": "Platinum-based chemotherapy (cisplatin or carboplatin, often with 5-FU), with or without immunotherapy", "evidence": EST,
     "what": "The usual chemotherapy backbone for recurrent or metastatic disease. Suitability depends on kidney function, hearing, nutrition and what was already given with radiotherapy.",
     "ask": ["Was platinum given before, and does that change what comes next?", "Are his kidney function, hearing and weight good enough for it?"],
     "records": ["chemotherapy"]},
    {"id": "cetuximab", "title": "Cetuximab-containing treatment (an antibody against EGFR)", "evidence": EST,
     "what": "Added to chemotherapy in some regimens, or used after other treatments. It commonly causes skin reactions and low magnesium, which are monitored.",
     "ask": ["Is a cetuximab regimen suitable, and what monitoring would it need?"], "records": []},
    {"id": "taxane", "title": "Taxane chemotherapy (docetaxel or paclitaxel), alone or with cetuximab", "evidence": PRACTICE,
     "what": "A common choice after platinum or immunotherapy, supported by smaller studies.", "ask": ["Is a taxane an option after what he has already had?"], "records": ["chemotherapy"]},
    {"id": "metronomic", "title": "Oral low-dose (metronomic) chemotherapy, for example methotrexate with celecoxib", "evidence": PRACTICE,
     "what": "Tablets given daily at low dose, studied in randomised trials at Indian cancer centres in people who were not suited to intravenous chemotherapy. Easier to give, with a different side-effect profile.",
     "ask": ["Would an oral metronomic regimen suit him if intravenous treatment is too demanding?"], "records": []},
    {"id": "biomarker", "title": "Treatment matched to tumour biomarkers (microsatellite instability or mismatch-repair loss, high mutation burden, specific gene fusions)", "evidence": EST,
     "what": "A few approved indications apply to any tumour type when such a marker is found. They are uncommon in head and neck cancer, so the result matters only if present.",
     "ask": ["Can microsatellite/mismatch-repair testing (MSI/MMR) and a tumour mutation burden be done on the existing blocks?", "What does the PMS2 variant of uncertain significance, if confirmed on his report, mean for this?"],
     "records": ["panel"]},
    {"id": "trial", "title": "A clinical trial (including individualised neoantigen vaccines and other new agents)", "evidence": TRIAL,
     "what": "The only route to a personalised vaccine or a new drug not yet approved. Trials have eligibility rules, so ask early and in parallel.",
     "ask": ["Which trials in India or abroad could he be screened for now?", "Which tests would a trial centre need, and can they start from the existing blocks?"], "records": ["panel"]},
    {"id": "supportive", "title": "Supportive and palliative care alongside any treatment", "evidence": EST,
     "what": "Pain control, swallowing and speech support, nutrition, mouth care and emotional support. Specialist palliative care alongside cancer treatment is recommended in guidelines because it improves comfort and can help people stay well enough for treatment.",
     "ask": ["Can a palliative or supportive-care team be involved now, together with the oncologist?", "What would help most with eating, swallowing and pain?"], "records": []},
]

FIRST = [
    "Settle the neck-vein (jugular) clot first: whether it needs blood thinners is a clinical decision that affects which treatments are safe.",
    "Ask for a multidisciplinary tumour-board review: surgeon, medical oncologist, radiation oncologist and radiologist together decide which of these apply.",
]


def _events(db: Session, category: str) -> list[str]:
    return [f"{e.event_date}: {e.title}" for e in db.query(ClinicalEvent).filter(ClinicalEvent.category == category).order_by(ClinicalEvent.event_date) if e.event_date]


def view(db: Session) -> dict:
    found = {f["key"]: f for f in fasttrack.findings(db)}
    out = []
    for o in OPTIONS:
        lines = []
        for key in o["records"]:
            if key == "pdl1":
                lines.append(found["pdl1"]["text"] if "pdl1" in found else "No PD-L1 result found in the uploaded documents.")
            elif key == "panel":
                lines.append("Sequencing, MSI/MMR and tumour mutation burden: not on file.")
            elif key == "residual":
                t = {x["id"]: x for x in priorities.tracks(db)}.get("residual")
                if t:
                    lines.append("Latest scan: " + t["title"] + (f" ({' '.join(t['facts'])})" if t["facts"] else ""))
            else:
                ev = _events(db, key)
                lines.append(f"Recorded {key}: " + ("; ".join(ev) if ev else "nothing recorded in this app. Please confirm with the family and the treating team."))
        out.append({k: v for k, v in o.items() if k != "records"} | {"records": lines})
    return {"first": FIRST, "options": out,
            "note": "This is a list of options to discuss, in no order of effectiveness. It is not derived from the synthetic cohort, which cannot show which treatment works better. Only the treating team can say what suits him."}
