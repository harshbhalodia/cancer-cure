from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

_STOPWORDS = {
    "the", "and", "for", "are", "was", "what", "with", "about", "this", "that", "have", "has", "from",
    "your", "you", "can", "does", "did", "how", "why", "when", "which", "tell", "please", "show", "any",
    "his", "her", "him", "she", "they", "them", "there", "been", "will", "would", "could", "should",
}


@dataclass(frozen=True)
class Passage:
    document_id: int
    filename: str
    doc_date: str
    page: int
    text: str
    ai_read: bool = False  # transcribed from a scan by the vision model


def _fts_query(question: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", question.lower()) if w not in _STOPWORDS]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words))


def search(db: Session, question: str, limit: int = 6) -> list[Passage]:
    query = _fts_query(question)
    if not query:
        return []
    rows = db.execute(
        text(
            "SELECT f.document_id, f.page, f.text, d.filename, d.doc_date, d.text_source "
            "FROM cc_chunk_fts f JOIN cc_document d ON d.id = f.document_id "
            "WHERE cc_chunk_fts MATCH :q ORDER BY bm25(cc_chunk_fts) LIMIT :n"
        ),
        {"q": query, "n": limit},
    ).all()
    return [Passage(r.document_id, r.filename, r.doc_date or "", int(r.page), r.text, r.text_source == "vision_ocr") for r in rows]


def latest_per_document(db: Session, limit: int = 3) -> list[Passage]:
    """Fallback when the question has no searchable words: the opening of the newest documents."""
    rows = db.execute(
        text(
            "SELECT c.document_id, c.page, c.text, d.filename, d.doc_date, d.text_source FROM cc_document_chunk c "
            "JOIN cc_document d ON d.id = c.document_id "
            "WHERE c.id IN (SELECT MIN(id) FROM cc_document_chunk GROUP BY document_id) "
            "ORDER BY d.created_at DESC LIMIT :n"
        ),
        {"n": limit},
    ).all()
    return [Passage(r.document_id, r.filename, r.doc_date or "", int(r.page), r.text, r.text_source == "vision_ocr") for r in rows]
