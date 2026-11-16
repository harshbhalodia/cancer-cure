import hashlib

import pytest

from app.database import SessionLocal
from app.models import HlaAllele, SomaticVariant
from app.services import safety, vaccine
from app.vaccine import dossier, evals, ingest, peptides, pipeline, predictor, synth
from app.vaccine.pipeline import Blocked, Params


class Stub:
    """A deterministic stand-in for the binding predictor, used only to test the plumbing."""

    name = "stub-predictor 0"

    def supported(self, allele: str) -> bool:
        return not allele.startswith("HLA-Z")

    def predict(self, peps, alleles):
        out = {}
        for p in set(peps):
            best = None
            for a in sorted(alleles):
                h = int(hashlib.sha256(f"{a}|{p}".encode()).hexdigest()[:8], 16)
                rec = {"allele": a, "affinity_nM": 15 + h % 4000, "presentation_score": round((h % 1000) / 1000, 3), "presentation_pct": round((h % 400) / 100, 3)}
                if best is None or rec["presentation_pct"] < best["presentation_pct"]:
                    best = rec
            out[p] = best
        return out


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(vaccine, "predictor_factory", lambda: Stub())
    monkeypatch.setattr(vaccine, "predictor_available", lambda: True)
    return Stub()


# ---------------------------------------------------------------- reading input
def test_protein_changes_and_hla_are_read_strictly():
    assert ingest.parse_protein_change("p.G12D") == ("G", 12, "D")
    assert ingest.parse_protein_change("p.Gly12Asp") == ("G", 12, "D")
    assert all(ingest.parse_protein_change(x) is None for x in ("G12fs", "E746_A750del", "R213*", "c.35G>A", "G12"))
    alleles, problems = ingest.parse_hla("A*02:01, hla-b*07:02; C0702 nonsense")
    assert alleles == ["HLA-A*02:01", "HLA-B*07:02"] and len(problems) == 2


def test_table_and_vcf_inputs_report_what_they_cannot_read():
    rows, problems = ingest.parse_variants("gene\tprotein_change\tvaf\ttpm\nKRAS\tp.G12D\t35%\t12.5\nTP53\t\t0.4\t3\n")
    assert rows[0]["gene"] == "KRAS" and rows[0]["vaf"] == 0.35 and rows[0]["tpm"] == 12.5 and len(problems) == 1
    vcf = ("##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
           "12\t25398284\t.\tC\tT\t.\tPASS\tDP=120;AF=0.31;ANN=T|missense_variant|MODERATE|KRAS|ENSG1|transcript|ENST1|protein_coding|2/6|c.35G>A|p.Gly12Asp|\n"
           "1\t100\t.\tA\tG\t.\tPASS\tDP=50\n")
    rows, problems = ingest.parse_variants(vcf)
    assert rows[0]["protein_change"] == "Gly12Asp" and rows[0]["depth"] == 120 and rows[0]["vaf"] == 0.31
    assert len(rows) == 1 and "no protein-level annotation" in problems[0]


def test_peptides_always_span_the_mutation_and_a_wrong_reference_is_refused():
    seq = "MTEYKLVVVGAGGVGKSALTIQLIQNHFVDEYDPTIEDSYRKQVVIDGETCLLDILDTAGQEEYSAMRDQYMRTGEGFLCVFAINNTKSFEDIHHYREQIKRVKDSEDVPMVLVGNKCDLPSRTVDTKQAQDLARSYGIPFIETSAKTRQGVDDAFYTLVREIRKH"
    pairs = peptides.peptides_for(seq, 1, 12, "G", "D")
    assert pairs and all(p["mut"][p["offset"]] == "D" and p["wt"][p["offset"]] == "G" for p in pairs)
    assert {p["length"] for p in pairs} == {8, 9, 10, 11}
    assert any(p["mut"] == "VVVGADGVGK" for p in pairs)  # the published KRAS G12D 10-mer is among them
    with pytest.raises(ValueError, match="reference has G"):
        peptides.peptides_for(seq, 1, 12, "A", "D")
    assert all(p["offset"] < p["length"] for p in peptides.peptides_for(seq, 1, 2, "T", "A"))  # near the start of the protein


# ---------------------------------------------------------------- the pipeline and its evals
def test_every_eval_passes_with_a_deterministic_predictor(stub):
    report = evals.run_all(stub, controls=False)
    failed = [c for c in report["checks"] if not c["passed"]]
    assert not failed, failed
    assert report["total"] == 10 and "do not show" in report["note"]


def test_a_tampered_run_cannot_be_replayed_to_the_same_hash(stub):
    rows, alleles, _ = evals._rows()
    run = pipeline.execute(rows, alleles, Params(), stub, dataset="synthetic")
    assert pipeline.replay(run)["result_hash"] == run["result_hash"]
    key = next(iter(run["predictions"]))
    run["predictions"][key] = {**run["predictions"][key], "presentation_pct": 0.0, "affinity_nM": 1.0}
    assert pipeline.replay(run)["result_hash"] != run["result_hash"]


def test_candidates_carry_their_reasons_and_caveats(stub):
    rows, alleles, _ = evals._rows()
    for r in rows:
        if r["gene"] == "SYN001":
            r["tpm"] = None  # unknown expression
    run = pipeline.execute(rows, alleles, Params(), stub, dataset="synthetic")
    c = next(c for c in run["candidates"] if c["gene"] == "SYN001")
    assert "expression unknown" in c["flags"] and c["tier"] in ("B", "C") and set(c["components"]) == {"presentation", "affinity", "differential", "vaf", "expression"}
    assert all(r["reason"] for r in run["rejected"]) and {r["stage"] for r in run["rejected"]} >= {"variants", "quality", "germline", "expression", "reference"}


def test_unsupported_alleles_are_reported_not_silently_used(stub):
    rows, alleles, _ = evals._rows()
    run = pipeline.execute(rows, alleles + ["HLA-Z*01:01"], Params(), stub, dataset="synthetic")
    assert run["alleles_unsupported"] == ["HLA-Z*01:01"] and any("does not support" in w for w in run["warnings"])
    with pytest.raises(Blocked):
        pipeline.execute(rows, ["HLA-Z*01:01"], Params(), stub)


# ---------------------------------------------------------------- the app around it
def test_synthetic_and_patient_data_never_mix(client, stub):
    with SessionLocal() as db:
        vaccine.load_synthetic(db)
        assert db.query(SomaticVariant).filter_by(dataset="patient").count() == 0 and db.query(SomaticVariant).filter_by(dataset="synthetic").count() == 15
        with pytest.raises(Blocked, match="No tumour mutations"):
            vaccine.run(db, "patient")
        row = vaccine.run(db, "synthetic")
        text = vaccine.dossier_text(db, row.id)
        assert "SYNTHETIC DATA" in text and "not a vaccine" in text and "investigational" in text
        assert vaccine.verify(db, row.id)["ok"]
        assert vaccine.workbench(db)["latest"]["patient"] is None


def test_fasttrack_drafts_come_from_records_and_pass_safety(client):
    v = client.get("/api/vaccine/fasttrack").json()
    assert [d["id"] for d in v["drafts"]] == ["trial", "blocks", "oncologist"] and v["steps"] and v["cautions"]
    assert [t["id"] for t in v["today"]] == ["oncologist", "blocks", "trial"] and isinstance(v["encouraging"], list)
    trial = v["drafts"][0]["text"]
    assert "not on file" in trial  # nothing is invented when sequencing/HLA are missing
    for d in v["drafts"]:
        assert not [i for i in safety.lint(d["text"]) if "efficacy" in str(i)]


def test_options_are_discussion_points_that_pass_safety_and_read_the_records(client):
    o = client.get("/api/vaccine/options").json()
    assert len(o["options"]) == 10 and o["first"] and "not derived from the synthetic cohort" in o["note"]
    for opt in o["options"]:
        assert opt["evidence"] and opt["ask"]
        assert not safety.lint(" ".join([opt["title"], opt["what"], *opt["ask"]])), opt["id"]
    assert any("not on file" in line for opt in o["options"] for line in opt["records"])


def test_cohort_scenarios_are_reproducible_and_summaries_are_sane():
    from app.vaccine import cohort

    pool = cohort.make_pool(n=60)
    alleles = ["HLA-A*02:01", "HLA-A*24:02", "HLA-B*07:02", "HLA-B*44:02", "HLA-C*07:02", "HLA-C*05:01"]
    a = cohort.make_scenario(3, 1, pool, cohort.DEFAULT_PROFILE, alleles)
    b = cohort.make_scenario(3, 1, pool, cohort.DEFAULT_PROFILE, alleles)
    assert a == b and a["hla"] and 5 <= a["burden"] <= 60
    assert all(r["tpm"] is None and r["normal_vaf"] is None for r in a["views"]["panel_only"])
    assert all(r["tpm"] is None for r in a["views"]["no_rna"]) and all(r["normal_vaf"] is None for r in a["views"]["no_normal"])
    row = {v: {"in": 10, "cands": 5, "selected": 4, "strong": 2, "strong_v": 3, "tierA": 1, "top": 70.0, "top5": 60.0, "germline_selected": 0, "genes": 3} for v in cohort.VIEWS}
    s = cohort.summarize([{"i": i, "burden": 10 + i, "purity": .5, "hla": ["HLA-A*02:01"] * 6, "views": row} for i in range(40)])
    assert s["scenarios"] == 40 and s["views"]["full"]["p_strong_ge"]["3"] == 1.0 and s["views"]["full"]["p_strong_ge"]["5"] == 0.0


def test_audit_scores_model_flags_against_planted_truth_and_memo_is_checked():
    from app.vaccine import audit

    cases = [{"i": 1, "n_selected": 5, "truth": [1, 3], "flags": [1], "rule": [1, 3], "concerns": [], "overall": "needs_review", "error": "", "secs": 10.0},
             {"i": 2, "n_selected": 5, "truth": [], "flags": [2], "rule": [], "concerns": [], "overall": "needs_review", "error": "", "secs": 12.0},
             {"i": 3, "n_selected": 5, "truth": [4], "flags": [], "rule": [], "concerns": [], "overall": "", "error": "TimeoutError", "secs": 0.0}]
    s = audit.summarize_audit(cases)
    assert s["answered"] == 2 and s["failed"] == 1
    assert (s["model"]["true_flags"], s["model"]["false_flags"], s["model"]["missed"]) == (1, 1, 1)
    assert s["rule"]["recall"] == 1.0 and s["model_better_than_rule"] is False and "no better" in s["verdict"]
    facts = "Scenarios simulated: 10000\n- full: median 18"
    good = "Across 10000 simulated tumours the median was 18. This is a software test on invented tumours, not advice about treatment."
    assert audit.check_memo(good, facts) == []
    assert any("999" in p for p in audit.check_memo(good + " About 999 are affected.", facts))
    assert audit.check_memo("A vaccine will cure this tumour.", facts)


def test_cohort_lookup_picks_the_best_allele():
    from app.vaccine import cohort

    table = {"HLA-A*02:01": {"PEPTIDEK": (50.0, 0.9, 0.2)}, "HLA-B*07:02": {"PEPTIDEK": (900.0, 0.1, 3.0)}}
    r = cohort.Lookup(table, "t").predict(["PEPTIDEK"], ["HLA-B*07:02", "HLA-A*02:01"])
    assert r["PEPTIDEK"]["allele"] == "HLA-A*02:01" and r["PEPTIDEK"]["presentation_pct"] == 0.2


def test_cohort_api_reports_nothing_before_a_run(client):
    v = client.get("/api/vaccine/cohort").json()
    assert v["status"]["state"] == "none" and v["summary"] is None and v["situation"]


def test_api_flow_paste_run_verify_and_download(client, stub):
    r = client.post("/api/vaccine/variants", json={"text": "gene\tprotein_change\tvaf\tnormal_vaf\ttpm\twt_window\nSYNX\tG5D\t0.3\t0\t20\tMAAAGKLMNPQRSTVWYACDEFGHIKLMN\n"}).json()
    assert r["read"] == 1 and r["added"] == 1
    assert client.post("/api/vaccine/hla", json={"text": "HLA-A*02:01 HLA-B*07:02 HLA-C*07:02"}).json()["alleles"] == ["HLA-A*02:01", "HLA-B*07:02", "HLA-C*07:02"]
    from app.services import jobs
    assert client.post("/api/vaccine/run", json={"dataset": "patient"}).json() == {"queued": True}
    assert client.post("/api/vaccine/run", json={"dataset": "patient"}).status_code == 409  # already queued
    with SessionLocal() as db:
        jobs.run_pending(db)
    wb = client.get("/api/vaccine").json()
    run = wb["latest"]["patient"]
    assert run and run["stages"][0]["in"] == 1 and wb["patient"]["variants"] == 1 and wb["runs"][0]["dataset"] == "patient"
    assert client.post(f"/api/vaccine/runs/{run['id']}/verify").json()["ok"] is True
    md = client.get(f"/api/vaccine/runs/{run['id']}/dossier")
    assert md.status_code == 200 and "Candidate antigen shortlist" in md.text and "attachment" in md.headers["content-disposition"]
    assert "predictions" not in client.get(f"/api/vaccine/runs/{run['id']}/dossier?fmt=json").text
    assert client.delete("/api/vaccine/data?dataset=patient").status_code == 204
    assert client.get("/api/vaccine").json()["patient"]["variants"] == 0


def test_a_run_with_missing_inputs_fails_with_a_clear_message(client, stub):
    from app.models import Job
    from app.services import jobs
    client.post("/api/vaccine/run", json={"dataset": "patient"})
    with SessionLocal() as db:
        jobs.run_pending(db)
        j = db.query(Job).filter_by(kind="vaccine").one()
        assert j.status == "failed" and "No tumour mutations" in j.error


def test_reference_lookup_is_opt_in_and_sends_only_gene_symbols(client, monkeypatch):
    sent = []
    monkeypatch.setattr(peptides, "fetch_reference", lambda gene: (sent.append(gene) or ("M" + "A" * 50, "uniprot:TEST")))
    with SessionLocal() as db:
        vaccine.add_variants(db, "patient", [{"gene": "KRAS", "protein_change": "G12D"}, {"gene": "TP53", "protein_change": "R175H", "wt_window": "A" * 20}, {"gene": "NF1", "protein_change": "L5fs"}])
        assert vaccine.missing_references(db, "patient") == ["KRAS"]  # supplied window and non-substitutions need no lookup
        assert sent == []
        assert vaccine.fetch_references(db, "patient") == {"KRAS": "uniprot:TEST"} and sent == ["KRAS"]
        assert vaccine.missing_references(db, "patient") == []


def test_the_review_board_sees_only_computed_facts_and_the_safety_lint_blocks_efficacy_claims(client, stub):
    with SessionLocal() as db:
        assert "no candidate selection" in vaccine.board_facts(db)
        vaccine.load_synthetic(db)
        vaccine.run(db, "synthetic")
        facts = vaccine.board_facts(db)
        assert facts.startswith("Dataset: SYNTHETIC") and "Selected candidates" in facts and "Not handled by this pipeline" in facts
    assert "vaccine-efficacy-claim" in safety.lint("This vaccine is safe and effective for him.")
    assert "vaccine-efficacy-claim" in safety.lint("The candidate will shrink the tumour.")
    assert not safety.lint("These are predictions only; no peptide has been shown to work in the patient.")


def test_dossier_states_its_limits_and_never_claims_efficacy(stub):
    rows, alleles, _ = evals._rows()
    text = dossier.build(pipeline.execute(rows, alleles, Params(), stub, dataset="synthetic"), synthetic=True)
    assert "Limits of this analysis" in text and "Frameshifts" in text and not evals.CLAIMS.search(text)


@pytest.mark.skipif(not predictor.available(), reason="MHCflurry is not installed")
def test_the_real_predictor_recovers_published_epitopes_and_runs_the_whole_suite():
    report = evals.run_all(predictor.load_default())
    assert report["passed"] == report["total"], [c for c in report["checks"] if not c["passed"]]
    assert any(c["name"] == "predictor_recovers_published_epitopes" and c["passed"] for c in report["checks"])
