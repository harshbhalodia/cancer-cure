from __future__ import annotations

from collections.abc import Iterator
import threading

from sqlalchemy import create_engine, event, text, Engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import get_base_settings, get_settings


class Base(DeclarativeBase):
    pass


_settings = get_base_settings()
_settings.data_dir.mkdir(parents=True, exist_ok=True)
_settings.uploads_dir.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{_settings.db_path}", connect_args={"check_same_thread": False})
_engines: dict[str, Engine] = {str(_settings.db_path): engine}
_engine_lock = threading.RLock()


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def current_engine() -> Engine:
    settings = get_settings()
    key = str(settings.db_path)
    with _engine_lock:
        if key not in _engines:
            settings.uploads_dir.mkdir(parents=True, exist_ok=True)
            created = create_engine(f"sqlite:///{settings.db_path}", connect_args={"check_same_thread": False})
            event.listen(created, "connect", _sqlite_pragmas)
            init_db(created)
            _engines[key] = created
        return _engines[key]


def SessionLocal() -> Session:
    return Session(bind=current_engine(), autoflush=False, expire_on_commit=False)


def catalog_session() -> Session:
    return Session(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(bind: Engine | None = None) -> None:
    from app import models  # noqa: F401  (registers tables)
    from app import research_models  # noqa: F401

    bind = bind or engine
    Base.metadata.create_all(bind)
    with bind.begin() as conn:
        # Lightweight migration for databases created before a column existed.
        doc_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(cc_document)"))}
        if "text_source" not in doc_cols:
            conn.execute(text("ALTER TABLE cc_document ADD COLUMN text_source VARCHAR(20) NOT NULL DEFAULT 'pdf_text'"))
        rec_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(cc_recommendation)"))}
        for col in ("urgency", "verified"):
            if rec_cols and col not in rec_cols:
                conn.execute(text(f"ALTER TABLE cc_recommendation ADD COLUMN {col} VARCHAR(10) NOT NULL DEFAULT ''"))
        experiment_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(cc_research_experiment)"))}
        for col, size in (("comparison_hash", 64), ("pipeline_version", 80)):
            if col not in experiment_cols:
                conn.execute(text(f"ALTER TABLE cc_research_experiment ADD COLUMN {col} VARCHAR({size}) NOT NULL DEFAULT ''"))
        # Full-text index over document chunks; rows are kept in sync by services/documents.py.
        conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS cc_chunk_fts USING fts5("
                "text, chunk_id UNINDEXED, document_id UNINDEXED, page UNINDEXED)"
            )
        )


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
