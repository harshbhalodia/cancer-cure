"""Upload handling: store the file, extract text per page, chunk it, and index it for search."""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, DocumentChunk, Event

CHUNK_CHARS = 1100
TEXT_SUFFIXES = {".txt", ".md", ".csv"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}

_TYPE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("imaging", re.compile(r"\b(PET[- ]?CT|FDG|MRI|CT scan|CT of|ultrasound|sonograph\w+|radiolog\w+|impression|SUV|Doppler|echocardio\w*)\b", re.I)),
    ("genomics", re.compile(r"\b(NGS|mutation|variant|tumou?r mutational|MSI|PD-?L1|Guardant|Caris|VAF|HLA)\b", re.I)),
    ("pathology", re.compile(r"\b(histopatholog\w+|HPE|biops\w+|pathology|cytolog\w+|FNAC|smear|margin|differentiated|carcinoma|squamous|malignan\w+)\b", re.I)),
    ("lab", re.compile(r"\b(hemoglobin|haemoglobin|WBC|platelet|creatinine|CA ?19-9|CEA|reference range|laborator\w+|lab report|CBC|blood count|LFT)\b", re.I)),
    ("prescription", re.compile(r"\b(Rx|prescri\w+|tablet|capsule|dose|dosage)\b", re.I)),
    ("advice", re.compile(r"\b(OPD|advised|advice|referral|follow[- ]?up|review after|consultation|discharge)\b", re.I)),
)
_DATE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.]((?:20)?\d{2})\b|\b(20\d{2})-(\d{2})-(\d{2})\b")


def _year(y: str) -> str:
    return y if len(y) == 4 else f"20{y}"


def guess_type(text_: str, filename: str = "") -> str:
    """Most distinctive vocabulary wins (a note that merely mentions a PET-CT is still an advice note).
    The file name counts triple: people name scans and reports sensibly."""
    sample = text_[:6000]
    stem = Path(filename).stem.replace("_", " ")
    scores = {name: len(pattern.findall(sample)) + 3 * len(pattern.findall(stem)) for name, pattern in _TYPE_RULES}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] else "other"


def guess_date(text_: str) -> str:
    """Best-effort ISO date; assumes day-first for ambiguous numeric dates."""
    m = _DATE.search(text_[:3000])
    if not m:
        return ""
    if m.group(4):
        return f"{m.group(4)}-{m.group(5)}-{m.group(6)}"
    day, month, year = int(m.group(1)), int(m.group(2)), _year(m.group(3))
    if month > 12:
        day, month = month, day
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{year}-{month:02d}-{day:02d}"


def split_chunks(page_text: str, size: int = CHUNK_CHARS) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", page_text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if current and len(current) + len(para) + 1 > size:
            chunks.append(current)
            current = ""
        while len(para) > size:
            chunks.append(para[:size])
            para = para[size:]
        current = f"{current}\n{para}".strip() if current else para
    if current:
        chunks.append(current)
    return chunks


def _extract_pages(data: bytes, suffix: str) -> list[str]:
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        return [(p.extract_text() or "").strip() for p in reader.pages]
    if suffix in TEXT_SUFFIXES:
        return [data.decode("utf-8", errors="replace")]
    return []


MIN_PAGE_CHARS = 20  # a PDF page with less text than this is treated as a scanned image


def pages_needing_ocr(suffix: str, pages: list[str]) -> list[int]:
    """1-based page numbers whose text can't be read directly."""
    if suffix in IMAGE_SUFFIXES:
        return [1]
    if suffix == ".pdf":
        return [i for i, p in enumerate(pages, start=1) if len(p.strip()) < MIN_PAGE_CHARS]
    return []


def index_page(db: Session, doc: Document, page_no: int, page_text: str) -> None:
    for chunk_text in split_chunks(page_text):
        chunk = DocumentChunk(document_id=doc.id, page=page_no, text=chunk_text)
        db.add(chunk)
        db.flush()
        db.execute(
            text("INSERT INTO cc_chunk_fts(text, chunk_id, document_id, page) VALUES (:t, :c, :d, :p)"),
            {"t": chunk_text, "c": chunk.id, "d": doc.id, "p": page_no},
        )


def refresh_metadata(db: Session, doc: Document) -> None:
    """Recompute type/date/size from everything indexed so far."""
    chunks = db.query(DocumentChunk).filter_by(document_id=doc.id).order_by(DocumentChunk.page, DocumentChunk.id).all()
    full = "\n".join(c.text for c in chunks)
    doc.text_chars = len(full)
    if full.strip():
        doc.doc_type = guess_type(full, doc.filename)
        doc.doc_date = guess_date(full) or doc.doc_date


def save_upload(db: Session, filename: str, data: bytes) -> tuple[Document, bool]:
    """Returns (document, created). Re-uploading identical bytes returns the existing document."""
    sha = hashlib.sha256(data).hexdigest()
    existing = db.query(Document).filter_by(sha256=sha).first()
    if existing:
        return existing, False

    suffix = Path(filename).suffix.lower()
    stored_name = f"{sha}{suffix}"

    pages = _extract_pages(data, suffix)  # may raise on a corrupt file, before anything is stored
    (get_settings().uploads_dir / stored_name).write_bytes(data)
    full_text = "\n".join(pages)
    has_text = bool(full_text.strip())
    scanned = pages_needing_ocr(suffix, pages)
    doc = Document(
        filename=Path(filename).name,
        sha256=sha,
        stored_name=stored_name,
        doc_type=guess_type(full_text, filename) if has_text else "other",
        doc_date=guess_date(full_text) if has_text else "",
        page_count=len(pages) or (1 if suffix in IMAGE_SUFFIXES else 0),
        text_chars=len(full_text),
        status="needs_ocr" if scanned else ("indexed" if has_text else "needs_ocr"),
    )
    db.add(doc)
    db.flush()

    for page_no, page_text in enumerate(pages, start=1):
        index_page(db, doc, page_no, page_text)

    note = f" {len(scanned) or 1} scanned page(s) will be read by the AI." if doc.status == "needs_ocr" else ""
    db.add(
        Event(
            kind="document",
            title=f"Uploaded {doc.filename}",
            detail=f"Type: {doc.doc_type}. Date: {doc.doc_date or 'unknown'}.{note}",
            ref_type="document",
            ref_id=doc.id,
        )
    )
    db.commit()
    return doc, True


def delete_document(db: Session, doc: Document) -> None:
    db.execute(text("DELETE FROM cc_chunk_fts WHERE document_id = :d"), {"d": doc.id})
    path = get_settings().uploads_dir / doc.stored_name
    db.add(Event(kind="document", title=f"Removed {doc.filename}", ref_type="document", ref_id=doc.id))
    db.delete(doc)
    db.commit()
    path.unlink(missing_ok=True)
