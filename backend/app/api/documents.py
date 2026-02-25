"""
Documents API: PDF upload only (MVP: max 100 pages). Extraction runs in background; list, get by id. Scoped by current user.
"""
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.document import Document
from app.schemas.document import (
    DocumentResponse,
    DocumentListResponse,
    DocumentDetailResponse,
    DocumentExtractResponse,
)
from app.api.deps import get_current_user
from app.jobs.tasks import run_extraction
from app import metrics

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)

REJECTED_PDF_MESSAGE = (
    "For MVP, PDFs are limited to 100 pages to ensure fast & high-quality generation. "
    "Please split larger files or contact support for bigger documents."
)


def _pdf_page_count(contents: bytes) -> int | None:
    """Return page count using PyMuPDF (reused from vision pipeline). None on error."""
    try:
        import pymupdf
        doc = pymupdf.open(stream=contents, filetype="pdf")
        try:
            return len(doc)
        finally:
            doc.close()
    except Exception:
        return None


def _doc_to_response(d: Document) -> DocumentResponse:
    # elapsed_time: extraction duration in seconds, set by run_extraction when PDF extraction finishes
    return DocumentResponse(
        id=str(d.id),
        user_id=str(d.user_id),
        source_type=d.source_type,
        filename=d.filename,
        title=d.title,
        status=d.status,
        target_questions=getattr(d, "target_questions", None),
        elapsed_time=getattr(d, "extraction_elapsed_seconds", None),
        created_at=d.created_at,
    )


def _resolve_pdf_path(doc: Document) -> str | None:
    """Resolve document file_path to absolute path; return None if not found."""
    if not doc or not (doc.file_path or "").strip():
        return None
    path = Path(doc.file_path).resolve()
    if path.exists():
        return str(path)
    _base = Path(__file__).resolve().parent.parent.parent
    alt = (_base / doc.file_path).resolve()
    if alt.exists():
        return str(alt)
    return None


def _normalize_target_questions(value: int | None) -> int:
    """Return value clamped to 1-20; default 15 if None or invalid."""
    if value is None:
        return 15
    try:
        n = int(value)
        return max(1, min(20, n))
    except (TypeError, ValueError):
        return 15


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    num_questions: int | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a PDF. MVP: max 100 pages. Extraction runs in background; doc status processing → ready or extraction_failed. Optional num_questions (1-20) stored on document."""
    if num_questions is not None and (num_questions < 1 or num_questions > 20):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Number of questions must be between 1 and 20.",
        )
    target_q = _normalize_target_questions(num_questions)

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must be a PDF")
    contents = file.file.read()
    page_count = _pdf_page_count(contents)
    if page_count is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not read PDF or determine page count")
    max_pages = getattr(settings, "max_pdf_pages", 100)
    if page_count > max_pages:
        logger.warning("PDF rejected: page_count=%s > max_pages=%s filename=%s user_id=%s", page_count, max_pages, file.filename, current_user.id)
        doc_id = uuid.uuid4()
        doc = Document(
            id=doc_id,
            user_id=current_user.id,
            source_type="pdf",
            filename=file.filename or "document.pdf",
            file_path=None,
            file_size_bytes=len(contents),
            title=file.filename or None,
            status="rejected",
            extracted_text="",
            target_questions=target_q,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=REJECTED_PDF_MESSAGE,
        )
    _base = Path(__file__).resolve().parent.parent.parent
    upload_dir = (settings.upload_dir if settings.upload_dir.is_absolute() else _base / settings.upload_dir).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    doc_id = uuid.uuid4()
    safe_name = f"{doc_id}.pdf"
    file_path = (upload_dir / safe_name).resolve()
    try:
        file_path.write_bytes(contents)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to save file: {e}")
    doc = Document(
        id=doc_id,
        user_id=current_user.id,
        source_type="pdf",
        filename=file.filename or "document.pdf",
        file_path=str(file_path),
        file_size_bytes=len(contents),
        title=file.filename or None,
        status="processing",
        extracted_text="",
        target_questions=target_q,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    if background_tasks:
        background_tasks.add_task(run_extraction, doc.id, current_user.id)
    return _doc_to_response(doc)


@router.get("", response_model=DocumentListResponse)
def list_documents(
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List current user's documents."""
    limit = min(max(1, limit), 100)
    offset = max(0, offset)
    q = db.query(Document).filter(Document.user_id == current_user.id)
    total = q.count()
    items = q.order_by(Document.created_at.desc()).offset(offset).limit(limit).all()
    return DocumentListResponse(items=[_doc_to_response(d) for d in items], total=total)


@router.get("/{document_id}/extract", response_model=DocumentExtractResponse)
def get_document_extract(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return what was extracted from the document (stored text or run PDF extraction on demand)."""
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    text = (doc.extracted_text or "").strip()
    page_count: int | None = None
    used_ocr_pages: list[int] | None = None
    extraction_valid: bool | None = None
    extraction_error: str | None = None

    if doc.source_type == "pdf" and not text:
        pdf_path = _resolve_pdf_path(doc)
        if pdf_path:
            timeout_sec = getattr(settings, "extract_on_demand_timeout_seconds", 600)
            try:
                from app.services.pdf_extraction_service import extract_hybrid
                pool = ThreadPoolExecutor(max_workers=1)
                try:
                    future = pool.submit(extract_hybrid, pdf_path)
                    result = future.result(timeout=timeout_sec)
                    text = result.text or ""
                    page_count = result.page_count
                    used_ocr_pages = list(result.used_ocr_pages)
                    extraction_valid = result.is_valid
                    extraction_error = result.error_message
                    if text:
                        doc.extracted_text = text
                        db.commit()
                except (FuturesTimeoutError, TimeoutError):
                    extraction_timeouts_total = metrics.increment_extraction_timeouts_total()
                    logger.warning(
                        "On-demand PDF extraction timed out",
                        extra={
                            "document_id": str(document_id),
                            "timeout_seconds": timeout_sec,
                            "extraction_timeouts_total": extraction_timeouts_total,
                        },
                    )
                    extraction_valid = False
                    extraction_error = (
                        f"Extraction timed out (limit {timeout_sec}s). "
                        "Retry GET /documents/{id}/extract later or check document status via GET /documents/{id}."
                    )
                finally:
                    pool.shutdown(wait=False)  # return immediately on timeout; don't block until worker finishes
            except Exception as e:
                logger.warning("On-demand PDF extraction failed for doc %s: %s", document_id, e)
                extraction_valid = False
                extraction_error = str(e)[:512]

    def _word_count(s: str) -> int:
        return len(s.split()) if s else 0

    return DocumentExtractResponse(
        document_id=str(doc.id),
        source_type=doc.source_type,
        filename=doc.filename,
        status=doc.status,
        elapsed_time=getattr(doc, "extraction_elapsed_seconds", None),
        extracted_text=text,
        character_count=len(text),
        word_count=_word_count(text),
        page_count=page_count,
        used_ocr_pages=used_ocr_pages if used_ocr_pages else None,
        extraction_valid=extraction_valid,
        extraction_error=extraction_error,
    )


@router.get("/{document_id}", response_model=DocumentDetailResponse)
def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get one document by id; includes extracted_text."""
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return DocumentDetailResponse(
        **_doc_to_response(doc).model_dump(),
        extracted_text=doc.extracted_text,
    )
