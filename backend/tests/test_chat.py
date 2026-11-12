from app.services import llm
from tests.conftest import SAMPLE_REPORT


def upload(client):
    return client.post("/api/documents", files={"file": ("pet.txt", SAMPLE_REPORT.encode(), "text/plain")}).json()


def test_chat_uses_documents_and_checks_citations(client, monkeypatch):
    doc = upload(client)
    client.put("/api/case", json={"diagnosis": "Carcinoma of tongue"})
    seen = {}

    def fake_chat(system, user_input, **_):
        seen["input"] = user_input
        return f"The lesion is 18 mm [D{doc['id']} p1]. Another claim [D999 p3]."

    monkeypatch.setattr(llm, "chat", fake_chat)
    r = client.post("/api/chat", json={"message": "How big is the tongue lesion now?"}).json()

    assert "Carcinoma of tongue" in seen["input"]
    assert "18 x 18 mm" in seen["input"]
    assert f"[D{doc['id']} p1]" in r["content"]
    assert "D999" not in r["content"]
    assert [c["document_id"] for c in r["citations"]] == [doc["id"]]


def test_multi_tag_citations_are_validated_individually(client, monkeypatch):
    doc = upload(client)
    monkeypatch.setattr(llm, "chat", lambda s, i, **_: f"Lesion shrank [D{doc['id']} p1, D{doc['id']} p9, D77 p1].")
    r = client.post("/api/chat", json={"message": "tongue lesion size?"}).json()
    assert f"[D{doc['id']} p1]" in r["content"] and "p9" not in r["content"] and "D77" not in r["content"]


def test_history_is_replayed_without_duplicating_current_message(client, monkeypatch):
    inputs = []
    monkeypatch.setattr(llm, "chat", lambda s, i, **_: inputs.append(i) or "ok")
    client.post("/api/chat", json={"message": "first question"})
    client.post("/api/chat", json={"message": "second question"})
    second = inputs[1]
    assert "User: first question" in second
    assert second.count("second question") == 1
    assert len(client.get("/api/chat").json()) == 4


def test_emergency_skips_model(client, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("model must not be called")

    monkeypatch.setattr(llm, "chat", boom)
    r = client.post("/api/chat", json={"message": "He has severe chest pain"}).json()
    assert "emergency" in r["content"].lower()
    assert r["flags"][0]["level"] == "emergency"
    assert any(e["kind"] == "alert" for e in client.get("/api/timeline").json())


def test_unsafe_answer_is_retried_then_replaced(client, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "chat", lambda s, i, **_: calls.append(i) or "You should stop chemotherapy.")
    r = client.post("/api/chat", json={"message": "Should we continue?"}).json()
    assert len(calls) == 2
    assert "oncology team" in r["content"]
    assert r["flags"][0]["type"] == "safety"


def test_model_unavailable_is_reported_not_raised(client, monkeypatch):
    def down(*_a, **_k):
        raise llm.LLMError("Can't reach LM Studio.")

    monkeypatch.setattr(llm, "chat", down)
    r = client.post("/api/chat", json={"message": "Hello"})
    assert r.status_code == 200 and "Can't reach LM Studio" in r.json()["content"]


def test_extract_case_returns_proposal_without_saving(client, monkeypatch):
    doc = upload(client)
    monkeypatch.setattr(llm, "chat_json", lambda s, i, **_: {"diagnosis": "carcinoma of tongue", "stage": None, "junk": "x"})
    r = client.post(f"/api/documents/{doc['id']}/extract-case").json()["proposed"]
    assert r["diagnosis"] == "carcinoma of tongue" and r["stage"] == "" and "junk" not in r
    assert client.get("/api/case").json()["diagnosis"] == ""
