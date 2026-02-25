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
# Candidate count: generate this many before validation filter (config/env MCQ_CANDIDATE_COUNT, default 4)
def _get_candidate_count() -> int:
    return max(1, min(MAX_QUESTIONS, getattr(settings, "mcq_candidate_count", 4)))
# Max 3 concurrent generation jobs
_generation_semaphore = threading.BoundedSemaphore(3)

# Drop MCQs whose critique contains these (case-insensitive). Use specific phrases so we don't drop when critique only says "option B is incorrect" (distractor).
BAD_CRITIQUE_SUBSTRINGS = ("incorrect key", "wrong answer", "incorrect answer", "key is wrong", "explanation is wrong")


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
    """Background task: run PDF extraction and store extracted_text; set status ready or extraction_failed.
    Elapsed time: we measure with time.monotonic() from start to finish and store in doc.extraction_elapsed_seconds
    (integer seconds); returned as elapsed_time in document response JSON."""
    t0 = time.monotonic()
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
            elapsed = int(time.monotonic() - t0)
            doc.extraction_elapsed_seconds = elapsed
            doc.status = "extraction_failed"
            doc.extracted_text = ""
            db.commit()
            logger.warning("run_extraction: PDF file not found for doc %s (elapsed=%ss)", doc_id, elapsed)
            return
        from app.services.pdf_extraction_service import extract_hybrid
        result = extract_hybrid(pdf_path)
        elapsed = int(time.monotonic() - t0)
        doc.extracted_text = result.text or ""
        doc.status = "ready" if (result.is_valid and (result.text or "").strip()) else "extraction_failed"
        doc.extraction_elapsed_seconds = elapsed
        db.commit()
        logger.info("run_extraction: doc %s status=%s text_len=%s elapsed_time=%ss", doc_id, doc.status, len(doc.extracted_text), elapsed)
    except Exception as e:
        elapsed = int(time.monotonic() - t0)
        logger.exception("run_extraction failed for doc_id=%s (elapsed=%ss)", doc_id, elapsed)
        if db:
            try:
                doc = db.query(Document).filter(Document.id == doc_id).first()
                if doc:
                    doc.extraction_elapsed_seconds = elapsed
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

        candidate_count = _get_candidate_count()  # 4: max parallel workers / batch requests
        num_questions = min(target_n + 2, MAX_QUESTIONS)  # small buffer for validation drop
        meta = test.generation_metadata if isinstance(test.generation_metadata, dict) else {}
        requested_difficulty = (meta.get("difficulty") or "MEDIUM")
        if isinstance(requested_difficulty, str):
            requested_difficulty = requested_difficulty.strip().upper()
            if requested_difficulty not in ("EASY", "MEDIUM", "HARD"):
                requested_difficulty = "MEDIUM"
        else:
            requested_difficulty = "MEDIUM"
        logger.info("run_generation: text pipeline test_id=%s candidate_count=%s target_n=%s num_questions=%s difficulty=%s", test_id, candidate_count, target_n, num_questions, requested_difficulty)

        from app.services.chunking_service import chunk_text
        mode = getattr(settings, "chunk_mode", "semantic")
        chunks_for_outline = chunk_text(
            extracted_text,
            mode=mode,
            chunk_size=getattr(settings, "chunk_size", 1500),
            overlap_fraction=getattr(settings, "chunk_overlap_fraction", 0.2),
        )
        num_chunks = len(chunks_for_outline or [])
        min_chunks = getattr(settings, "rag_min_chunks_for_global", 20)
        use_global_rag = getattr(settings, "use_global_rag", True)
        global_outline_arg: str | None = None
        use_rag_flag = False
        if use_global_rag and num_chunks > min_chunks:
            t_outline_start = time.monotonic()
            try:
                from app.services.summarization_service import summarize_chunk, generate_global_outline
                max_chunks = max(1, min(20, getattr(settings, "rag_outline_max_chunks", 10)))
                chunk_summaries = []
                for c in (chunks_for_outline or [])[:max_chunks]:
                    s = summarize_chunk(c)
                    if s:
                        chunk_summaries.append(s)
                global_outline_arg = generate_global_outline(chunk_summaries) if chunk_summaries else ""
                use_rag_flag = True
                outline_elapsed = time.monotonic() - t_outline_start
                logger.info(
                    "Global RAG activated",
                    extra={"chunks": num_chunks, "threshold": min_chunks},
                )
                logger.info("run_generation: Global RAG enabled (chunks=%s); outline %.2fs", num_chunks, outline_elapsed)
            except Exception as ex:
                logger.warning("run_generation: outline/rag prep failed, falling back to no RAG: %s", ex)
                use_rag_flag = False
                global_outline_arg = None
        else:
            if not use_global_rag:
                logger.info("run_generation: Global RAG skipped (disabled)")
            else:
                logger.info("run_generation: Global RAG skipped (chunks=%s <= threshold %s)", num_chunks, min_chunks)

        # Dynamic timeout: base + 1 min per 10 chunks (so 100-page PDFs don't get marked stale)
        base_stale_sec = getattr(settings, "max_stale_generation_seconds", 1200)
        timeout_sec = base_stale_sec + (num_chunks // 10 * 60)
        meta = test.generation_metadata if isinstance(test.generation_metadata, dict) else {}
        meta = dict(meta)
        meta["stale_timeout_sec"] = timeout_sec
        test.generation_metadata = meta
        db.commit()

        def _heartbeat() -> None:
            _db = SessionLocal()
            try:
                t = _db.query(GeneratedTest).filter(GeneratedTest.id == test_id).first()
                if t:
                    from datetime import datetime, timezone
                    t.updated_at = datetime.now(timezone.utc)
                    _db.commit()
            except Exception as hb_ex:
                logger.warning("run_generation: heartbeat failed: %s", hb_ex)
            finally:
                _db.close()

        from app.services.mcq_generation_service import generate_mcqs_with_rag
        t_gen_start = time.monotonic()
        all_mcqs, _scores, total_inp, total_out, _ = generate_mcqs_with_rag(
            extracted_text,
            topic_slugs=topic_slugs,
            num_questions=num_questions,
            target_n=target_n,
            use_rag=use_rag_flag,
            global_outline=global_outline_arg,
            difficulty=requested_difficulty,
            heartbeat_callback=_heartbeat,
        )
        gen_elapsed = time.monotonic() - t_gen_start
        logger.info("run_generation: generate_mcqs_with_rag %.2fs (use_rag=%s)", gen_elapsed, use_rag_flag)

        # Drop any with bad critique (already have validation_result from generate_mcqs_with_rag)
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

        persist_difficulty = requested_difficulty.lower()[:20]
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
                difficulty=persist_difficulty,
                topic_id=topic_id,
                validation_result=m.get("validation_result"),
            ))

        elapsed = time.monotonic() - run_start
        if elapsed > timeout_sec:
            test.status = "failed_timeout"
            test.failure_reason = f"Run exceeded {timeout_sec}s"
            logger.info("run_generation: Job timed out after %.0fs (chunks=%s, target=%s)", elapsed, num_chunks, target_n)
        else:
            test.status = "completed" if len(mcqs) >= target_n else "partial"
            test.failure_reason = None
        test.questions_generated = len(mcqs)
        test.estimated_input_tokens = total_inp
        test.estimated_output_tokens = total_out
        test.estimated_cost_usd = None
        db.commit()
        logger.info("run_generation: test %s %s with %s questions (elapsed %.1fs)", test_id, test.status, len(mcqs), elapsed)

        # Optional: export MCQs to JSON for quality baseline (ENABLE_EXPORT=true and export_result=true)
        if getattr(settings, "enable_export", False) and isinstance(test.generation_metadata, dict) and test.generation_metadata.get("export_result"):
            try:
                import json
                from datetime import datetime, timezone
                export_dir = getattr(settings, "exports_dir", None) or Path("./exports")
                export_dir = export_dir if isinstance(export_dir, Path) else Path(export_dir)
                if not export_dir.is_absolute():
                    _base = Path(__file__).resolve().parent.parent
                    export_dir = (_base / export_dir).resolve()
                export_dir.mkdir(parents=True, exist_ok=True)
                payload = {
                    "test_id": str(test_id),
                    "document_title": (test.title or ""),
                    "num_questions": getattr(test, "target_questions", 0),
                    "status": test.status,
                    "questions_generated": len(mcqs),
                    "exported_at": datetime.now(tz=timezone.utc).isoformat(),
                    "mcqs": [
                        {
                            "question": m.get("question"),
                            "options": m.get("options"),
                            "correct_option": m.get("correct_option"),
                            "explanation": m.get("explanation"),
                            "difficulty": m.get("difficulty"),
                            "topic_tag": m.get("topic_tag"),
                            "validation_result": m.get("validation_result"),
                            "quality_score": m.get("quality_score"),
                        }
                        for m in mcqs
                    ],
                }
                path = export_dir / f"{test_id}.json"
                path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.info("run_generation: exported baseline to %s", path)
            except Exception as ex:
                logger.warning("run_generation: export failed: %s", ex)
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


def clear_one_stuck_test_if_stale(test_id: uuid.UUID, max_age_seconds: float | None = None) -> bool:
    """If test is pending/generating and older than timeout (from metadata or max_age_seconds), mark failed. Uses updated_at for age when set (heartbeat). Returns True if updated."""
    from datetime import datetime, timezone
    db = SessionLocal()
    try:
        test = db.query(GeneratedTest).filter(GeneratedTest.id == test_id).first()
        if not test or test.status not in ("pending", "generating"):
            return False
        timeout = max_age_seconds
        if timeout is None:
            meta = test.generation_metadata if isinstance(test.generation_metadata, dict) else {}
            timeout = meta.get("stale_timeout_sec") or getattr(settings, "max_stale_generation_seconds", 1200)
        ref = test.updated_at or test.created_at
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age = (now - ref).total_seconds()
        if age <= timeout:
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
        # Use COALESCE(updated_at, created_at) so heartbeating jobs aren't cleared
        rows = db.execute(
            text(
                "SELECT id FROM generated_tests "
                "WHERE status IN ('pending', 'generating') AND COALESCE(updated_at, created_at) < :cutoff"
            ),
            {"cutoff": cutoff},
        ).fetchall()
        ids = [row[0] for row in rows]
        if not ids:
            return []
        # Update status only (no failure_reason), so works before migration 003
        upd = text("UPDATE generated_tests SET status = 'failed_timeout' WHERE id = :id")
        for test_id in ids:
            db.execute(upd, {"id": test_id})
        db.commit()
        return [(test_id, "failed_timeout") for test_id in ids]
    finally:
        db.close()
