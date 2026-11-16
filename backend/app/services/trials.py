"""Trial matching: the registry's own eligibility text, checked line by line against the records.

The registry record is fetched from ClinicalTrials.gov (only the NCT number or generic search words leave this computer; no
patient data). Each criterion is then compared with what the uploaded documents and the family's answers actually show:

  ok       the records support it
  check    the records show something to confirm, or a likely problem
  missing  nothing on file: someone has to supply it
  routine  a standard check the study team does itself

Nothing here decides eligibility. Only the study team can, and it can only be done from the current protocol. Things the
family reports that no document backs up are labelled as such and never counted as verified.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk, Trial
from app.services import casefile, fasttrack, priorities

API = "https://clinicaltrials.gov/api/v2/studies"
FIELDS = "NCTId,BriefTitle,OverallStatus,StatusModule,DesignModule,EligibilityModule,ContactsLocationsModule"
NCT = re.compile(r"^NCT\d{8}$")


class TrialError(Exception):
    pass


# ------------------------------------------------------------------------------------------------ registry
def _get(url: str, params: dict | None = None) -> dict:
    try:
        r = httpx.get(url, params=params, timeout=25, headers={"Accept": "application/json"})
        if r.status_code == 404:
            raise TrialError("No trial with that number was found in ClinicalTrials.gov.")
        r.raise_for_status()
        return r.json()
    except TrialError:
        raise
    except httpx.HTTPError as exc:
        raise TrialError(f"Could not reach ClinicalTrials.gov ({type(exc).__name__}). Check the internet connection and try again.") from exc


def parse_criteria(text: str) -> list[dict]:
    out: list[dict] = []
    kind = "inclusion"
    for block in re.split(r"\n\s*\n", text or ""):
        head = block.strip().lower()
        if head.startswith("inclusion criteria"):
            kind = "inclusion"
        elif head.startswith("exclusion criteria"):
            kind = "exclusion"
        for line in re.split(r"\n\s*[*\-•]\s+", "\n" + block):
            line = re.sub(r"\s+", " ", line).strip()
            if len(line) > 6 and not re.match(r"^(inclusion|exclusion) criteria:?$", line, re.I):
                out.append({"n": len(out), "kind": kind, "text": line})
    return out


def fetch_study(nct: str) -> dict:
    nct = nct.strip().upper()
    if not NCT.match(nct):
        raise TrialError("A trial number looks like NCT followed by 8 digits, for example NCT06868433.")
    p = _get(f"{API}/{nct}", {"fields": FIELDS}).get("protocolSection", {})
    ident, st, des, el, loc = (p.get(k, {}) for k in ("identificationModule", "statusModule", "designModule", "eligibilityModule", "contactsLocationsModule"))
    sites = [{"facility": s.get("facility", ""), "city": s.get("city", ""), "country": s.get("country", ""), "status": s.get("status", ""),
              "contacts": [{k: c.get(k, "") for k in ("name", "role", "phone", "email")} for c in s.get("contacts", [])]} for s in loc.get("locations", [])]
    return {"nct_id": nct, "title": ident.get("briefTitle", ""), "status": st.get("overallStatus", ""), "verified": st.get("statusVerifiedDate", ""), "last_update": (st.get("lastUpdatePostDateStruct") or {}).get("date", ""),
            "phase": ", ".join(des.get("phases", [])), "enrollment": (des.get("enrollmentInfo") or {}).get("count"), "eligibility_text": el.get("eligibilityCriteria", ""),
            "min_age": el.get("minimumAge", ""), "sex": el.get("sex", ""), "central": [{k: c.get(k, "") for k in ("name", "role", "phone", "email")} for c in loc.get("centralContacts", [])],
            "officials": [{"name": o.get("name", ""), "affiliation": o.get("affiliation", ""), "role": o.get("role", "")} for o in loc.get("overallOfficials", [])], "sites": sites,
            "criteria": parse_criteria(el.get("eligibilityCriteria", ""))}


def search(term: str = "vaccine OR neoantigen", country: str = "", status: str = "RECRUITING") -> list[dict]:
    params = {"query.cond": "head and neck squamous cell carcinoma", "query.intr": term, "filter.overallStatus": status, "pageSize": 25,
              "fields": "NCTId,BriefTitle,OverallStatus,Phase,ContactsLocationsModule"}
    if country.strip():
        params["query.locn"] = country.strip()
    out = []
    for s in _get(API, params).get("studies", []):
        p = s.get("protocolSection", {})
        locs = p.get("contactsLocationsModule", {}).get("locations", [])
        out.append({"nct_id": p["identificationModule"]["nctId"], "title": p["identificationModule"].get("briefTitle", ""), "status": p["statusModule"].get("overallStatus", ""),
                    "phase": ", ".join(p.get("designModule", {}).get("phases", [])), "countries": sorted({x.get("country", "") for x in locs if x.get("country")})})
    return out


# ------------------------------------------------------------------------------------------------ the records
def _texts(db: Session) -> list[tuple[Document, str]]:
    out = []
    for d in db.query(Document).filter(Document.status == "indexed").order_by(Document.id):
        out.append((d, re.sub(r"[ \t]+", " ", "\n".join(c.text for c in db.query(DocumentChunk).filter_by(document_id=d.id).order_by(DocumentChunk.id)))))
    return out


DRUG = re.compile(r"nivolumab|opdivo|tishtha|pembrolizumab|keytruda|toripalimab|camrelizumab|atezolizumab|durvalumab", re.I)
GIVEN = re.compile(r"cycle|\bmg\b|received|given|infusion|started|dose|prescri|tab\.|inj\.", re.I)


def _documented_pd1(texts: list[tuple[Document, str]]) -> list[str]:
    hits = []
    for d, t in texts:
        if d.doc_type == "genomics":  # test reports quote drug names as boilerplate
            continue
        for m in DRUG.finditer(t):
            if GIVEN.search(t[max(0, m.start() - 80): m.end() + 80]):
                hits.append(d.filename)
                break
    return hits


def _labs(texts: list[tuple[Document, str]]) -> dict | None:
    best = None
    for d, t in texts:
        if d.doc_type != "lab" and not re.search(r"BIOCHEMISTRY|COMPLETE BLOOD COUNT", t):
            continue
        m = re.search(r"Reporting Date\.?:?\s*(\d{1,2})/(\d{1,2})/(\d{4})", t)
        when = date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None
        vals = {}
        for key, pat in (("hb", r"HAEMOGLOBIN\s+([\d.]+)"), ("platelets", r"PLATELET COUNT\s+([\d,]+)"), ("creatinine", r"S\.?\s?Creatinine:?\s+([\d.]+)"), ("alt", r"\(ALT\):?\s+([\d.]+)")):
            v = re.search(pat, t, re.I)
            if v:
                vals[key] = v.group(1)
        if vals and (best is None or (when and (best["date"] is None or when > best["date"]))):
            best = {"date": when, "file": d.filename, **vals}
    return best


def _context(db: Session, profile: dict) -> dict:
    values, _ = casefile.derive(db)
    texts = _texts(db)
    f = {x["key"]: x for x in fasttrack.findings(db)}
    age = re.search(r"\d+", str(values.get("age") or ""))
    tracks = {t["id"]: t for t in priorities.tracks(db)}
    return {"age": int(age.group(0)) if age else None, "histology": f.get("histology"), "tongue": any(re.search(r"tongue", t, re.I) for _, t in texts),
            "scan": priorities.latest_scan(db), "vessel": tracks.get("vessel"), "residual": tracks.get("residual"), "labs": _labs(texts), "pd1_docs": _documented_pd1(texts),
            "treatments": fasttrack._treatments(db), "profile": profile or {}, "recurrent_wording": any(re.search(r"appears to be recurrent|recurrent neoplastic", t, re.I) for _, t in texts)}


# ------------------------------------------------------------------------------------------------ rules
def _f(status: str, text: str, ask: str = "", key: str = "") -> dict:
    return {"status": status, "text": text, "ask": ask, "key": key}


def _lab_line(c: dict) -> str:
    lab = c["labs"]
    if not lab:
        return "No blood test results are on file."
    age_days = (date.today() - lab["date"]).days if lab["date"] else None
    bits = [f"Hb {lab['hb']} g/dL" if "hb" in lab else "", f"platelets {lab['platelets']}" if "platelets" in lab else "",
            f"creatinine {lab['creatinine']} mg/dL (that lab's range 0.7–1.3)" if "creatinine" in lab else "", f"ALT {lab['alt']}" if "alt" in lab else ""]
    return (f"The only blood test on file is from {lab['date'].strftime('%d %b %Y') if lab['date'] else 'an unknown date'}"
            + (f" ({age_days // 30} months old)" if age_days is not None else "") + f" ({lab['file']}): " + ", ".join(b for b in bits if b) + ". It cannot show today's values.")


def _evaluate(text: str, kind: str, c: dict) -> list[dict]:
    t, p, out = text.lower(), c["profile"], []

    if re.search(r"≥ ?18 years|at least.{0,6}18", t):
        out.append(_f("ok", f"He is {c['age']} years old." if c["age"] else "Age is not on file.") if c["age"] and c["age"] >= 18 else _f("missing", "Age is not on file."))
    if re.search(r"histolog|squamous", t):
        h = c["histology"]
        if kind == "inclusion" and h:
            out.append(_f("ok", f"Pathology on file: {h['text']} ({h['filename']})."))
        if re.search(r"sarcomatoid|differentiation", (h or {}).get("text", ""), re.I):
            out.append(_f("check", "His pathology says “with sarcomatoid differentiation”. This trial accepts squamous cell carcinoma and excludes non-squamous histology.",
                          "His pathology report describes invasive squamous cell carcinoma with sarcomatoid differentiation. Does this count as squamous cell carcinoma for eligibility?", "histology"))
        if "oral cavity" in t and c["tongue"]:
            out.append(_f("ok", "Oral cavity (tongue) is one of the accepted sites."))
    if "non-squamous" in t and not any(x["status"] == "check" for x in out):
        out.append(_f("ok", "Pathology on file is squamous cell carcinoma."))
    if "salvage surgery" in t and kind == "inclusion":
        s = p.get("surgeon_opinion")
        if s == "yes":
            out.append(_f("ok", "The surgeon has said the current disease can be removed with curative intent (as you recorded)."))
        elif s == "no":
            out.append(_f("check", "The surgeon has said it cannot be removed with curative intent (as you recorded). This trial requires salvage surgery.", "", "surgery"))
        else:
            out.append(_f("missing", "Needs the head-and-neck surgeon’s opinion on whether the current disease can be removed with curative intent. The scan shows a residual 18 mm lesion, which may or may not be removable.",
                          "If his recurrent tongue cancer is judged removable by salvage surgery, can the surgery and tissue collection be done under the study, and where?", "surgery"))
    if re.search(r"tissue|cellularity|gram|banked", t):
        out.append(_f("missing", "No information on file about tumour tissue available for the study (amount, % tumour cells, whether it is frozen). The study wants fresh tissue collected at salvage surgery.",
                      "Can previously stored tissue (FFPE blocks) be used, or must fresh tissue be collected during surgery? What is the exact minimum tissue weight?", "tissue"))
    if re.search(r"\blines?\b|regimens?|progressed on|failed standard", t):
        txt = (p.get("treatment_lines") or "").strip()
        if txt:
            out.append(_f("check", f"You reported: “{txt}”. No uploaded document confirms the drugs, dates or why each stopped, so this is unverified.",
                          "How does the protocol count lines of treatment (for example, immunotherapy plus oral chemotherapy given together)?", "lines"))
        else:
            rec = "; ".join(c["treatments"]) or "no treatment events"
            out.append(_f("missing", f"The documents on file record only: {rec}. No document names the drugs given for recurrent disease, their dates, or when they stopped or failed.",
                          "How does the protocol count lines of treatment, and what documentation of prior treatments is required?", "lines"))
        if re.search(r"recurrent", t) and c["recurrent_wording"]:
            out.append(_f("check", "The PET-CT says the tongue lesion “appears to be recurrent”. That is an imaging impression, not a biopsy result.", "Is biopsy confirmation of recurrence required?", "recurrence"))
    if re.search(r"pembrolizumab|nivolumab|immunotherapy|checkpoint|monoclonal", t) and "hypersensitivity" not in t and kind == "inclusion":
        docs = c["pd1_docs"]
        out.append(_f("ok", f"Anti-PD-1 treatment is documented in: {', '.join(docs)}.") if docs else
                   _f("missing", "No uploaded document shows nivolumab, pembrolizumab or any other immunotherapy being given. If he is on one, upload the prescription or a photo of the packaging.",
                      "Is prior nivolumab (rather than pembrolizumab) acceptable? The listing explicitly permits pembrolizumab but does not mention nivolumab.", "pd1"))
    if re.search(r"ecog|performance status", t):
        e = str(p.get("ecog", ""))
        out.append(_f("ok", f"ECOG {e} (as recorded by you).") if e in ("0", "1", "2") else _f("check", f"ECOG {e} is outside the accepted range.") if e in ("3", "4") else
                   _f("missing", "ECOG performance status is not recorded anywhere. His oncologist assigns it (0 = fully active, 2 = up and about more than half the day but unable to work).", "", "ecog"))
    if re.search(r"measurable|recist", t):
        out.append(_f("check", "The PET-CT gives measurements (tongue lesion 18 mm; right neck node 4 mm). The trial’s radiologists decide what counts as measurable by RECIST, which is normally judged on CT or MRI; a 4 mm node would not count.",
                      "Is the residual tongue lesion measurable by RECIST on CT or MRI? Do you need a new scan?", "measurable") if c["scan"] else _f("missing", "No scan on file."))
    if re.search(r"neutrophil|platelet|hemoglobin|bilirubin|aspartate|alanine|albumin|creatinine", t):
        out.append(_f("check", _lab_line(c), "", "labs"))
    if re.search(r"\binr\b|anticoag|bleeding|coagulopathy", t):
        v, a = c["vessel"], p.get("anticoagulant", "")
        base = ("He has a reported right internal jugular vein thrombosis (PET-CT, 2 Nov 2026), which should be disclosed. " if v else "") + "No INR result is on file."
        if a == "lmwh":
            out.append(_f("check", base + " You recorded low-molecular-weight heparin: the trial allows only that, on a stable dose for over 2 weeks.", "He has a vein clot on LMWH. Does that fit the INR and anticoagulation rules, and what surgical bleeding precautions apply?", "clot"))
        elif a in ("other", "none", ""):
            out.append(_f("check", base + (f" Anticoagulant recorded: {a}." if a else " Whether he is on a blood thinner is not recorded.") + " Only low-molecular-weight heparin is allowed.",
                          "He has a reported neck-vein clot. How is a clot and any blood thinner handled in the protocol?", "clot"))
    if re.search(r"immunosuppress|autoimmune|corticosteroid|prednisone", t):
        a = p.get("autoimmune_or_steroids", "")
        out.append(_f("ok", "You recorded no autoimmune disease or steroid use.") if a == "no" else _f("check", "You recorded an autoimmune condition or steroid use: tell the study team.") if a == "yes" else
                   _f("missing", "Not recorded: any autoimmune disease, and steroid or immunosuppressant use within 14 days.", "", "autoimmune"))
    if re.search(r"prior malignanc", t):
        out.append(_f("missing", "No other cancers are recorded in the documents; confirm there are none in the last 5 years.", "", "priormalig"))
    if re.search(r"hiv", t):
        out.append(_f("routine", "An HIV screening test on 25 Dec 2024 was non-reactive (old; the study team will repeat what it needs)."))
    if re.search(r"pregnan|childbearing|contracepti", t):
        out.append(_f("routine", "Mostly about women; for men the study asks for contraception during the study."))
    return out


ORDER = {"check": 0, "missing": 1, "routine": 2, "ok": 3}
KEY_PRIORITY = ["surgery", "lines", "histology", "tissue", "pd1", "clot", "ecog", "labs", "recurrence", "measurable", "autoimmune", "priormalig"]


def assess(db: Session, trial: Trial) -> dict:
    c = _context(db, trial.profile)
    data = trial.data
    crits = []
    for cr in data.get("criteria", []):
        findings = _evaluate(cr["text"], cr["kind"], c)
        status = min((x["status"] for x in findings), key=lambda s: ORDER[s]) if findings else "routine"
        if not findings:
            findings = [_f("routine", "A standard check the study team does itself.")]
        crits.append({**cr, "status": status, "findings": findings})
    counts = {s: sum(1 for x in crits if x["status"] == s) for s in ("ok", "check", "missing", "routine")}
    keyed: dict[str, dict] = {}
    for cr in crits:
        for fnd in cr["findings"]:
            if fnd["key"] and fnd["status"] in ("check", "missing") and fnd["key"] not in keyed:
                keyed[fnd["key"]] = {"key": fnd["key"], "status": fnd["status"], "text": fnd["text"], "ask": fnd["ask"], "criterion": cr["text"][:160]}
    key_issues = sorted(keyed.values(), key=lambda k: KEY_PRIORITY.index(k["key"]) if k["key"] in KEY_PRIORITY else 99)
    text = data.get("eligibility_text", "")
    notes = []
    if re.search(r"progressed on ≥ ?2 lines", text):
        notes.append("This registry text requires progression on at least 2 lines of standard treatment, and allows up to 3 regimens after the cancer became recurrent or metastatic. Other summaries of the same trial can say 1 line: ask for the current protocol in writing.")
    if re.search(r"≥ ?\.?0?\.?5 grams?", text) and re.search(r"less than 1\.0 gram", text):
        notes.append("The registry text gives two different tissue minimums (at least 0.5 g in inclusion, under 1.0 g as an exclusion). Ask which applies.")
    if re.search(r"banked.{0,60}salvage surgery|salvage surgery.{0,120}(informed consent|ICF)", text, re.S | re.I):
        notes.append("The tumour tissue is collected at the salvage surgery after the first consent is signed, so the operation is part of taking part. Ask whether it must be done at the trial site, which for a US site means travel and a stay.")
    sites = [s for s in data.get("sites", []) if s.get("status", "").upper() in ("RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION")]
    countries = sorted({s["country"] for s in sites if s.get("country")})
    if sites and "India" not in countries:
        notes.append(f"Recruiting sites are listed only in: {', '.join(countries) or 'unknown'}. No site in India is listed, so ask about overseas participation.")
    if data.get("status") and data["status"] != "RECRUITING":
        notes.append(f"Registry status is {data['status']}: confirm it is still enrolling.")
    return {"id": trial.id, "nct_id": trial.nct_id, "title": trial.title, "status": trial.status, "phase": data.get("phase", ""), "verified": data.get("verified", ""),
            "last_update": data.get("last_update", ""), "enrollment": data.get("enrollment"), "fetched_at": trial.fetched_at.isoformat() if trial.fetched_at else "",
            "counts": counts, "key_issues": key_issues, "notes": notes, "criteria": crits, "profile": trial.profile or {}, "log": trial.log or [], "central": data.get("central", []),
            "officials": data.get("officials", []), "sites": sites, "letter": letter(db, trial, c, key_issues, notes),
            "url": f"https://clinicaltrials.gov/study/{trial.nct_id}"}


def letter(db: Session, trial: Trial, c: dict, issues: list[dict], notes: list[str]) -> str:
    summary = fasttrack._clinical_summary(db)
    pi = next((o["name"] for o in trial.data.get("officials", []) if o.get("role") == "PRINCIPAL_INVESTIGATOR"), "")
    qs, seen = [], set()
    for i in issues:
        if i["ask"] and i["ask"] not in seen:
            seen.add(i["ask"])
            qs.append(i["ask"])
    qs += ["Are patients from India eligible, and what arrangements exist for overseas participants?" if any("No site in India" in n for n in notes) else "",
           "Can you give a preliminary eligibility view from his pathology, treatment history and PET-CT, and tell us the current protocol version?"]
    reported = (c["profile"].get("treatment_lines") or "").strip()
    name = re.sub(r"^(dr\.?\s+)+", "", pi.split(",")[0].strip(), flags=re.I)
    body = [f"Dear {('Dr. ' + name) if name else 'Study team'} and research team,", "",
            f"I am writing on behalf of my father about your study {trial.nct_id} ({trial.title}). His records show:", ""]
    body += [f"- {s}" for s in summary]
    if reported:
        body += ["", f"Reported by the family (not yet backed by documents; we will send the prescriptions): {reported}"]
    body += ["", "Could you please tell us:"] + [f"{n}. {q}" for n, q in enumerate([q for q in qs if q], 1)]
    body += ["", "We can send his pathology, treatment records and PET-CT for preliminary review. Thank you for your time."]
    return "\n".join(body)


# ------------------------------------------------------------------------------------------------ storage
def _log(trial: Trial, text: str) -> None:
    trial.log = [*(trial.log or []), {"when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "text": text}]


def add(db: Session, nct: str) -> Trial:
    d = fetch_study(nct)
    row = db.query(Trial).filter_by(nct_id=d["nct_id"]).first()
    if row is None:
        row = Trial(nct_id=d["nct_id"])
        db.add(row)
        _log(row, f"Added from ClinicalTrials.gov (status {d['status']}, registry last updated {d['last_update']}).")
    row.title, row.status, row.data, row.fetched_at = d["title"], d["status"], d, datetime.now(timezone.utc)
    db.commit()
    return row


def refresh(db: Session, trial: Trial) -> list[str]:
    new = fetch_study(trial.nct_id)
    old = trial.data or {}
    changes = []
    if new["status"] != old.get("status"):
        changes.append(f"Status changed from {old.get('status')} to {new['status']}.")
    if new["eligibility_text"] != old.get("eligibility_text"):
        changes.append("The eligibility criteria text changed. Re-read the criteria below.")
    if {(s["facility"], s["status"]) for s in new["sites"]} != {(s["facility"], s["status"]) for s in old.get("sites", [])}:
        changes.append("Sites or their recruiting status changed.")
    trial.title, trial.status, trial.data, trial.fetched_at = new["title"], new["status"], new, datetime.now(timezone.utc)
    _log(trial, "Re-checked the registry: " + (" ".join(changes) if changes else "no changes."))
    db.commit()
    return changes


def set_profile(db: Session, trial: Trial, profile: dict) -> None:
    allowed = {"ecog": {"", "0", "1", "2", "3", "4"}, "surgeon_opinion": {"", "yes", "no"}, "anticoagulant": {"", "none", "lmwh", "other"}, "autoimmune_or_steroids": {"", "yes", "no"}}
    clean = dict(trial.profile or {})
    for k, vals in allowed.items():
        if k in profile and str(profile[k]) in vals:
            clean[k] = str(profile[k])
    if "treatment_lines" in profile:
        clean["treatment_lines"] = str(profile["treatment_lines"])[:600]
    trial.profile = clean
    db.commit()


def add_log(db: Session, trial: Trial, text: str) -> None:
    _log(trial, text.strip()[:600])
    db.commit()
