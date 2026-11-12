"""Reads scanned pages (image-only PDFs, photos of reports, handwritten notes) with the local vision model.

Each page is rendered, sent to the model for a faithful transcription, and indexed like any other text.
Pages are saved one at a time, so a long document can resume after an interruption. The text is flagged
as AI-read (Document.text_source = "vision_ocr") everywhere it is shown, because a transcription can
contain reading errors and must be checked against the original page.
"""
from __future__ import annotations

import base64
import io
import re
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageStat
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, DocumentChunk, Event
from app.services import documents, llm

LONG_EDGE_PX = 1800
BLANK_STDDEV = 4.0
BLANK_MARKER = "[blank page]"

OCR_PROMPT = (
    "/no_think\n"  # skip the model's long reasoning phase: this is transcription, not analysis
    "Transcribe ALL text in this scanned medical document page exactly as written, in reading order. "
    "Keep table rows on one line with ' | ' between columns. Keep the original language and script "
    "(English, Gujarati, Hindi) — do not translate. Copy every number, unit, date and name exactly. "
    "If a word or number is unclear write [?] after your best reading, or [illegible] if you cannot read it. "
    "Do not summarise, interpret, correct or add anything that is not on the page. "
    "Output only the transcription."
)


def _resize(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    longest = max(img.size)
    if longest > LONG_EDGE_PX:
        scale = LONG_EDGE_PX / longest
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    return img


def render_page(path: Path, page_no: int) -> Image.Image:
    """Render one 1-based page (or the image itself) to an RGB image."""
    if path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        try:
            page = pdf[page_no - 1]
            width, height = page.get_size()
            scale = min(3.0, LONG_EDGE_PX / max(width, height))
            return page.render(scale=scale).to_pil().convert("RGB")
        finally:
            pdf.close()
    return _resize(Image.open(path))


def is_blank(img: Image.Image) -> bool:
    return max(ImageStat.Stat(img.convert("L")).stddev) < BLANK_STDDEV


def to_jpeg_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def clean_transcript(text: str) -> str:
    """Collapse the runaway repetition a vision model sometimes produces on noisy pages."""
    text = re.sub(r"^```\w*\n?|```$", "", text.strip(), flags=re.M).strip()
    lines, out, run = text.splitlines(), [], 0
    for line in lines:
        run = run + 1 if out and line.strip() == out[-1].strip() else 0
        if run < 2:
            out.append(line)
    return "\n".join(out).strip()


def transcribe(img: Image.Image) -> str:
    """Read one page with the main model; if it returns nothing (it sometimes reasons endlessly on dense
    pages), try the fallback model before giving up."""
    b64 = to_jpeg_b64(img)
    try:
        return clean_transcript(llm.vision(OCR_PROMPT, b64))
    except llm.LLMError as exc:
        fallback = get_settings().ocr_fallback_model
        if not fallback or "no transcription" not in str(exc):
            raise
        return clean_transcript(llm.vision(OCR_PROMPT, b64, model=fallback))


def pages_to_read(db: Session, doc: Document, path: Path) -> list[int]:
    """Pages that still have no indexed text and are not readable directly from the PDF."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        candidates = [i for i, p in enumerate(reader.pages, start=1) if len((p.extract_text() or "").strip()) < documents.MIN_PAGE_CHARS]
    elif suffix in documents.IMAGE_SUFFIXES:
        candidates = [1]
    else:
        return []
    done = {c.page for c in db.query(DocumentChunk.page).filter_by(document_id=doc.id)}
    return [p for p in candidates if p not in done]


def read_document(db: Session, doc: Document, *, progress: Callable[[int, int], None], wait: Callable[[], None]) -> dict:
    path = get_settings().uploads_dir / doc.stored_name
    todo = pages_to_read(db, doc, path)
    total, done, blank = len(todo), 0, 0
    for page_no in todo:
        wait()  # let any interactive request go first
        img = render_page(path, page_no)
        if is_blank(img):
            documents.index_page(db, doc, page_no, BLANK_MARKER)
            blank += 1
        else:
            text = transcribe(img)
            documents.index_page(db, doc, page_no, text or BLANK_MARKER)
        db.commit()  # page saved: a retry resumes after it
        done += 1
        progress(done, total)

    doc.text_source = "vision_ocr"
    documents.refresh_metadata(db, doc)
    real = sum(len(c.text) for c in db.query(DocumentChunk).filter_by(document_id=doc.id) if c.text != BLANK_MARKER)
    doc.status = "indexed" if real >= documents.MIN_PAGE_CHARS else "unreadable"
    db.add(Event(kind="document", title=f"Read scanned pages of {doc.filename}",
                 detail=f"{done} page(s) transcribed by the local AI (check against the original). Type: {doc.doc_type}. Date: {doc.doc_date or 'unknown'}.",
                 ref_type="document", ref_id=doc.id))
    db.commit()
    return {"pages_read": done, "blank_pages": blank, "doc_type": doc.doc_type}
