"""Tables are prefixed `cc_` so they can later move into Loonie's database without clashes."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Case(Base):
    """The living Case File. Phase 0 supports exactly one case (id=1)."""

    __tablename__ = "cc_case"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_name: Mapped[str] = mapped_column(String(200), default="")
    age: Mapped[str] = mapped_column(String(40), default="")
    sex: Mapped[str] = mapped_column(String(40), default="")
    diagnosis: Mapped[str] = mapped_column(Text, default="")
    primary_site: Mapped[str] = mapped_column(String(200), default="")
    histology: Mapped[str] = mapped_column(String(200), default="")
    stage: Mapped[str] = mapped_column(String(200), default="")
    biomarkers: Mapped[str] = mapped_column(Text, default="")
    hla_type: Mapped[str] = mapped_column(Text, default="")
    treatment_history: Mapped[str] = mapped_column(Text, default="")
    current_treatment: Mapped[str] = mapped_column(Text, default="")
    current_status: Mapped[str] = mapped_column(Text, default="")
    allergies: Mapped[str] = mapped_column(Text, default="")
    care_team: Mapped[str] = mapped_column(Text, default="")
    goals: Mapped[str] = mapped_column(Text, default="")
    caregiver_contact: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Document(Base):
    __tablename__ = "cc_document"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    stored_name: Mapped[str] = mapped_column(String(100))
    doc_type: Mapped[str] = mapped_column(String(40), default="other")
    doc_date: Mapped[str] = mapped_column(String(20), default="")
    source: Mapped[str] = mapped_column(String(200), default="")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    text_chars: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="indexed")  # indexed | needs_ocr
    text_source: Mapped[str] = mapped_column(String(20), default="pdf_text")  # pdf_text | vision_ocr (AI-read scan)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chunks: Mapped[list["DocumentChunk"]] = relationship(cascade="all, delete-orphan", back_populates="document")


class DocumentChunk(Base):
    __tablename__ = "cc_document_chunk"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("cc_document.id", ondelete="CASCADE"), index=True)
    page: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(Text)

    document: Mapped[Document] = relationship(back_populates="chunks")


class Event(Base):
    """Append-only timeline: every meaningful write leaves a trace here."""

    __tablename__ = "cc_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text, default="")
    ref_type: Mapped[str] = mapped_column(String(40), default="")
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ChatMessage(Base):
    __tablename__ = "cc_chat_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    flags: Mapped[list] = mapped_column(JSON, default=list)  # triage / safety notes shown with the message


class AgentRun(Base):
    """Audit trail of how each answer was produced."""

    __tablename__ = "cc_agent_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    prompt_version: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    triage: Mapped[list] = mapped_column(JSON, default=list)
    lint: Mapped[list] = mapped_column(JSON, default=list)
    retrieved: Mapped[list] = mapped_column(JSON, default=list)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")


class CaseEntry(Base):
    """One dated value for a case-file field. Entries are append-only: nothing is ever overwritten.
    The case file's current value for a field is derived from its entries (see services/casefile.py)."""

    __tablename__ = "cc_case_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    field: Mapped[str] = mapped_column(String(40), index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    as_of: Mapped[str] = mapped_column(String(20), default="")  # ISO date the value was true (report date); "" = unknown
    source: Mapped[str] = mapped_column(String(20), default="document")  # document | you
    document_id: Mapped[int | None] = mapped_column(ForeignKey("cc_document.id", ondelete="SET NULL"), nullable=True)
    quote: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClinicalEvent(Base):
    """A dated thing that happened (biopsy, surgery, radiotherapy, scan…), with the line it came from."""

    __tablename__ = "cc_clinical_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_date: Mapped[str] = mapped_column(String(20), default="", index=True)
    category: Mapped[str] = mapped_column(String(30), default="other")
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="document")  # document | you
    document_id: Mapped[int | None] = mapped_column(ForeignKey("cc_document.id", ondelete="SET NULL"), nullable=True)
    quote: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CaseSummary(Base):
    """AI-written narrative of the whole history. Marked stale whenever the history changes."""

    __tablename__ = "cc_case_summary"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, default="")
    fingerprint: Mapped[str] = mapped_column(String(80), default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Recommendation(Base):
    """Something a clinician or report advised/planned for the patient, with the line it came from.
    Advice is quoted and attributed, never generated; status is yours to set."""

    __tablename__ = "cc_recommendation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30), default="other")
    advisor: Mapped[str] = mapped_column(String(200), default="")
    rec_date: Mapped[str] = mapped_column(String(20), default="")  # when it was advised
    target_date: Mapped[str] = mapped_column(String(20), default="")  # when it should happen, if stated
    timing: Mapped[str] = mapped_column(String(120), default="")  # wording such as "after 3 weeks"
    certainty: Mapped[str] = mapped_column(String(20), default="advised")  # advised | planned | suggested | considered
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open | done | dismissed
    note: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="document")  # document | you
    document_id: Mapped[int | None] = mapped_column(ForeignKey("cc_document.id", ondelete="SET NULL"), nullable=True)
    quote: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Plan(Base):
    """A generated advisor-pack output (e.g. the next-steps plan). Marked stale when its inputs change."""

    __tablename__ = "cc_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pack_id: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    markdown: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[list] = mapped_column(JSON, default=list)  # the specialists' notes
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    flags: Mapped[list] = mapped_column(JSON, default=list)  # what the validator changed or why a fallback was used
    fingerprint: Mapped[str] = mapped_column(String(80), default="")
    used_fallback: Mapped[bool] = mapped_column(default=False)
    model: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Habit(Base):
    """One thing to do in daily life: a medicine, meal habit, routine, mind practice, movement or support.
    Medicines found in documents arrive as `suggested` (quoted) and only count once you confirm them."""

    __tablename__ = "cc_habit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(20), index=True)  # medication | diet | routine | mind | movement | support
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text, default="")
    when: Mapped[str] = mapped_column(String(20), default="anytime")  # morning | midday | evening | bedtime | anytime
    dose: Mapped[str] = mapped_column(String(300), default="")  # medicines: dose and frequency exactly as written
    prescriber: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(20), default="you")  # you | starter | document
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # suggested | active | paused | dropped
    document_id: Mapped[int | None] = mapped_column(ForeignKey("cc_document.id", ondelete="SET NULL"), nullable=True)
    quote: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HabitLog(Base):
    """A row means the habit was done on that day."""

    __tablename__ = "cc_habit_log"
    __table_args__ = (UniqueConstraint("habit_id", "day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("cc_habit.id", ondelete="CASCADE"), index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)


class CheckIn(Base):
    """How the day went, one row per day. Every number is optional: a blank is unknown, never zero."""

    __tablename__ = "cc_checkin"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), unique=True)
    energy: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1 (very low) - 5 (very good)
    mood: Mapped[int | None] = mapped_column(Integer, nullable=True)
    appetite: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pain: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0 (none) - 10 (worst)
    sleep_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    symptoms: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    intention: Mapped[str] = mapped_column(Text, default="")
    gratitude: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Setting(Base):
    __tablename__ = "cc_setting"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Fact(Base):
    """One structured clinical fact (e.g. PD-L1, HLA type). Status says what we actually know:
    present = has a value, negative = tested and negative, not_done = documented as not done.
    A missing row means unknown — absence of data is never read as a negative result."""

    __tablename__ = "cc_fact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    status: Mapped[str] = mapped_column(String(20))  # present | negative | not_done
    value: Mapped[str] = mapped_column(Text, default="")
    fact_date: Mapped[str] = mapped_column(String(20), default="")
    document_id: Mapped[int | None] = mapped_column(ForeignKey("cc_document.id", ondelete="SET NULL"), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Scan(Base):
    """One imaging study read from a report, with the response the report itself states."""

    __tablename__ = "cc_scan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("cc_document.id", ondelete="CASCADE"), unique=True)
    modality: Mapped[str] = mapped_column(String(40), default="")
    scan_date: Mapped[str] = mapped_column(String(20), default="")
    comparator_date: Mapped[str] = mapped_column(String(20), default="")
    comparator_modality: Mapped[str] = mapped_column(String(40), default="")
    reported_label: Mapped[str] = mapped_column(String(100), default="")
    reported_criteria: Mapped[str] = mapped_column(String(100), default="")
    reported_sum_prior: Mapped[float | None] = mapped_column(Float, nullable=True)
    reported_sum_now: Mapped[float | None] = mapped_column(Float, nullable=True)
    reported_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    reported_quote: Mapped[str] = mapped_column(Text, default="")

    measurements: Mapped[list["Measurement"]] = relationship(cascade="all, delete-orphan", back_populates="scan")
    findings: Mapped[list["Finding"]] = relationship(cascade="all, delete-orphan", back_populates="scan")


class Measurement(Base):
    """A lesion size at a date. `current` points come from the scan itself; `prior` points are the
    comparison values the report quotes for the earlier study (marked so they are never mistaken
    for a measurement we read from that earlier study's own report)."""

    __tablename__ = "cc_measurement"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("cc_scan.id", ondelete="CASCADE"), index=True)
    lesion: Mapped[str] = mapped_column(String(120))  # normalised key
    label: Mapped[str] = mapped_column(String(160))
    site: Mapped[str] = mapped_column(String(160), default="")
    is_target: Mapped[bool] = mapped_column(default=True)
    basis: Mapped[str] = mapped_column(String(30), default="unknown")
    point_date: Mapped[str] = mapped_column(String(20), default="")
    kind: Mapped[str] = mapped_column(String(10), default="current")  # current | prior
    size_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    suv_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote: Mapped[str] = mapped_column(Text, default="")

    scan: Mapped[Scan] = relationship(back_populates="measurements")


class Finding(Base):
    __tablename__ = "cc_finding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("cc_scan.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30), default="other")  # primary | nodal | distant | vascular | other
    certainty: Mapped[str] = mapped_column(String(20), default="definite")  # definite | possible | absent
    quote: Mapped[str] = mapped_column(Text, default="")

    scan: Mapped[Scan] = relationship(back_populates="findings")


class Job(Base):
    """Background work queue (persisted, so queued work survives a restart).

    kind `ingest`: read a staged/dropped file into the library.
    kind `analyze`: have the local model prepare scan and case-file proposals for a document.
    Proposals are never applied automatically; they wait in the review inbox (review_status=pending)."""

    __tablename__ = "cc_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued | running | done | failed
    document_id: Mapped[int | None] = mapped_column(ForeignKey("cc_document.id", ondelete="SET NULL"), nullable=True)
    filename: Mapped[str] = mapped_column(String(300), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    review_status: Mapped[str] = mapped_column(String(20), default="none")  # none | pending | reviewed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
