"""
Background jobs: run_extraction (PDF → extracted_text), run_generation (extract → chunk → generate from text → persist).
MVP: Generate N+5 candidates → self-validation drop → simple sort → persist up to N; partial if <N. No vision path.
Timeout: passive stale detection + elapsed check at end (if >300s mark failed_timeout).
"""
import logging
import threading
import time
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.generated_test import GeneratedTest
from app.models.document import Document
from app.models.question import Question
from app.models.topic_list import TopicList
from app.services.prompt_helpers import get_topic_slugs_for_prompt

logger = logging.getLogger(__name__)

MIN_QUESTIONS = 1
MAX_QUESTIONS = 20  # MVP cap
# Small buffer for validation drops: request N+5, cap at 20
EXTRA_FOR_VALIDATION = 5
# Max 3 concurrent generation jobs
_generation_semaphore = threading.BoundedSemaphore(3)

# Drop MCQs whose critique contains these (case-insensitive)
BAD_CRITIQUE_SUBSTRINGS = ("incorrect", "wrong")


def _options_list_to_dict(opts: list) -> dict:
    """Convert list [{"label":"A","text":"..."}] to {"A":"..."} for LLM validate_mcq."""
    if not isinstance(opts, list):
        return {}
    return {str(o.get("label", "")).strip().upper(): str(o.get("text", "")) for o in opts if isinstance(o, dict) and o.get("label")}


def _options_to_dict(opts) -> dict:
    """Normalize options to dict {"A":"...","B":"..."} for validate_mcq or DB. Accepts list or dict."""
    if isinstance(opts, dict):
        return {str(k).strip().upper(): str(v) for k, v in opts.items() if str(k).strip().upper() in "ABCDE"}
    return _options_list_to_dict(opts)


def _run_self_validation_and_filter(mcqs: list[dict]) -> tuple[list[dict], int, int]:
    """Run LLM validate_mcq on each; drop any with bad critique (e.g. 'incorrect'/'wrong'). Return (survivors with validation_result, total_inp, total_out)."""
    from app.llm import get_llm_service
    llm = get_llm_service()
    total_inp, total_out = 0, 0
    survivors: list[dict] = []
    for m in mcqs:
        payload = {
            "question": m.get("question") or "",
            "options": _options_to_dict(m.get("options")),
            "correct_option": (m.get("correct_option") or "A").strip().upper(),
            "explanation": m.get("explanation") or "",
        }
        try:
            critique, ci, co = llm.validate_mcq(payload)
            total_inp += ci
            total_out += co
        except Exception as e:
            logger.warning("validate_mcq failed for one question: %s", e)
            critique = ""
        c_lower = (critique or "").lower()
        if any(bad in c_lower for bad in BAD_CRITIQUE_SUBSTRINGS):
            continue
        m = dict(m)
        m["validation_result"] = critique
        survivors.append(m)
    return survivors, total_inp, total_out


def _sort_medium_first(mcqs: list[dict]) -> list[dict]:
    """Simple sort: medium difficulty first, then easy, then hard."""
    def key(m: dict) -> int:
        d = (m.get("difficulty") or "medium").strip().lower()
        return 0 if d == "medium" else (1 if d == "easy" else 2)
    return sorted(mcqs, key=key)


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


def run_extraction(doc_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Background task: run PDF extraction and store extracted_text; set status ready or extraction_failed."""
    db: Session | None = None
    try:
        db = SessionLocal()
        doc = db.query(Document).filter(
            Document.id == doc_id,
            Document.user_id == user_id,
        ).first()
        if not doc:
            logger.warning("run_extraction: document %s not found for user %s", doc_id, user_id)
            return
        if getattr(doc, "source_type", None) != "pdf" or not doc.file_path:
            logger.warning("run_extraction: doc %s is not PDF or has no file_path", doc_id)
            return
        pdf_path = _resolve_pdf_path(doc)
        if not pdf_path:
            doc.status = "extraction_failed"
            doc.extracted_text = ""
            db.commit()
            logger.warning("run_extraction: PDF file not found for doc %s", doc_id)
            return
        from app.services.pdf_extraction_service import extract_hybrid
        result = extract_hybrid(pdf_path)
        doc.extracted_text = result.text or ""
        doc.status = "ready" if (result.is_valid and (result.text or "").strip()) else "extraction_failed"
        db.commit()
        logger.info("run_extraction: doc %s status=%s text_len=%s", doc_id, doc.status, len(doc.extracted_text))
    except Exception as e:
        logger.exception("run_extraction failed for doc_id=%s", doc_id)
        if db:
            try:
                doc = db.query(Document).filter(Document.id == doc_id).first()
                if doc:
                    doc.status = "extraction_failed"
                    doc.extracted_text = ""
                    db.commit()
            except Exception:
                pass
    finally:
        if db:
            db.close()


def run_generation(test_id: uuid.UUID, doc_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """
    Background task: extract → chunk → generate from text (LLM per chunk/batch) → filter bad critique → sort → persist up to N.
    Uses document.extracted_text; no vision path. At end, if elapsed > max_generation_time_seconds, mark failed_timeout.
    """
    run_start = time.monotonic()
    logger.info("run_generation: start test_id=%s doc_id=%s user_id=%s", test_id, doc_id, user_id)
    sem_acquired = False
    db: Session | None = None
    try:
        db = SessionLocal()
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
        if getattr(doc, "status", None) != "ready":
            _mark_failed(db, test, "Document is not ready for generation (status must be ready; run extraction first).")
            return
        extracted_text = (doc.extracted_text or "").strip()
        if not extracted_text:
            _mark_failed(db, test, "Document has no extracted text.")
            return
        min_words = getattr(settings, "min_extraction_words", 500)
        if len(extracted_text.split()) < min_words:
            _mark_failed(db, test, f"Extracted text has fewer than {min_words} words; need more content for generation.")
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

        target_n = getattr(test, "target_questions", None)
        if target_n is None:
            meta = test.generation_metadata if isinstance(test.generation_metadata, dict) else {}
            try:
                n = meta.get("num_questions", MAX_QUESTIONS)
                target_n = max(MIN_QUESTIONS, min(MAX_QUESTIONS, int(n) if n is not None else MAX_QUESTIONS))
            except (TypeError, ValueError):
                target_n = MAX_QUESTIONS
        else:
            target_n = max(MIN_QUESTIONS, min(MAX_QUESTIONS, int(target_n)))

        candidate_count = min(target_n + EXTRA_FOR_VALIDATION, MAX_QUESTIONS)
        logger.info("run_generation: text pipeline test_id=%s candidate_count=%s target_n=%s", test_id, candidate_count, target_n)

        from app.services.mcq_generation_service import generate_mcqs_with_rag
        all_mcqs, _scores, total_inp, total_out = generate_mcqs_with_rag(
            extracted_text,
            topic_slugs=topic_slugs,
            num_questions=candidate_count,
            use_rag=False,
        )

        # MVP: drop any with bad critique (already have validation_result from generate_mcqs_with_rag)
        mcqs = []
        for m in all_mcqs:
            critique = (m.get("validation_result") or "").lower()
            if any(bad in critique for bad in BAD_CRITIQUE_SUBSTRINGS):
                continue
            mcqs.append(m)
        mcqs = _sort_medium_first(mcqs)[:target_n]

        if not mcqs:
            _mark_failed(db, test, "No valid MCQs after filtering (text pipeline).")
            return

        db.query(Question).filter(Question.generated_test_id == test_id).delete()
        for i, m in enumerate(mcqs):
            slug = (m.get("topic_tag") or "polity").strip().lower()
            topic_id = slug_to_topic_id.get(slug) or default_topic_id
            opts = m.get("options")
            if isinstance(opts, dict):
                options_for_db = opts
            else:
                options_for_db = _options_to_dict(opts) or {"A": "", "B": "", "C": "", "D": ""}
            db.add(Question(
                generated_test_id=test_id,
                sort_order=i + 1,
                question=m.get("question") or "",
                options=options_for_db,
                correct_option=(m.get("correct_option") or "A").strip().upper()[:1],
                explanation=m.get("explanation") or "",
                difficulty=(m.get("difficulty") or "medium").strip().lower()[:20],
                topic_id=topic_id,
                validation_result=m.get("validation_result"),
            ))

        elapsed = time.monotonic() - run_start
        max_sec = getattr(settings, "max_generation_time_seconds", 300)
        if elapsed > max_sec:
            test.status = "failed_timeout"
            test.failure_reason = f"Run exceeded {max_sec}s"
        else:
            test.status = "completed" if len(mcqs) >= target_n else "partial"
            test.failure_reason = None
        test.estimated_input_tokens = total_inp
        test.estimated_output_tokens = total_out
        test.estimated_cost_usd = None
        db.commit()
        logger.info("run_generation: test %s %s with %s questions (elapsed %.1fs)", test_id, test.status, len(mcqs), elapsed)
    except Exception as e:
        logger.exception("run_generation failed for test_id=%s", test_id)
        # Mark test failed so it never stays "pending"; use existing db or new session if db failed early
        _db = db if db is not None else SessionLocal()
        try:
            t = _db.query(GeneratedTest).filter(GeneratedTest.id == test_id).first()
            if t:
                _mark_failed(_db, t, str(e)[:512] if str(e) else "Unknown error")
        except Exception:
            pass
        finally:
            if _db is not db:
                _db.close()
    finally:
        if sem_acquired:
            try:
                _generation_semaphore.release()
            except Exception:
                pass
        if db is not None:
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
        test.status = "failed_timeout"
        test.failure_reason = "Timed out (stale generating)"
        db.commit()
        logger.info("clear_one_stuck_test_if_stale: test %s marked failed_timeout (age %.0fs)", test_id, age)
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
        upd = text("UPDATE generated_tests SET status = 'failed_timeout' WHERE id = :id")
        for id in ids:
            db.execute(upd, {"id": id})
        db.commit()
        return [(id, "failed_timeout") for id in ids]
    finally:
        db.close()
