from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_settings.data_dir.mkdir(parents=True, exist_ok=True)
_settings.uploads_dir.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{_settings.db_path}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def init_db() -> None:
    from app import models  # noqa: F401  (registers tables)

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        # Lightweight migration for databases created before a column existed.
        doc_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(cc_document)"))}
        if "text_source" not in doc_cols:
            conn.execute(text("ALTER TABLE cc_document ADD COLUMN text_source VARCHAR(20) NOT NULL DEFAULT 'pdf_text'"))
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
