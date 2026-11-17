from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResearchSource(Base):
    __tablename__ = "cc_research_source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text, default="")
    as_of: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchEvidence(Base):
    __tablename__ = "cc_research_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_url: Mapped[str] = mapped_column(Text)
    study_id: Mapped[str] = mapped_column(String(100), default="")
    platform: Mapped[str] = mapped_column(String(200))
    disease: Mapped[str] = mapped_column(String(300))
    setting: Mapped[str] = mapped_column(String(30), default="unknown")
    prior_pd1: Mapped[str] = mapped_column(String(20), default="unknown")
    endpoint_result: Mapped[str] = mapped_column(Text)
    n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    followup: Mapped[str] = mapped_column(String(200), default="")
    evidence_level: Mapped[str] = mapped_column(String(30))
    limitations: Mapped[str] = mapped_column(Text, default="")
    as_of: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchProfile(Base):
    __tablename__ = "cc_research_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    disease: Mapped[str] = mapped_column(String(300), default="")
    setting: Mapped[str] = mapped_column(String(30), default="unknown")
    prior_pd1: Mapped[str] = mapped_column(String(20), default="unknown")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ResearchExperiment(Base):
    __tablename__ = "cc_research_experiment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_run_id: Mapped[int] = mapped_column(Integer, index=True)
    hypothesis: Mapped[str] = mapped_column(Text)
    input_hash: Mapped[str] = mapped_column(String(64))
    comparison_hash: Mapped[str] = mapped_column(String(64), default="")
    pipeline_version: Mapped[str] = mapped_column(String(80), default="")
    result_hash: Mapped[str] = mapped_column(String(64))
    predictor: Mapped[str] = mapped_column(String(120))
    dataset: Mapped[str] = mapped_column(String(12))
    candidate_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    selected: Mapped[list] = mapped_column(JSON, default=list)
    caveats: Mapped[list] = mapped_column(JSON, default=list)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
