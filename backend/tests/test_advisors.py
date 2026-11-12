import pytest

from app.database import SessionLocal
from app.services import advisors, casefile, jobs, llm, recommendations
from tests.test_casefile import apply, upload
from tests.test_record import REPORT

GOOD_PACK = """
id: test.my_pack
name: My pack
publisher: Me
version: "1.0.0"
kind: plan
summary: A test pack.
inputs: [case_now, recommendations]
scenarios:
  - id: one
    description: What is open?
output:
  sections:
    - {id: a, name: Where things stand}
    - {id: b, name: Open advice}
disclaimer: Test disclaimer.
"""


def fresh(monkeypatch=None):
    return advisors.load_packs()


def test_bundled_packs_load_and_are_valid():
    packs = advisors.load_packs()
    assert {"carecompanion.next_steps", "carecompanion.visit_prep", "carecompanion.second_opinion"} <= set(packs)
    for p in packs.values():
        assert p.inputs and p.scenarios and p.sections and p.disclaimer and all(i in advisors.SCOPES for i in p.inputs)
    assert advisors.load_problems() == []


@pytest.mark.parametrize("raw,match", [
    ({"id": "x", "name": "n", "inputs": ["case_now"]}, "id must be"),
    ({"id": "good.id", "name": "", "inputs": ["case_now"]}, "needs a name"),
    ({"id": "good.id", "name": "n", "inputs": []}, "inputs must be"),
    ({"id": "good.id", "name": "n", "inputs": ["bank_accounts"]}, "Unknown: bank_accounts"),
    ({"id": "good.id", "name": "n", "inputs": ["case_now"], "kind": "magic"}, "kind must be"),
    ({"id": "good.id", "name": "n", "inputs": ["case_now"], "scenarios": [{"id": "a"}]}, "id and a description"),
    ({"id": "good.id", "name": "n", "inputs": ["case_now"], "scenarios": [{"id": str(i), "description": "d"} for i in range(9)]}, "at most"),
])
def test_pack_validation_rejects_bad_manifests(raw, match):
    with pytest.raises(advisors.PackError, match=match):
        advisors.validate_pack(raw)


def test_your_own_pack_is_loaded_overrides_and_bad_ones_are_reported(client):
    from app.config import get_settings

    folder = get_settings().data_dir / "advisors"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "mine.yaml").write_text(GOOD_PACK, encoding="utf-8")
    (folder / "override.yaml").write_text(GOOD_PACK.replace("test.my_pack", "carecompanion.next_steps").replace('"1.0.0"', '"9.0.0"').replace("My pack", "Mine wins"), encoding="utf-8")
    (folder / "old.yaml").write_text(GOOD_PACK.replace("test.my_pack", "carecompanion.visit_prep").replace('"1.0.0"', '"0.0.1"'), encoding="utf-8")
    (folder / "broken.yaml").write_text("id: x\nname: [", encoding="utf-8")
    try:
        packs = advisors.load_packs()
        assert packs["test.my_pack"].source == "yours"
        assert packs["carecompanion.next_steps"].name == "Mine wins"  # a higher version of the same id replaces the bundled one
        assert packs["carecompanion.visit_prep"].source == "bundled"  # a lower version does not
        assert [p["file"] for p in advisors.load_problems()] == ["broken.yaml"]
    finally:
        for f in folder.glob("*.yaml"):
            f.unlink()


def test_unknown_scope_refuses_the_run_and_only_declared_scopes_are_read(client):
    with SessionLocal() as db:
        with pytest.raises(advisors.PackError):
            advisors.gather(db, ["case_now", "bank"])
        facts = advisors.gather(db, ["case_now"])
    assert list(facts) == ["today", "case_now"]  # nothing else is gathered


def test_validator_blocks_advice_invented_figures_and_invented_references():
    facts = "Radiotherapy advised on 2025-01-12 [R4]. PET-CT on 2026-11-02 showed 18 mm."
    ok, v = advisors.validate_output("Radiotherapy was advised on 2025-01-12 [R4]. The lesion measured 18 mm on 2026-11-02.", facts, {4})
    assert v == [] and "[R4]" in ok
    _, v = advisors.validate_output("The lesion measured 25 mm.", facts, {4})
    assert any(x.startswith("invented-figure") and "25" in x for x in v)
    cleaned, v = advisors.validate_output("Advised earlier [R4] and also [R99].", facts, {4})
    assert "invented-reference" in v and "[R99]" not in cleaned and "[R4]" in cleaned
    _, v = advisors.validate_output("You should stop chemotherapy now.", facts, {4})
    assert "stop-treatment" in v
    _, v = advisors.validate_output("1. First step on 2025-01-12\n2. Second step", facts, {4})
    assert v == []  # list numbering is not a figure


def _setup_record(client):
    doc = upload(client, "advice.txt", "Advice note 12/01/2025. Adjuvant radiotherapy advised.")
    apply(client, doc, "2026-11-02", {"current_status": "Partial response on PET-CT"})
    with SessionLocal() as db:
        rec = recommendations.add(db, text="Adjuvant radiotherapy", category="radiotherapy", advisor="Dr A", rec_date="2025-01-12")
        db.commit()
        return rec.id


def test_pack_run_uses_specialists_then_lead_and_passes_the_checks(client, monkeypatch):
    rid = _setup_record(client)
    calls = []

    def chat(system, user_input, **_):
        calls.append(system[:20])
        if system.startswith("/no_think"):
            return f"Radiotherapy is still open [R{rid}]."
        return f"## Where things stand now\nPartial response on PET-CT.\n\n## What your advisors recommended\nAdjuvant radiotherapy advised on 2025-01-12 [R{rid}]."

    monkeypatch.setattr(llm, "chat", chat)
    pack = advisors.load_packs()["carecompanion.next_steps"]
    with SessionLocal() as db:
        run = advisors.run_pack(db, pack)
    assert len(calls) == len(pack.scenarios) + 1 and calls[-1].startswith("Write one concise")
    assert not run.used_fallback and run.flags == [] and len(run.notes) == len(pack.scenarios)
    assert f"[R{rid}]" in run.markdown and pack.disclaimer in run.markdown


def test_invented_figure_gets_one_repair_then_a_plain_fallback(client, monkeypatch):
    _setup_record(client)
    drafts = []

    def chat(system, user_input, **_):
        if system.startswith("/no_think"):
            return "Note."
        drafts.append(user_input)
        return "The lesion shrank by 73 percent."  # 73 appears nowhere in the facts

    monkeypatch.setattr(llm, "chat", chat)
    with SessionLocal() as db:
        run = advisors.run_pack(db, advisors.load_packs()["carecompanion.next_steps"])
    assert len(drafts) == 2 and "broke these rules" in drafts[1]
    assert run.used_fallback and any("fallback used" in f and "invented-figure" in f for f in run.flags)
    assert "73" not in run.markdown and "Partial response on PET-CT" in run.markdown  # assembled from the facts instead


def test_model_unavailable_still_produces_a_plan_from_the_facts(client, monkeypatch):
    _setup_record(client)

    def down(*_a, **_k):
        raise llm.LLMError("Can't reach LM Studio.")

    monkeypatch.setattr(llm, "chat", down)
    with SessionLocal() as db:
        run = advisors.run_pack(db, advisors.load_packs()["carecompanion.next_steps"])
    assert run.used_fallback and "Adjuvant radiotherapy" in run.markdown and "Can't reach LM Studio" in run.flags[0]


def test_plan_job_saves_the_plan_and_goes_stale_when_the_record_changes(client, monkeypatch):
    _setup_record(client)
    monkeypatch.setattr(llm, "chat", lambda s, i, **_: "Note." if s.startswith("/no_think") else "## Where things stand now\nPartial response on PET-CT.")
    assert client.post("/api/advisors/carecompanion.next_steps/run").json() == {"queued": True}
    assert client.post("/api/advisors/carecompanion.next_steps/run").status_code == 409  # already queued
    assert client.post("/api/advisors/nope/run").status_code == 404
    with SessionLocal() as db:
        jobs.run_pending(db)
    plan = client.get("/api/advisors/carecompanion.next_steps/plan").json()["plan"]
    assert plan["markdown"].startswith("## Where things stand now") and plan["stale"] is False and plan["used_fallback"] is False
    listing = client.get("/api/advisors").json()
    nxt = next(p for p in listing["packs"] if p["id"] == "carecompanion.next_steps")
    assert nxt["latest"]["id"] == plan["id"] and nxt["running"] is None and listing["problems"] == []
    client.post("/api/recommendations", json={"text": "Dental review", "category": "supportive", "advisor": "Dr B", "rec_date": "2025-01-05"})
    assert client.get("/api/advisors/carecompanion.next_steps/plan").json()["plan"]["stale"] is True
    assert client.get("/api/advisors/other/plan").json() == {"plan": None}


def test_plan_runs_before_slow_background_reading(client, monkeypatch):
    from tests.test_jobs import bulk

    order = []
    monkeypatch.setattr(llm, "chat_json", lambda s, i, **_: order.append("extract") or {})
    monkeypatch.setattr(llm, "chat", lambda s, i, **_: order.append("plan") or "Note.")
    bulk(client, [("a.txt", REPORT.encode())])
    with SessionLocal() as db:
        assert jobs.run_one(db)  # ingest queues analysis + recommendation reading
        jobs.enqueue_plan(db, "carecompanion.next_steps")
        jobs.run_one(db)
    assert order and order[0] == "plan"
