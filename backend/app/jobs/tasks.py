"""
Background job: run MCQ generation for a test.
Vision-based: PDF → page images (300 DPI) → batch ingest to Claude → generate MCQs → quality review → persist.
"""
import logging
import threading
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.generated_test import GeneratedTest
from app.models.document import Document
from app.models.question import Question
from app.models.topic_list import TopicList
from app.services.prompt_helpers import get_topic_slugs_for_prompt

logger = logging.getLogger(__name__)

MIN_QUESTIONS = 1
MAX_QUESTIONS = 30
# Max 3 concurrent generation jobs (vision pipeline is heavy)
_generation_semaphore = threading.BoundedSemaphore(3)


def _resolve_pdf_path(doc: Document) -> str | None:
    """Resolve document file_path to absolute path; return None if not found."""
    if not doc or not (doc.file_path or "").strip():
        return None
    path = Path(doc.file_path).resolve()
    if path.exists():
        return str(path)
    backend_dir = Path(__file__).resolve().parent.parent
    alt = (backend_dir / doc.file_path).resolve()
    if alt.exists():
        return str(alt)
    return None


def run_generation(test_id: uuid.UUID, doc_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """
    Background task: vision-based MCQ generation from PDF (page images → Claude → persist).
    Updates test status to generating → completed or failed. Runs in thread pool; does not block event loop.
    """
    logger.info("run_generation: start test_id=%s doc_id=%s user_id=%s", test_id, doc_id, user_id)
    sem_acquired = False
    db: Session = SessionLocal()
    try:
        test = db.query(GeneratedTest).filter(
            GeneratedTest.id == test_id,
            GeneratedTest.user_id == user_id,
        ).first()
        if not test:
            logger.warning("run_generation: test %s not found for user %s", test_id, user_id)
            return
        test.status = "generating"
        db.commit()
        logger.info("run_generation: status set to generating for test_id=%s", test_id)

        doc = db.query(Document).filter(
            Document.id == doc_id,
            Document.user_id == user_id,
        ).first()
        if not doc:
            _mark_failed(db, test, "Document not found")
            return
        if getattr(doc, "source_type", None) != "pdf":
            _mark_failed(db, test, "Only PDF documents are supported for generation")
            return
        pdf_path = _resolve_pdf_path(doc)
        if not pdf_path:
            _mark_failed(db, test, "PDF file not found on server")
            return

        _generation_semaphore.acquire()
        sem_acquired = True

        topic_slugs = get_topic_slugs_for_prompt(db)
        if not topic_slugs:
            topic_slugs = ["polity"]
        slug_to_topic_id = {r.slug: r.id for r in db.query(TopicList).filter(TopicList.slug.in_(topic_slugs)).all()}
        default_topic_id = slug_to_topic_id.get(topic_slugs[0]) if topic_slugs else None
        if not default_topic_id:
            topic_rows = db.query(TopicList).order_by(TopicList.sort_order).limit(1).all()
            default_topic_id = topic_rows[0].id if topic_rows else None
        if not default_topic_id:
            _mark_failed(db, test, "No topic_list rows")
            return

        meta = test.generation_metadata if isinstance(test.generation_metadata, dict) else {}
        try:
            n = meta.get("num_questions", MAX_QUESTIONS)
            num_requested = max(MIN_QUESTIONS, min(MAX_QUESTIONS, int(n) if n is not None else MAX_QUESTIONS))
        except (TypeError, ValueError):
            num_requested = MAX_QUESTIONS
        difficulty = (meta.get("difficulty") or "").strip().upper()
        if difficulty not in ("EASY", "MEDIUM", "HARD"):
            _mark_failed(db, test, "generation_metadata.difficulty required (EASY, MEDIUM, or HARD)")
            return

        logger.info("run_generation: calling generate_mcqs_vision for test_id=%s num_questions=%s difficulty=%s", test_id, num_requested, difficulty)
        from app.llm.vision_mcq import generate_mcqs_vision, _validate_mcqs
        mcqs, total_inp, total_out = generate_mcqs_vision(
            pdf_path, num_questions=num_requested, difficulty=difficulty, topic_slugs=topic_slugs,
        )

        if not mcqs:
            _mark_failed(db, test, "Vision pipeline returned no MCQs")
            return

        if not _validate_mcqs(mcqs):
            logger.warning("run_generation: validation failed (options/correct_answer), retrying once")
            mcqs, total_inp, total_out = generate_mcqs_vision(
                pdf_path, num_questions=num_requested, difficulty=difficulty, topic_slugs=topic_slugs,
            )
            if not mcqs or not _validate_mcqs(mcqs):
                _mark_failed(db, test, "MCQ validation failed after retry (options 4 or 5, labels A..D/E, correct_answer in labels)")
                return

        db.query(Question).filter(Question.generated_test_id == test_id).delete()
        for i, m in enumerate(mcqs):
            slug = (m.get("topic_tag") or "polity").strip().lower()
            topic_id = slug_to_topic_id.get(slug) or default_topic_id
            opts = m.get("options")
            if not isinstance(opts, list):
                opts = [{"label": "A", "text": ""}, {"label": "B", "text": ""}, {"label": "C", "text": ""}, {"label": "D", "text": ""}]
            db.add(Question(
                generated_test_id=test_id,
                sort_order=i + 1,
                question=m.get("question") or "",
                options=opts,
                correct_option=(m.get("correct_option") or "A").strip().upper()[:1],
                explanation=m.get("explanation") or "",
                difficulty=(m.get("difficulty") or "medium").strip().lower()[:20],
                topic_id=topic_id,
                validation_result=None,
            ))

        test.status = "completed"
        test.failure_reason = None
        test.estimated_input_tokens = total_inp
        test.estimated_output_tokens = total_out
        test.estimated_cost_usd = None
        db.commit()
        logger.info("run_generation: test %s completed with %s questions", test_id, len(mcqs))
    except Exception as e:
        logger.exception("run_generation failed for test_id=%s", test_id)
        try:
            t = db.query(GeneratedTest).filter(GeneratedTest.id == test_id).first()
            if t:
                t.failure_reason = str(e)[:512] if str(e) else None
                _mark_failed(db, t, str(e))
        except Exception:
            pass
    finally:
        if sem_acquired:
            try:
                _generation_semaphore.release()
            except Exception:
                pass
        db.close()


def _mark_failed(db: Session, test: GeneratedTest, reason: str) -> None:
    test.status = "failed"
    test.failure_reason = (reason[:512]) if reason else None
    db.commit()
    logger.warning("Test %s marked failed: %s", test.id, reason)


def clear_one_stuck_test_if_stale(test_id: uuid.UUID, max_age_seconds: float) -> bool:
    """If test is pending/generating and older than max_age_seconds, mark failed. Returns True if updated."""
    from datetime import datetime, timezone
    db = SessionLocal()
    try:
        test = db.query(GeneratedTest).filter(GeneratedTest.id == test_id).first()
        if not test or test.status not in ("pending", "generating"):
            return False
        created = test.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - created).total_seconds()
        if age <= max_age_seconds:
            return False
        test.status = "failed"
        test.failure_reason = "Timed out (stale generating)"
        db.commit()
        logger.info("clear_one_stuck_test_if_stale: test %s marked failed (age %.0fs)", test_id, age)
        return True
    finally:
        db.close()


def cancel_generation(test_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """If test is pending/generating and belongs to user, mark failed. Returns True if cancelled."""
    db = SessionLocal()
    try:
        test = db.query(GeneratedTest).filter(
            GeneratedTest.id == test_id,
            GeneratedTest.user_id == user_id,
        ).first()
        if not test or test.status not in ("pending", "generating"):
            return False
        test.status = "failed"
        test.failure_reason = "Cancelled by user"
        db.commit()
        logger.info("cancel_generation: test %s cancelled", test_id)
        return True
    finally:
        db.close()


def clear_stuck_generating_tests(max_age_seconds: int) -> list[tuple[uuid.UUID, str]]:
    """Mark tests stuck in pending/generating longer than max_age_seconds as failed. Returns list of (test_id, status).
    Uses raw SQL so startup works even when failure_reason column does not exist yet (run alembic upgrade head)."""
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import text
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        # Query only id/status/created_at so we don't require failure_reason column to exist
        rows = db.execute(
            text(
                "SELECT id FROM generated_tests "
                "WHERE status IN ('pending', 'generating') AND created_at < :cutoff"
            ),
            {"cutoff": cutoff},
        ).fetchall()
        ids = [row[0] for row in rows]
        if not ids:
            return []
        # Update status only (no failure_reason), so works before migration 003
        upd = text("UPDATE generated_tests SET status = 'failed' WHERE id = :id")
        for id in ids:
            db.execute(upd, {"id": id})
        db.commit()
        return [(id, "failed") for id in ids]
    finally:
        db.close()
