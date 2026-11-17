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
import copy
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
    record = _get(f"{API}/{nct}")
    p = record.get("protocolSection", {})
    ident, st, des, el, loc = (p.get(k, {}) for k in ("identificationModule", "statusModule", "designModule", "eligibilityModule", "contactsLocationsModule"))
    sites = [{"facility": s.get("facility", ""), "city": s.get("city", ""), "country": s.get("country", ""), "status": s.get("status", ""),
              "contacts": [{k: c.get(k, "") for k in ("name", "role", "phone", "email")} for c in s.get("contacts", [])]} for s in loc.get("locations", [])]
    return {"nct_id": nct, "title": ident.get("briefTitle", ""), "status": st.get("overallStatus", ""), "verified": st.get("statusVerifiedDate", ""), "last_update": (st.get("lastUpdatePostDateStruct") or {}).get("date", ""),
            "phase": ", ".join(des.get("phases", [])), "enrollment": (des.get("enrollmentInfo") or {}).get("count"), "eligibility_text": el.get("eligibilityCriteria", ""),
            "min_age": el.get("minimumAge", ""), "sex": el.get("sex", ""), "central": [{k: c.get(k, "") for k in ("name", "role", "phone", "email")} for c in loc.get("centralContacts", [])],
            "officials": [{"name": o.get("name", ""), "affiliation": o.get("affiliation", ""), "role": o.get("role", "")} for o in loc.get("overallOfficials", [])], "sites": sites,
            "criteria": parse_criteria(el.get("eligibilityCriteria", "")),
            "summary": p.get("descriptionModule", {}).get("briefSummary", ""),
            "description": p.get("descriptionModule", {}).get("detailedDescription", ""),
            "arms": p.get("armsInterventionsModule", {}).get("armGroups", []),
            "outcomes": p.get("outcomesModule", {}),
            "has_results": record.get("hasResults", False)}


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


def _documented_pd1(texts: list[tuple[Document, str]]) -> list[dict]:
    hits = []
    for d, t in texts:
        if d.doc_type == "genomics":  # test reports quote drug names as boilerplate
            continue
        for m in DRUG.finditer(t):
            excerpt = t[max(0, m.start() - 80): m.end() + 80]
            if GIVEN.search(excerpt) and not re.search(r"\b(not received|never received|not given|consider|planned|may receive)\b", excerpt, re.I):
                name = m.group(0).lower()
                drug = "pembrolizumab" if name in ("pembrolizumab", "keytruda") else "nivolumab" if name in ("nivolumab", "opdivo", "tishtha") else name
                hits.append({"drug": drug, "filename": d.filename, "document_id": d.id, "quote": excerpt, "date": d.doc_date})
    return hits


def _labs(texts: list[tuple[Document, str]]) -> dict | None:
    best = None
    for d, t in texts:
        if d.doc_type != "lab" and not re.search(r"BIOCHEMISTRY|COMPLETE BLOOD COUNT", t):
            continue
        m = re.search(r"Reporting Date\.?:?\s*(\d{1,2})/(\d{1,2})/(\d{4})", t)
        when = None
        if m:
            try:
                when = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError as exc:
                raise TrialError(f"Invalid reporting date in {d.filename}; correct the document date before assessing laboratory results.") from exc
        vals = {}
        for key, pat in (("hb", r"HAEMOGLOBIN\s+([\d.]+)"), ("platelets", r"PLATELET COUNT\s+([\d,]+)"), ("creatinine", r"S\.?\s?Creatinine:?\s+([\d.]+)"), ("alt", r"\(ALT\):?\s+([\d.]+)")):
            v = re.search(pat, t, re.I)
            if v:
                vals[key] = v.group(1)
        if vals and (best is None or (when and (best["date"] is None or when > best["date"]))):
            best = {"date": when, "file": d.filename, **vals}
    return best


def _context(db: Session, profile: dict) -> dict:
    values, meta = casefile.derive(db)
    texts = _texts(db)
    f = {x["key"]: x for x in fasttrack.findings(db)}
    age = re.search(r"\d+", str(values.get("age") or ""))
    tracks = {t["id"]: t for t in priorities.tracks(db)}
    return {"age": int(age.group(0)) if age else None, "age_source": meta["age"], "histology": f.get("histology"), "tongue": any(re.search(r"tongue", t, re.I) for _, t in texts),
            "scan": priorities.latest_scan(db), "vessel": tracks.get("vessel"), "residual": tracks.get("residual"), "labs": _labs(texts), "pd1_docs": _documented_pd1(texts),
            "treatments": fasttrack._treatments(db), "profile": profile or {}, "recurrent_wording": any(re.search(r"appears to be recurrent|recurrent neoplastic", t, re.I) for _, t in texts)}


# ------------------------------------------------------------------------------------------------ rules
def _f(status: str, text: str, ask: str = "", key: str = "", evidence: dict | None = None) -> dict:
    return {"status": status, "text": text, "ask": ask, "key": key, "evidence": evidence or {}}


def _ecog_range(text: str) -> set[int] | None:
    match = re.search(r"(?:performance status|ecog)[^0-4]{0,40}([0-4](?:\s*(?:,|or|and|[-–]|to)\s*[0-4])*)", text, re.I)
    if not match:
        return None
    values = [int(v) for v in re.findall(r"[0-4]", match.group(1))]
    if re.search(r"[-–]|\bto\b", match.group(1)) and len(values) == 2:
        return set(range(values[0], values[1] + 1))
    return set(values)


def _lab_line(c: dict) -> str:
    lab = c["labs"]
    if not lab:
        return "No blood test results are on file."
    age_days = (date.today() - lab["date"]).days if lab["date"] else None
    bits = [f"Hb {lab['hb']} g/dL" if "hb" in lab else "", f"platelets {lab['platelets']}" if "platelets" in lab else "",
            f"creatinine {lab['creatinine']} mg/dL" if "creatinine" in lab else "", f"ALT {lab['alt']}" if "alt" in lab else ""]
    return (f"Available blood test results are from {lab['date'].strftime('%d %b %Y') if lab['date'] else 'an unknown date'}"
            + (f" ({age_days // 30} months old)" if age_days is not None else "") + f" ({lab['file']}): " + ", ".join(b for b in bits if b) + ". It cannot show today's values.")


def _evaluate(text: str, kind: str, c: dict) -> list[dict]:
    t, p, out = text.lower(), c["profile"], []

    if kind == "inclusion" and re.search(r"\bage\b|\baged\b|years", t):
        minimum = re.search(r"(?:≥|>=|at least)\s*(?:≥\s*)?(\d+)", t)
        age_range = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*(?:years|years of age)", t)
        if c.get("age") is None:
            out.append(_f("missing", "Age is not on file.", key="age"))
        elif minimum or age_range:
            fits = c["age"] >= int(minimum.group(1)) if minimum else int(age_range.group(1)) <= c["age"] <= int(age_range.group(2))
            documented = c.get("age_source", {}).get("source") == "document"
            out.append(_f("ok" if fits and documented else "check", f"Recorded age: {c['age']}. " + ("Within the stated range; verify age and date at screening." if fits else "Outside the stated age range.") + ("" if documented else " User-reported, unverified."), key="age", evidence=c.get("age_source")))
        else:
            out.append(_f("check", "The age rule could not be interpreted reliably. Ask the study team.", key="age"))
    if re.search(r"histolog|squamous", t):
        h = c["histology"]
        if kind == "inclusion":
            out.append(_f("check" if h else "missing", f"Pathology on file: {h['text']} ({h['filename']}). The study team must confirm the accepted histology." if h else "No sourced pathology is available for this histology criterion.", key="histology", evidence=h))
        if re.search(r"sarcomatoid|differentiation", (h or {}).get("text", ""), re.I):
            out.append(_f("check", "The pathology records sarcomatoid differentiation. The investigator must review how this fits the histology criterion.",
                          "Does the recorded sarcomatoid differentiation meet your protocol's histology requirements?", "histology", h))
        if "oral cavity" in t and c["tongue"]:
            out.append(_f("check", "Documents mention the tongue; oral cavity is listed in this criterion. Confirm the primary site from the pathology.", key="histology"))
    if "non-squamous" in t and not any(x["status"] == "check" for x in out):
        out.append(_f("check" if c.get("histology") else "missing", "Review the pathology against this exclusion; absence of a report does not establish squamous histology.", key="histology"))
    if "salvage surgery" in t and kind == "inclusion":
        s = p.get("surgeon_opinion")
        if s == "yes":
            out.append(_f("check", "You report that the surgeon considers salvage surgery feasible. This is unverified; ask the study team to review the surgical opinion.", key="surgery"))
        elif s == "no":
            out.append(_f("check", "The surgeon has said it cannot be removed with curative intent (as you recorded). This trial requires salvage surgery.", "", "surgery"))
        else:
            out.append(_f("missing", "A sourced surgeon's opinion on feasibility of salvage surgery is needed. Imaging alone cannot establish operability.",
                          "Does the patient meet the surgical criterion, and where must surgery and tissue collection occur?", "surgery"))
    if re.search(r"tissue|cellularity|gram|banked", t):
        tissue = p.get("tissue_details", "")
        out.append(_f("check" if tissue else "missing", f"User-reported tissue information (unverified): {tissue}" if tissue else "Tissue availability, collection timing, preservation and cellularity have not been confirmed for this criterion.",
                      "Which stored or fresh tissue is acceptable, what amount is needed, and when must consent and collection occur?", "tissue"))
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
            out.append(_f("check", "A document uses possible-recurrence wording. That is an imaging impression, not biopsy confirmation.", "Is biopsy confirmation of recurrence required?", "recurrence"))
    if re.search(r"pembrolizumab|nivolumab|immunotherapy|checkpoint|monoclonal", t) and "hypersensitivity" not in t and kind == "inclusion":
        docs = c["pd1_docs"]
        if docs:
            names = sorted({d["drug"] for d in docs})
            named = {drug for drug in ("pembrolizumab", "nivolumab") if drug in t}
            permissive = bool(re.search(r"prior|previous", t) and re.search(r"eligible|allowed|permitted", t))
            exact = permissive and bool(named) and named <= set(names)
            out.append(_f("ok" if exact else "check", "Treatment mentions in documents: " + ", ".join(f"{d['drug']} ({d['filename']})" for d in docs) + ". " +
                          ("The named drug is recorded; this does not establish dates, progression or overall eligibility." if exact else "Drug classes are not interchangeable, and a mention does not prove treatment failure."),
                          "Does the documented prior treatment satisfy this exact criterion, including drug, dates and progression?", "pd1", {"records": docs}))
        else:
            out.append(_f("missing", "No sourced record of the relevant immunotherapy being given is available.",
                          "Which prior immunotherapies are accepted, and what evidence of treatment and progression is required?", "pd1"))
    if re.search(r"ecog|performance status", t):
        e = str(p.get("ecog", ""))
        allowed = _ecog_range(t)
        if e not in ("0", "1", "2", "3", "4"):
            out.append(_f("missing", "ECOG is unknown. Ask the oncologist to assess and document it.", key="ecog"))
        else:
            range_note = "The permitted range could not be interpreted reliably." if allowed is None else "Within the stated range." if int(e) in allowed else "Outside the stated range."
            out.append(_f("check", f"ECOG {e}, reported by you and unverified. {range_note}", "Please confirm the current clinician-assessed ECOG against this criterion.", "ecog"))
    if re.search(r"measurable|recist", t):
        scan = c.get("scan")
        measurements = "; ".join(f"{l['label']}: {l['now']:g} mm" for l in priorities._lesions(scan) if l["now"] is not None) if scan else ""
        out.append(_f("check" if scan else "missing", f"Recorded scan {scan.scan_date}: {measurements or 'no measurements confirmed'}. " + "The study radiologist must assess measurable disease; the app's size arithmetic is not formal RECIST." if scan else "No confirmed scan is on file.",
                      "Is disease measurable under the protocol, and is new CT or MRI required?", "measurable"))
    if re.search(r"neutrophil|platelet|hemoglobin|bilirubin|aspartate|alanine|albumin|creatinine", t):
        out.append(_f("check", _lab_line(c), "", "labs"))
    if re.search(r"\binr\b|anticoag|bleeding|coagulopathy", t):
        v, a = c["vessel"], p.get("anticoagulant", "")
        base = (f"An open vascular finding is recorded: {v['title']}. " if v else "") + "Current INR/coagulation results have not been confirmed against this criterion."
        note = f" Anticoagulant reported by you (unverified): {a}." if a else " Current anticoagulation is unknown."
        out.append(_f("check", base + note, "How does the patient's vascular finding, coagulation status and any anticoagulant fit this exact criterion? Do not change medicines to meet eligibility.", "clot"))
    if re.search(r"immunosuppress|autoimmune|corticosteroid|prednisone", t):
        a = p.get("autoimmune_or_steroids", "")
        out.append(_f("check", f"Autoimmune disease / steroid use reported by you: {a} (unverified). Ask the team to review medication history and the protocol's timing.") if a in ("no", "yes") else
                   _f("missing", "Autoimmune history and steroid or immunosuppressant use are unknown.", key="autoimmune"))
    if re.search(r"prior malignanc", t):
        out.append(_f("missing", "Prior malignancy history has not been confirmed against this criterion.", "", "priormalig"))
    if re.search(r"hiv", t):
        out.append(_f("missing", "HIV status is not established by this assessment. Ask the study team which sourced screening results it requires.", key="screening"))
    if re.search(r"pregnan|childbearing|contracepti", t):
        out.append(_f("routine", "The study team must determine which pregnancy, reproductive and contraception requirements apply."))
    return out


ORDER = {"check": 0, "missing": 1, "routine": 2, "ok": 3}
KEY_PRIORITY = ["surgery", "lines", "histology", "tissue", "pd1", "clot", "ecog", "labs", "recurrence", "measurable", "autoimmune", "priormalig"]


def assess(db: Session, trial: Trial) -> dict:
    c = _context(db, trial.profile)
    data = trial.data
    crits = []
    for cr in data.get("criteria", []):
        findings = _evaluate(cr["text"], cr["kind"], c)
        status = min((x["status"] for x in findings), key=lambda s: ORDER[s]) if findings else "missing"
        if not findings:
            findings = [_f("missing", "This criterion is not evaluated by the app. Coordinator confirmation is needed.", key=f"criterion_{cr['n']}")]
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
        notes.append("This registry text requires progression on at least 2 lines of standard treatment. Confirm how those lines are counted in the current protocol.")
    if re.search(r"up to 3", text) and re.search(r"no restriction on prior lines", text):
        notes.append("The registry says both up to 3 regimens and no restriction on prior lines. Ask the investigator to resolve this contradiction.")
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
    notes.append("Criterion checks are incomplete and do not decide eligibility. Reported family answers remain unverified; obtain coordinator confirmation.")
    if data.get("has_results") is False:
        notes.append("No results are posted in this registry record. Listed endpoints are planned measurements, not observed benefits.")
    return {"id": trial.id, "nct_id": trial.nct_id, "title": trial.title, "status": trial.status, "phase": data.get("phase", ""), "verified": data.get("verified", ""),
            "last_update": data.get("last_update", ""), "enrollment": data.get("enrollment"), "fetched_at": trial.fetched_at.isoformat() if trial.fetched_at else "",
            "counts": counts, "key_issues": key_issues, "notes": notes, "criteria": crits, "profile": trial.profile or {}, "log": trial.log or [], "central": data.get("central", []),
            "officials": data.get("officials", []), "sites": sites, "letter": letter(db, trial, c, key_issues, notes),
            "url": f"https://clinicaltrials.gov/study/{trial.nct_id}", "summary": data.get("summary", ""),
            "arms": data.get("arms", []), "outcomes": data.get("outcomes", {}),
            "has_results": data.get("has_results"), "snapshots": data.get("snapshots", [])}


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
            f"I am writing on behalf of the patient about your study {trial.nct_id} ({trial.title}). The records show:", ""]
    body += [f"- {s}" for s in summary]
    if reported:
        body += ["", f"Reported by the family (not yet backed by documents; we will send the prescriptions): {reported}"]
    body += ["", "Could you please tell us:"] + [f"{n}. {q}" for n, q in enumerate([q for q in qs if q], 1)]
    body += ["", "We can send his pathology, treatment records and PET-CT for preliminary review. Thank you for your time."]
    return "\n".join(body)


# ------------------------------------------------------------------------------------------------ storage
def _log(trial: Trial, text: str) -> None:
    trial.log = [*(trial.log or []), {"when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "text": text}]


def _store_registry(row: Trial, data: dict) -> None:
    previous = row.data or {}
    snapshots = copy.deepcopy(previous.get("snapshots", []))
    if previous:
        snapshots.append({"fetched_at": row.fetched_at.isoformat() if row.fetched_at else "",
                          "data": copy.deepcopy({k: v for k, v in previous.items() if k != "snapshots"})})
    row.title, row.status, row.data, row.fetched_at = data["title"], data["status"], {**data, "snapshots": snapshots}, datetime.now(timezone.utc)


def add(db: Session, nct: str) -> Trial:
    d = fetch_study(nct)
    row = db.query(Trial).filter_by(nct_id=d["nct_id"]).first()
    if row is None:
        row = Trial(nct_id=d["nct_id"])
        db.add(row)
        _log(row, f"Added from ClinicalTrials.gov (status {d['status']}, registry last updated {d['last_update']}).")
    _store_registry(row, d)
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
    _store_registry(trial, new)
    _log(trial, "Re-checked the registry: " + (" ".join(changes) if changes else "no changes."))
    db.commit()
    return changes


def set_profile(db: Session, trial: Trial, profile: dict) -> None:
    allowed = {"ecog": {"", "0", "1", "2", "3", "4"}, "surgeon_opinion": {"", "yes", "no"}, "anticoagulant": {"", "none", "lmwh", "other"}, "autoimmune_or_steroids": {"", "yes", "no"}}
    clean = dict(trial.profile or {})
    text_fields = {"treatment_lines": 1000, "protocol_version": 200, "coordinator_response": 4000,
                   "tissue_details": 2000, "logistics": 2000, "next_followup": 10}
    unknown = set(profile) - set(allowed) - set(text_fields)
    if unknown:
        raise ValueError("Unknown trial profile fields: " + ", ".join(sorted(unknown)))
    for k, vals in allowed.items():
        if k in profile and str(profile[k]) not in vals:
            raise ValueError(f"Invalid value for {k}.")
        if k in profile and str(profile[k]) in vals:
            clean[k] = str(profile[k])
    for key, maximum in text_fields.items():
        if key in profile:
            if not isinstance(profile[key], str) or len(profile[key]) > maximum:
                raise ValueError(f"{key} must be text of at most {maximum} characters.")
            value = profile[key].strip()
            if key == "next_followup" and value and date.fromisoformat(value).isoformat() != value:
                raise ValueError("Follow-up date must use YYYY-MM-DD.")
            clean[key] = value
    trial.profile = clean
    _log(trial, "User-reported profile updated; answers remain unverified. Fields: " + ", ".join(sorted(profile)))
    db.commit()


def add_log(db: Session, trial: Trial, text: str) -> None:
    _log(trial, text.strip()[:600])
    db.commit()
