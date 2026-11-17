import pytest

from app.services import trials

TEXT = """Inclusion Criteria:

* Must be at least ≥ 18 years of age
* Histologically proven squamous cell carcinoma of the head and neck (HNSCC), amenable to salvage surgery. Squamous cell carcinoma of the oral cavity is allowed.
* Recurrent and/or metastatic HNSCC that has failed standard chemotherapy and immunotherapy. Eligible subjects must have progressed on ≥ 2 lines of standard of care prior to starting trial therapy.
* Must have enough tissue collected after salvage surgery (minimum weight of the resectable tumor tissue is ≥ .5 grams) and adequate cellularity (> 40%)
* Eastern Cooperative Oncology Group (ECOG) performance status 0, 1 or 2
* International normalized ratio (INR) ≤ 1.5. Anticoagulation is allowed only with low molecular weight heparin (LMWH).
* Patients who have received prior pembrolizumab are eligible

Exclusion Criteria:

* Not enough tissue collected after surgery for a planned 3 doses (weight of the resectable tumor tissue is less than 1.0 gram)
* Subjects with any active autoimmune disease
"""


def study(status="RECRUITING"):
    return {"nct_id": "NCT00000001", "title": "Test vaccine trial", "status": status, "verified": "2026-03", "last_update": "2026-03-04", "phase": "PHASE1", "enrollment": 40,
            "eligibility_text": TEXT, "min_age": "18 Years", "sex": "ALL", "central": [{"name": "Dr A", "role": "CONTACT", "phone": "1", "email": "a@example.org"}],
            "officials": [{"name": "Dr Pat Investigator, MD", "affiliation": "X", "role": "PRINCIPAL_INVESTIGATOR"}],
            "sites": [{"facility": "Site", "city": "Atlanta", "country": "United States", "status": "RECRUITING", "contacts": []}], "criteria": trials.parse_criteria(TEXT)}


def test_parse_criteria_splits_bullets_and_kinds():
    c = trials.parse_criteria(TEXT)
    assert [x["kind"] for x in c].count("inclusion") == 7 and [x["kind"] for x in c].count("exclusion") == 2
    assert all(x["text"] and not x["text"].startswith("*") for x in c)


def test_trial_flow_flags_gaps_notes_and_never_invents_support(client, monkeypatch):
    monkeypatch.setattr(trials, "fetch_study", lambda nct: study())
    a = client.post("/api/trials", json={"nct_id": "NCT00000001"}).json()
    keys = {k["key"] for k in a["key_issues"]}
    assert {"surgery", "lines", "tissue", "ecog", "clot"} <= keys
    assert a["counts"]["ok"] <= 1  # nothing is called supported without a record
    text = " ".join(a["notes"])
    assert "at least 2 lines" in text and "two different tissue minimums" in text and "No site in India" in text
    assert "Dear Dr. Pat Investigator" in a["letter"] and "overseas" in a["letter"]
    b = client.put(f"/api/trials/{a['id']}/profile", json={"ecog": "1", "surgeon_opinion": "yes", "treatment_lines": "nivolumab plus an oral tablet"}).json()
    keys = {k["key"] for k in b["key_issues"]}
    assert "ecog" in keys and "surgery" in keys  # family-reported values remain unverified
    lines = next(k for k in b["key_issues"] if k["key"] == "lines")
    assert lines["status"] == "check" and "unverified" in lines["text"]  # reported by the family, not documented
    assert "Reported by the family" in b["letter"]
    c = client.post(f"/api/trials/{a['id']}/log", json={"text": "Emailed the team"}).json()
    assert c["log"][-1]["text"] == "Emailed the team"
    assert client.get("/api/trials").json()[0]["nct_id"] == "NCT00000001"


def test_refresh_reports_registry_changes(client, monkeypatch):
    monkeypatch.setattr(trials, "fetch_study", lambda nct: study())
    a = client.post("/api/trials", json={"nct_id": "NCT00000001"}).json()
    monkeypatch.setattr(trials, "fetch_study", lambda nct: study("SUSPENDED"))
    b = client.post(f"/api/trials/{a['id']}/refresh").json()
    assert "Status changed from RECRUITING to SUSPENDED" in b["log"][-1]["text"] and any("SUSPENDED" in n for n in b["notes"])


def test_bad_trial_number_is_rejected_before_any_network_call():
    with pytest.raises(trials.TrialError):
        trials.fetch_study("not-a-trial")


def test_ecog_and_drug_rules_are_specific_and_never_invent_missing_results():
    context = {"profile": {"ecog": "2"}, "pd1_docs": [{"drug": "nivolumab", "filename": "synthetic-prescription.txt", "document_id": 1, "quote": "nivolumab given", "date": ""}]}
    ecog = trials._evaluate("ECOG performance status 0 or 1", "inclusion", context)
    assert ecog[0]["status"] == "check" and "Outside" in ecog[0]["text"]
    pd1 = trials._evaluate("Patients who have received prior pembrolizumab are eligible", "inclusion", context)
    assert pd1[0]["status"] == "check" and "interchangeable" in pd1[0]["text"]
    hiv = trials._evaluate("HIV screening required", "inclusion", context)
    assert hiv[0]["status"] == "missing" and "2024" not in hiv[0]["text"]
    assert trials._ecog_range("ECOG 0-2") == {0, 1, 2}


def test_empty_patient_has_no_pathology_support_and_unknown_criteria_stay_unknown(client, monkeypatch):
    data = study()
    data["criteria"].append({"n": 9, "kind": "inclusion", "text": "LVEF must satisfy the current protocol"})
    monkeypatch.setattr(trials, "fetch_study", lambda nct: data)
    a = client.post("/api/trials", json={"nct_id": "NCT00000001"}).json()
    assert a["criteria"][-1]["status"] == "missing"
    assert a["counts"]["ok"] == 0
    assert not any("18 mm" in f["text"] for c in a["criteria"] for f in c["findings"])


def test_trial_research_details_and_registry_snapshots_are_preserved(client, monkeypatch):
    monkeypatch.setattr(trials, "fetch_study", lambda nct: study())
    a = client.post("/api/trials", json={"nct_id": "NCT00000001"}).json()
    b = client.put(f"/api/trials/{a['id']}/profile", json={"protocol_version": "Coordinator supplied v2", "coordinator_response": "Please send records through the hospital channel.", "next_followup": "2026-12-01", "tissue_details": "Availability unknown"}).json()
    assert b["profile"]["coordinator_response"] and b["profile"]["protocol_version"]
    monkeypatch.setattr(trials, "fetch_study", lambda nct: study("SUSPENDED"))
    c = client.post(f"/api/trials/{a['id']}/refresh").json()
    assert c["snapshots"][0]["data"]["status"] == "RECRUITING"
    assert c["profile"] == b["profile"]
    assert client.put(f"/api/trials/{a['id']}/profile", json={"ecog": "9"}).status_code == 422
