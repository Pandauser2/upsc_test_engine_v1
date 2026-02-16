"""
Tests API: generate (create test pending, enqueue job), list, get, PATCH test, PATCH question, POST question (manual fill), export .docx.
All scoped by current user id.
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
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
    TestPatchRequest,
    QuestionPayload,
    QuestionResponse,
    QuestionPatchRequest,
)
from app.api.deps import get_current_user
from app.config import settings
from app.jobs.tasks import run_generation
from app.services.export_docx import build_docx

router = APIRouter(prefix="/tests", tags=["tests"])


def _test_to_response(t: GeneratedTest) -> TestResponse:
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
        created_at=t.created_at,
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


@router.post("/generate", response_model=TestResponse, status_code=status.HTTP_202_ACCEPTED)
def start_generation(
    data: TestGenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create GeneratedTest (pending), enqueue job, return test_id."""
    from app.models.document import Document
    doc_id = uuid.UUID(data.document_id)
    doc_row = db.query(Document).filter(Document.id == doc_id, Document.user_id == current_user.id).first()
    if not doc_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    test = GeneratedTest(
        user_id=current_user.id,
        document_id=doc_id,
        title=doc_row.title or doc_row.filename or "Generated test",
        status="pending",
        prompt_version=settings.prompt_version,
        model=settings.openai_model,
    )
    db.add(test)
    db.commit()
    db.refresh(test)
    background_tasks.add_task(run_generation, test.id, doc_id, current_user.id)
    return _test_to_response(test)


@router.get("", response_model=TestListResponse)
def list_tests(
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List current user's tests."""
    limit = min(max(1, limit), 100)
    offset = max(0, offset)
    q = db.query(GeneratedTest).filter(GeneratedTest.user_id == current_user.id)
    total = q.count()
    items = q.order_by(GeneratedTest.created_at.desc()).offset(offset).limit(limit).all()
    return TestListResponse(items=[_test_to_response(t) for t in items], total=total)


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
    questions = db.query(Question).filter(Question.generated_test_id == test_id).order_by(Question.sort_order).all()
    base = _test_to_response(test)
    return TestDetailResponse(**base.model_dump(), questions=[_question_to_response(q) for q in questions])


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
    """Manual fill: add question to test (for partial tests until 50)."""
    test = db.query(GeneratedTest).filter(
        GeneratedTest.id == test_id,
        GeneratedTest.user_id == current_user.id,
    ).first()
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")
    current_count = db.query(Question).filter(Question.generated_test_id == test_id).count()
    if current_count >= 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Test already has 50 questions; cap enforced.",
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
