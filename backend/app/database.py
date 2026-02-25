"""
SQLAlchemy engine and session. Supports PostgreSQL and SQLite (for local testing without Docker).
Sync usage (BackgroundTasks-friendly); scope by user_id for all document/test access.
"""
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

logger = logging.getLogger(__name__)

_is_sqlite = "sqlite" in settings.database_url
_connect_args = {"check_same_thread": False} if _is_sqlite else {}
engine = create_engine(
    settings.database_url,
    pool_pre_ping=not _is_sqlite,
    connect_args=_connect_args,
    echo=False,  # Set True for SQL logging during development
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_sqlite_db():
    """When using SQLite: create tables, add missing columns (e.g. failure_reason), seed topic_list. Call once at app startup."""
    if not _is_sqlite:
        return
    # Import all models so they register with Base before create_all
    from app.models import user, document, generated_test, question, topic_list  # noqa: F401
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Ensure generated_tests.failure_reason exists (added after initial schema; avoids 500s if Alembic not run)
        from sqlalchemy import text
        try:
            rows = db.execute(text("PRAGMA table_info(generated_tests)")).fetchall()
            if rows and not any(r[1] == "failure_reason" for r in rows):
                db.execute(text("ALTER TABLE generated_tests ADD COLUMN failure_reason VARCHAR(512)"))
            if rows and not any(r[1] == "target_questions" for r in rows):
                db.execute(text("ALTER TABLE generated_tests ADD COLUMN target_questions INTEGER NOT NULL DEFAULT 15"))
            if rows and not any(r[1] == "questions_generated" for r in rows):
                db.execute(text("ALTER TABLE generated_tests ADD COLUMN questions_generated INTEGER NOT NULL DEFAULT 0"))
            if rows and not any(r[1] == "processed_candidates" for r in rows):
                db.execute(text("ALTER TABLE generated_tests ADD COLUMN processed_candidates INTEGER NOT NULL DEFAULT 0"))
            db.commit()
        except Exception as e:
            logger.warning("SQLite init: generated_tests column add failed: %s", e)
            db.rollback()
        try:
            doc_rows = db.execute(text("PRAGMA table_info(documents)")).fetchall()
            if doc_rows and not any(r[1] == "target_questions" for r in doc_rows):
                db.execute(text("ALTER TABLE documents ADD COLUMN target_questions INTEGER DEFAULT 15"))
            if doc_rows and not any(r[1] == "extraction_elapsed_seconds" for r in doc_rows):
                db.execute(text("ALTER TABLE documents ADD COLUMN extraction_elapsed_seconds INTEGER"))
            if doc_rows and not any(r[1] == "total_pages" for r in doc_rows):
                db.execute(text("ALTER TABLE documents ADD COLUMN total_pages INTEGER"))
            if doc_rows and not any(r[1] == "extracted_pages" for r in doc_rows):
                db.execute(text("ALTER TABLE documents ADD COLUMN extracted_pages INTEGER NOT NULL DEFAULT 0"))
            db.commit()
        except Exception as e:
            logger.warning("SQLite init: documents column add failed: %s", e)
            db.rollback()
        from app.models.topic_list import TopicList
        if db.query(TopicList).count() == 0:
            for slug, name, order in [
                ("polity", "Polity", 1),
                ("economy", "Economy", 2),
                ("history", "History", 3),
                ("geography", "Geography", 4),
                ("science", "Science", 5),
                ("environment", "Environment", 6),
            ]:
                db.add(TopicList(slug=slug, name=name, sort_order=order))
            db.commit()
    finally:
        db.close()


def get_db():
    """Dependency: yield a DB session, close after request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
