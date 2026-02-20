"""
Documents API: PDF upload, list, get by id. Scoped by current user.
Vision-based generation uses PDF file directly; no text extraction endpoints.
"""
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.document import Document
from app.schemas.document import DocumentResponse, DocumentListResponse, DocumentDetailResponse
from app.api.deps import get_current_user

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)


def _doc_to_response(d: Document) -> DocumentResponse:
    return DocumentResponse(
        id=str(d.id),
        user_id=str(d.user_id),
        source_type=d.source_type,
        filename=d.filename,
        title=d.title,
        status=d.status,
        created_at=d.created_at,
    )


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_pdf(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a PDF file. File is saved; document is ready immediately for vision-based MCQ generation."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must be a PDF")
    _base = Path(__file__).resolve().parent.parent.parent
    upload_dir = (settings.upload_dir if settings.upload_dir.is_absolute() else _base / settings.upload_dir).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    doc_id = uuid.uuid4()
    safe_name = f"{doc_id}.pdf"
    file_path = (upload_dir / safe_name).resolve()
    contents = file.file.read()
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
        status="ready",
        extracted_text="",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
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
