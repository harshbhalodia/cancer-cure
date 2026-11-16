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
    assert "ecog" not in keys and "surgery" not in keys
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
