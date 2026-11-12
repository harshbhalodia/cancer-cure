from datetime import date

import pytest

from app.services import llm, response, scan_extract
from tests.conftest import SAMPLE_REPORT

TODAY = date(2026, 11, 11)

REPORT = SAMPLE_REPORT + """
Thrombosis of right internal jugular vein is seen with increased activity. SUV Max.: 12.
Lymphnode in right level III appears metastatic.
Sr. No. Target lesion Previous measurement (MRI: 22-07-2026) Current measurement
1. Left tongue lesion 34 mm 18 mm
2. Right neck node 8 mm 4 mm
Sum of target lesion diameter previously: 42 mm. Sum of target lesion diameter currently: 22 mm.
Percentage change: 47.7%. STATUS: Partial Response (PR).
"""

GOOD = {
    "study": {"modality": "PET-CT", "date": "2026-11-02", "comparator": {"modality": "MRI", "date": "2026-07-22"}},
    "lesions": [
        {"name": "Left tongue lesion", "is_target": True, "size_mm_now": 18, "size_mm_prior": 34, "suv_max_now": 10.8,
         "quote": "1. Left tongue lesion 34 mm 18 mm"},
        {"name": "Right neck node", "is_target": True, "basis": "short_axis", "size_mm_now": 4, "size_mm_prior": 8,
         "quote": "2. Right neck node 8 mm 4 mm"},
    ],
    "findings": [
        {"text": "Right level III node appears metastatic", "category": "nodal", "certainty": "possible", "quote": "Lymphnode in right level III appears metastatic."},
        {"text": "Thrombosis of right internal jugular vein", "category": "vascular", "certainty": "definite",
         "quote": "Thrombosis of right internal jugular vein is seen with increased activity."},
    ],
    "reported_response": {"label": "Partial Response", "sum_prior_mm": 42, "sum_now_mm": 22, "percent_change": 47.7,
                          "quote": "Percentage change: 47.7%. STATUS: Partial Response (PR)."},
}


def P(label, size):
    return response.Point(label.lower(), label, size)


def test_compare_partial_response_matches_report_arithmetic():
    c = response.compare([P("a", 34), P("b", 8)], [P("a", 18), P("b", 4)])
    assert (c.sum_prior, c.sum_now, c.pct_change, c.category) == (42.0, 22.0, -47.6, "partial_response")


@pytest.mark.parametrize("prior,now,cat", [(40, 41, "stable_disease"), (40, 50, "progressive_disease"), (10, 13, "stable_disease"), (10, 7, "partial_response")])
def test_classify_thresholds(prior, now, cat):
    assert response.classify(prior, now)[1] == cat


def test_progression_needs_five_mm_absolute():
    assert response.classify(10, 12.5)[1] == "stable_disease"  # +25% but only 2.5 mm


def test_compare_only_uses_lesions_measured_both_times():
    c = response.compare([P("a", 30), P("b", 10)], [P("a", 15)])
    assert (c.sum_prior, c.sum_now) == (30.0, 15.0)
    assert response.compare([P("a", 30)], [P("z", 5)]) is None


def test_validate_accepts_supported_items():
    v = scan_extract.validate(GOOD, REPORT, "2026-11-02")
    assert v["rejected"] == [] and len(v["lesions"]) == 2 and len(v["findings"]) == 2


def test_validate_rejects_fabricated_quote_number_and_date():
    bad = {
        "study": {"date": "2026-11-02", "comparator": {"date": "2025-01-01"}},
        "lesions": [
            {"name": "Invented", "size_mm_now": 18, "quote": "A lesion that is not in this report anywhere at all"},
            {"name": "Wrong number", "size_mm_now": 99, "quote": "1. Left tongue lesion 34 mm 18 mm"},
        ],
        "findings": [{"text": "Liver lesion", "certainty": "definite", "quote": "Multiple liver metastases are present"}],
        "reported_response": {},
    }
    v = scan_extract.validate(bad, REPORT, "2026-11-02")
    assert v["lesions"] == [] and v["findings"] == [] and v["study"]["comparator_date"] == ""
    reasons = " | ".join(r["reason"] for r in v["rejected"])
    assert "quote not found" in reasons and "99" in reasons and "date not found" in reasons


def test_quote_tolerates_pdf_line_noise():
    assert scan_extract.quote_supported("Lymphnode in right level III appears metastatic.", "Lymphnode in r ight level III\nappears  metastatic.")


def test_possible_finding_text_never_reads_as_certain():
    data = {"findings": [
        {"text": "Metastatic lymph node in right level III", "category": "nodal", "certainty": "possible", "quote": "Lymphnode in right level III appears metastatic."},
        {"text": "Node appears metastatic", "category": "nodal", "certainty": "possible", "quote": "Lymphnode in right level III appears metastatic."},
    ]}
    texts = [f["text"] for f in scan_extract.validate(data, REPORT, "2026-11-02")["findings"]]
    assert texts == ["Possible: metastatic lymph node in right level III", "Node appears metastatic"]


def _save(client, monkeypatch):
    doc = client.post("/api/documents", files={"file": ("pet.txt", REPORT.encode(), "text/plain")}).json()
    monkeypatch.setattr(llm, "chat_json", lambda s, i, **_: GOOD)
    proposal = client.post(f"/api/documents/{doc['id']}/extract-scan").json()
    body = {
        "modality": proposal["study"]["modality"], "date": proposal["study"]["date"],
        "comparator_modality": proposal["study"]["comparator_modality"], "comparator_date": proposal["study"]["comparator_date"],
        "lesions": proposal["lesions"], "findings": proposal["findings"],
        "reported_label": "Partial Response", "reported_sum_prior": 42, "reported_sum_now": 22, "reported_pct": 47.7,
        "reported_quote": "Percentage change: 47.7%. STATUS: Partial Response (PR).",
    }
    return doc, client.post(f"/api/documents/{doc['id']}/scan", json=body)


def test_save_scan_builds_series_and_comparison(client, monkeypatch):
    _, r = _save(client, monkeypatch)
    prog = r.json()
    tongue = next(s for s in prog["series"] if s["label"] == "Left tongue lesion")
    assert [(p["date"], p["size_mm"], p["kind"]) for p in tongue["points"]] == [("2026-07-22", 34.0, "prior"), ("2026-11-02", 18.0, "current")]
    scan = prog["scans"][0]
    assert scan["computed"]["pct_change"] == -47.6 and scan["computed"]["category"] == "partial_response"
    assert scan["reported"]["label"] == "Partial Response" and scan["discrepancy"] is None


def test_save_scan_rejects_tampered_quote(client, monkeypatch):
    doc, _ = _save(client, monkeypatch)
    r = client.post(f"/api/documents/{doc['id']}/scan", json={"lesions": [{"name": "x", "size_mm_now": 5, "quote": "completely made up sentence not present"}]})
    assert r.status_code == 422


def test_readiness_distinguishes_unknown_from_answered(client, monkeypatch):
    _save(client, monkeypatch)
    client.put("/api/case", json={"primary_site": "tongue", "diagnosis": "carcinoma of tongue", "stage": "Stage IV"})
    data = client.get("/api/readiness").json()
    reqs = {r["key"]: r for r in data["requirements"]}
    assert data["profile"] == "oral_cavity"
    assert reqs["stage"]["met"] and reqs["stage"]["source"] == "case"
    assert reqs["recent_imaging"]["met"] and reqs["imaging_trend"]["met"]
    assert reqs["hla"]["status"] == "unknown" and not reqs["hla"]["met"]
    vaccine = next(d for d in data["decisions"] if d["id"] == "vaccine_feasibility")
    assert vaccine["status"] == "blocked" and "HLA typing (class I, high resolution)" in vaccine["blocked_by"]

    assert client.put("/api/facts/hla", json={"status": "not_done"}).status_code == 200
    reqs = {r["key"]: r for r in client.get("/api/readiness").json()["requirements"]}
    assert reqs["hla"]["status"] == "not_done" and not reqs["hla"]["met"]  # documented as not done still blocks
    client.put("/api/facts/hla", json={"status": "present", "value": "A*02:01, B*07:02"})
    assert {r["key"]: r for r in client.get("/api/readiness").json()["requirements"]}["hla"]["met"]


def test_insights_flag_vascular_possible_and_residual_activity(client, monkeypatch):
    _save(client, monkeypatch)
    items = client.get("/api/readiness").json()["insights"]
    ids = [i["id"] for i in items]
    assert items[0]["severity"] == "attention" and ids[0].startswith("vascular")
    assert any(i.startswith("possible") for i in ids) and any(i.startswith("residual") for i in ids)
    assert all(i["detail"] for i in items)
    assert not any("stop" in i["detail"].lower() and "treatment" in i["detail"].lower() for i in items)


def test_fact_validation(client):
    assert client.put("/api/facts/nope", json={"status": "present", "value": "x"}).status_code == 404
    assert client.put("/api/facts/pdl1", json={"status": "present"}).status_code == 422
    assert client.put("/api/facts/pdl1", json={"status": "weird"}).status_code == 422


def test_chat_context_contains_computed_values(client, monkeypatch):
    _save(client, monkeypatch)
    seen = {}
    monkeypatch.setattr(llm, "chat", lambda s, i, **_: seen.setdefault("i", i) or "ok")
    client.post("/api/chat", json={"message": "How is the treatment working?"})
    assert "42.0 mm -> 22.0 mm" in seen["i"] and "Partial response (size)" in seen["i"]
    assert "vaccine" in seen["i"].lower()
