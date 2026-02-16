"""
Generation job: extract (if needed) -> chunk -> generate batches -> dedupe -> validate -> rank -> select best 50 -> persist.
Enforces max_generation_time_seconds = 300; sets status partial | failed_timeout when applicable.
"""
import logging
import time
import uuid
from decimal import Decimal
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.config import settings
from app.models.document import Document
from app.models.generated_test import GeneratedTest
from app.models.question import Question
from app.models.topic_list import TopicList
from app.services.chunking import chunk_text
from app.services.dedupe import deduplicate_mcqs
from app.services.ranking import rank_mcqs, select_top_with_topic_diversity
from app.services.validation import run_validation_on_mcqs
from app.services.prompt_helpers import get_topic_slugs_for_prompt
from app.llm import get_llm_service

logger = logging.getLogger(__name__)

# Rough cost per 1K tokens for gpt-4o-mini (USD).
INPUT_COST_PER_1K = Decimal("0.00015")
OUTPUT_COST_PER_1K = Decimal("0.0006")


def _slug_to_topic_id(db: Session) -> dict[str, uuid.UUID]:
    """Build slug -> topic_list.id map for persisting questions."""
    rows = db.query(TopicList).all()
    return {r.slug: r.id for r in rows}


def _elapsed(start: float) -> float:
    return time.time() - start


def _normalize_correct_option(raw: str | None) -> str:
    """Return one of A, B, C, D for DB constraint."""
    if not raw:
        return "A"
    c = str(raw).strip().upper()[:1]
    return c if c in ("A", "B", "C", "D") else "A"


def run_generation(test_id: uuid.UUID, document_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """
    Background task: load existing test (pending), set generating, run pipeline, persist questions, set final status.
    Enforces 300s timeout; on <50 valid MCQs sets status = partial.
    """
    db = SessionLocal()
    start = time.time()
    try:
        test = db.query(GeneratedTest).filter(
            GeneratedTest.id == test_id,
            GeneratedTest.document_id == document_id,
            GeneratedTest.user_id == user_id,
        ).first()
        if not test:
            logger.error("Test %s not found", test_id)
            return
        test.status = "generating"
        db.commit()

        doc = db.query(Document).filter(Document.id == document_id, Document.user_id == user_id).first()
        if not doc:
            logger.error("Document %s not found", document_id)
            test.status = "failed"
            db.commit()
            return
        if not doc.extracted_text or not doc.extracted_text.strip():
            logger.error("Document %s has no extracted text", document_id)
            test.status = "failed"
            db.commit()
            return

        topic_slugs = get_topic_slugs_for_prompt(db)
        slug_to_id = _slug_to_topic_id(db)
        llm = get_llm_service()
        total_input, total_output = 0, 0
        all_mcqs = []

        chunks = chunk_text(doc.extracted_text)
        for chunk in chunks:
            # Strict 300s cap: check before each chunk
            if _elapsed(start) >= settings.max_generation_time_seconds:
                test.status = "failed_timeout"
                test.estimated_input_tokens = total_input
                test.estimated_output_tokens = total_output
                test.estimated_cost_usd = (
                    (total_input / 1000) * INPUT_COST_PER_1K + (total_output / 1000) * OUTPUT_COST_PER_1K
                )
                db.commit()
                logger.warning("Generation timeout for test %s", test.id)
                return
            try:
                mcqs, ti, to = llm.generate_mcqs(chunk, topic_slugs)
                all_mcqs.extend(mcqs)
                total_input += ti
                total_output += to
            except Exception as e:
                logger.exception("generate_mcqs failed: %s", e)
                continue

        if _elapsed(start) >= settings.max_generation_time_seconds:
            test.status = "failed_timeout"
            test.estimated_input_tokens = total_input
            test.estimated_output_tokens = total_output
            test.estimated_cost_usd = (
                (total_input / 1000) * INPUT_COST_PER_1K + (total_output / 1000) * OUTPUT_COST_PER_1K
            )
            db.commit()
            return

        # Dedupe -> validate subset (cap to avoid timeout) -> rank -> select 50
        deduped = deduplicate_mcqs(all_mcqs)
        pool = deduped[:100]  # Validate at most 100 for speed
        validated, vi, vo = run_validation_on_mcqs(pool)
        total_input += vi
        total_output += vo
        validation_by_idx = {i: m.get("validation_result") or "" for i, m in enumerate(validated)}
        ranked = rank_mcqs(validated, validation_results=validation_by_idx, prefer_medium=True)
        top = select_top_with_topic_diversity(ranked, 50)

        if _elapsed(start) >= settings.max_generation_time_seconds:
            test.status = "failed_timeout"
            test.estimated_input_tokens = total_input
            test.estimated_output_tokens = total_output
            test.estimated_cost_usd = (
                (total_input / 1000) * INPUT_COST_PER_1K + (total_output / 1000) * OUTPUT_COST_PER_1K
            )
            db.commit()
            return

        # Persist questions; map slug -> topic_id
        for i, m in enumerate(top, 1):
            slug = m.get("topic_tag", "polity")
            topic_id = slug_to_id.get(slug) or slug_to_id.get("polity")
            if not topic_id:
                continue
            opts = m.get("options") or {}
            if not isinstance(opts, dict):
                opts = {}
            raw_diff = (m.get("difficulty") or "medium").strip().lower()
            difficulty = raw_diff if raw_diff in ("easy", "medium", "hard") else "medium"
            q = Question(
                generated_test_id=test.id,
                sort_order=i,
                question=(m.get("question") or "").strip(),
                options=opts,
                correct_option=_normalize_correct_option(m.get("correct_option")),
                explanation=(m.get("explanation") or "").strip(),
                difficulty=difficulty,
                topic_id=topic_id,
                validation_result=(m.get("validation_result") or "").strip() or None,
            )
            db.add(q)

        test.status = "completed" if len(top) >= 50 else "partial"
        test.estimated_input_tokens = total_input
        test.estimated_output_tokens = total_output
        test.estimated_cost_usd = (
            (total_input / 1000) * INPUT_COST_PER_1K + (total_output / 1000) * OUTPUT_COST_PER_1K
        )
        db.commit()
    except Exception as e:
        logger.exception("run_generation failed: %s", e)
        try:
            test = db.query(GeneratedTest).filter(GeneratedTest.id == test_id).first()
            if test:
                test.status = "failed"
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()
