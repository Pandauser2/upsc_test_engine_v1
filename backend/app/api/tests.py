"""
Tests API: generate (create test pending, enqueue job), list, get, PATCH test, PATCH question, POST question (manual fill), export .docx, cancel.
All scoped by current user id. On-read cleanup: stale generating tests are marked failed when user loads test/list.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks

logger = logging.getLogger(__name__)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.generated_test import GeneratedTest
from app.models.question import Question
from app.schemas.test import (
    TestGenerateRequest,
    TestResponse,
    TestDetailResponse,
    TestListResponse,
    TestStatusResponse,
    TestPatchRequest,
    QuestionPayload,
    QuestionResponse,
    QuestionPatchRequest,
)
from app.api.deps import get_current_user
from app.config import settings
from app.jobs.tasks import run_generation, clear_one_stuck_test_if_stale, cancel_generation
from app.services.export_docx import build_docx

router = APIRouter(prefix="/tests", tags=["tests"])


def _age_seconds(created_at: datetime) -> float:
    """Seconds since created_at; works for naive (UTC) or aware datetimes."""
    now = datetime.now(timezone.utc)
    c = created_at
    if c.tzinfo:
        c = c.astimezone(timezone.utc)
    else:
        now = datetime.utcnow()
    return (now - c).total_seconds()


def _test_elapsed_time_seconds(t: GeneratedTest) -> int | None:
    """
    Compute elapsed_time for test response: time from create to last update (includes queue + job).
    Only set when generation has finished (terminal status); otherwise return None.
    Calculation: (updated_at - created_at).total_seconds() when both exist and status is terminal.
    """
    if t.status not in ("completed", "partial", "failed", "failed_timeout"):
        return None
    updated = t.updated_at or t.created_at
    created = t.created_at
    if not updated or not created:
        return None
    try:
        delta = updated - created
        return int(delta.total_seconds())
    except (TypeError, AttributeError):
        return None


def _test_to_response(t: GeneratedTest, stale: bool = False) -> TestResponse:
    target = getattr(t, "target_questions", None) or 0
    generated = getattr(t, "questions_generated", None) or 0
    progress = round(generated / target, 2) if target else None
    progress_message = f"{generated} of {target} questions created" if target else None
    return TestResponse(
        id=str(t.id),
        user_id=str(t.user_id),
        document_id=str(t.document_id),
        title=t.title,
        status=t.status,
        prompt_version=t.prompt_version,
        model=t.model,
        estimated_input_tokens=t.estimated_input_tokens,
        estimated_output_tokens=t.estimated_output_tokens,
        estimated_cost_usd=t.estimated_cost_usd,
        failure_reason=getattr(t, "failure_reason", None),
        created_at=t.created_at,
        stale=stale,
        questions_generated=generated if target else None,
        target_questions=target or None,
        progress=progress,
        progress_message=progress_message,
        elapsed_time=_test_elapsed_time_seconds(t),
    )


def _question_to_response(q: Question) -> QuestionResponse:
    return QuestionResponse(
        id=str(q.id),
        generated_test_id=str(q.generated_test_id),
        sort_order=q.sort_order,
        question=q.question,
        options=q.options or {},
        correct_option=q.correct_option,
        explanation=q.explanation,
        difficulty=q.difficulty,
        topic_id=str(q.topic_id),
        validation_result=q.validation_result,
    )


# Validation message for generation start (EXPLORATION §7.3)
TARGET_QUESTIONS_RANGE_MSG = "target_questions must be between 1 and 20"


@router.post("/generate", response_model=TestResponse, status_code=status.HTTP_202_ACCEPTED)
def start_generation(
    data: TestGenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create GeneratedTest (pending), enqueue job, return test_id. Validates target_questions 1–20."""
    from app.models.document import Document
    # Ensure num_questions (target_questions) is set and within 1–20; reject target_n > 20
    nq = getattr(data, "num_questions", None)
    if nq is None or not isinstance(nq, int) or nq < 1 or nq > 20:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=TARGET_QUESTIONS_RANGE_MSG,
        )
    doc_id = uuid.UUID(data.document_id)
    doc_row = db.query(Document).filter(Document.id == doc_id, Document.user_id == current_user.id).first()
    if not doc_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if getattr(doc_row, "status", None) == "rejected":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document was rejected (e.g. PDF exceeds 100 pages). Use another document.",
        )
    # Require extraction completed (status=ready) and extracted_text for text-based generation
    if getattr(doc_row, "status", None) != "ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document is not ready for generation. Wait for extraction to complete (status=ready) or re-upload.",
        )
    if not (getattr(doc_row, "extracted_text", None) or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document has no extracted text. Extraction may have failed; check document status.",
        )
    # Prevent double generation: reject if a run is already pending or in progress for this document
    existing = (
        db.query(GeneratedTest)
        .filter(
            GeneratedTest.document_id == doc_id,
            GeneratedTest.user_id == current_user.id,
            GeneratedTest.status.in_(["pending", "generating"]),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A generation is already in progress for this document. Wait for it to finish.",
        )
    target_n = max(1, min(20, data.num_questions))
    test = GeneratedTest(
        user_id=current_user.id,
        document_id=doc_id,
        title=doc_row.title or doc_row.filename or "Generated test",
        status="pending",
        prompt_version=settings.prompt_version,
        model=settings.active_llm_model,
        target_questions=target_n,
        generation_metadata={
            "num_questions": data.num_questions,
            "difficulty": data.difficulty,
            "export_result": getattr(data, "export_result", False),
        },
    )
    db.add(test)
    db.commit()
    db.refresh(test)
    logger.info("POST /tests/generate: enqueueing run_generation test_id=%s doc_id=%s", test.id, doc_id)
    background_tasks.add_task(run_generation, test.id, doc_id, current_user.id)
    return _test_to_response(test)


@router.get("", response_model=TestListResponse)
def list_tests(
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List current user's tests. Stale (generating too long) is set so UI can show 'may have timed out'."""
    limit = min(max(1, limit), 100)
    offset = max(0, offset)
    q = db.query(GeneratedTest).filter(GeneratedTest.user_id == current_user.id)
    total = q.count()
    items = q.order_by(GeneratedTest.created_at.desc()).offset(offset).limit(limit).all()
    max_stale = getattr(settings, "max_stale_generation_seconds", 1200)
    out = []
    for t in items:
        timeout = (t.generation_metadata or {}).get("stale_timeout_sec") or max_stale
        age = _age_seconds(t.updated_at or t.created_at)
        stale = t.status in ("pending", "generating") and age > timeout
        out.append(_test_to_response(t, stale=stale))
    return TestListResponse(items=out, total=total)


@router.get("/{test_id}/status", response_model=TestStatusResponse)
def get_test_status(
    test_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return status and progress (questions_generated / target_questions). No polling."""
    test = db.query(GeneratedTest).filter(
        GeneratedTest.id == test_id,
        GeneratedTest.user_id == current_user.id,
    ).first()
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")
    target = getattr(test, "target_questions", 0) or 0
    generated = getattr(test, "questions_generated", 0) or 0
    progress = (generated / target) if target else 0.0
    if test.status in ("pending", "generating") and target > 0:
        message = f"Generating... usually under 1 minute. {generated} of {target} questions created"
        timeout = (test.generation_metadata or {}).get("stale_timeout_sec") or getattr(settings, "max_stale_generation_seconds", 1200)
        age = _age_seconds(test.updated_at or test.created_at)
        if age > timeout / 2:
            message += " (this may take a while for large documents)"
    else:
        message = f"{generated} of {target} questions created" if target else test.status
    return TestStatusResponse(
        status=test.status,
        progress=round(progress, 2),
        message=message,
        questions_generated=generated,
        target_questions=target,
        elapsed_time=_test_elapsed_time_seconds(test),
    )


@router.get("/{test_id}", response_model=TestDetailResponse)
def get_test(
    test_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get test with questions; 404 if not owned."""
    test = db.query(GeneratedTest).filter(
        GeneratedTest.id == test_id,
        GeneratedTest.user_id == current_user.id,
    ).first()
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")
    max_stale = getattr(settings, "max_stale_generation_seconds", 1200)
    timeout = (test.generation_metadata or {}).get("stale_timeout_sec") or max_stale
    age = _age_seconds(test.updated_at or test.created_at)
    if test.status in ("pending", "generating") and age > timeout:
        if clear_one_stuck_test_if_stale(test_id, timeout):
            test = db.query(GeneratedTest).filter(
                GeneratedTest.id == test_id,
                GeneratedTest.user_id == current_user.id,
            ).first()
    stale = test.status in ("pending", "generating") and age > timeout
    questions = db.query(Question).filter(Question.generated_test_id == test_id).order_by(Question.sort_order).all()
    base = _test_to_response(test, stale=stale)
    return TestDetailResponse(**base.model_dump(), questions=[_question_to_response(q) for q in questions])


@router.post("/{test_id}/cancel", response_model=TestResponse)
def cancel_test(
    test_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a pending or generating test (mark as failed). No-op if already completed/partial/failed. Improves UX when generation is stuck or user wants to stop."""
    if not cancel_generation(test_id, current_user.id):
        test = db.query(GeneratedTest).filter(
            GeneratedTest.id == test_id,
            GeneratedTest.user_id == current_user.id,
        ).first()
        if not test:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Test is not pending or generating; nothing to cancel.",
        )
    test = db.query(GeneratedTest).filter(
        GeneratedTest.id == test_id,
        GeneratedTest.user_id == current_user.id,
    ).first()
    return _test_to_response(test, stale=False)


@router.patch("/{test_id}", response_model=TestResponse)
def patch_test(
    test_id: uuid.UUID,
    data: TestPatchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update test metadata (e.g. title)."""
    test = db.query(GeneratedTest).filter(
        GeneratedTest.id == test_id,
        GeneratedTest.user_id == current_user.id,
    ).first()
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")
    if data.title is not None:
        test.title = data.title
    db.commit()
    db.refresh(test)
    return _test_to_response(test)


@router.patch("/{test_id}/questions/{question_id}", response_model=QuestionResponse)
def patch_question(
  test_id: uuid.UUID,
  question_id: uuid.UUID,
  data: QuestionPatchRequest,
  current_user: User = Depends(get_current_user),
  db: Session = Depends(get_db),
):
    """Full edit of one question (stem, options, correct_option, explanation, difficulty, topic_id)."""
    test = db.query(GeneratedTest).filter(
        GeneratedTest.id == test_id,
        GeneratedTest.user_id == current_user.id,
    ).first()
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")
    q = db.query(Question).filter(
        Question.id == question_id,
        Question.generated_test_id == test_id,
    ).first()
    if not q:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    if data.question is not None:
        q.question = data.question
    if data.options is not None:
        q.options = data.options
    if data.correct_option is not None:
        q.correct_option = data.correct_option
    if data.explanation is not None:
        q.explanation = data.explanation
    if data.difficulty is not None:
        q.difficulty = data.difficulty
    if data.topic_id is not None:
        q.topic_id = uuid.UUID(data.topic_id)
    db.commit()
    db.refresh(q)
    return _question_to_response(q)


@router.post("/{test_id}/questions", response_model=QuestionResponse, status_code=status.HTTP_201_CREATED)
def add_question(
  test_id: uuid.UUID,
  data: QuestionPayload,
  current_user: User = Depends(get_current_user),
  db: Session = Depends(get_db),
):
    """Manual fill: add question to test (cap = test target_questions, 1-20)."""
    test = db.query(GeneratedTest).filter(
        GeneratedTest.id == test_id,
        GeneratedTest.user_id == current_user.id,
    ).first()
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")
    cap = getattr(test, "target_questions", None)
    if cap is None and test.generation_metadata and isinstance(test.generation_metadata.get("num_questions"), int):
        cap = test.generation_metadata["num_questions"]
    cap = max(1, min(20, cap if cap is not None else 20))
    current_count = db.query(Question).filter(Question.generated_test_id == test_id).count()
    if current_count >= cap:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Test already has {cap} questions; cap enforced.",
        )
    next_order = current_count + 1
    q = Question(
        generated_test_id=test_id,
        sort_order=next_order,
        question=data.question,
        options=data.options,
        correct_option=data.correct_option,
        explanation=data.explanation,
        difficulty=data.difficulty,
        topic_id=uuid.UUID(data.topic_id),
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return _question_to_response(q)


@router.post("/{test_id}/export")
def export_docx(
  test_id: uuid.UUID,
  current_user: User = Depends(get_current_user),
  db: Session = Depends(get_db),
):
    """Export test to .docx: questions, answer key, explanations."""
    test = db.query(GeneratedTest).filter(
        GeneratedTest.id == test_id,
        GeneratedTest.user_id == current_user.id,
    ).first()
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")
    questions = db.query(Question).filter(Question.generated_test_id == test_id).order_by(Question.sort_order).all()
    buf = build_docx(test, questions)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=test-{test_id}.docx"},
    )
