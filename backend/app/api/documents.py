"""
Documents API: upload PDF (BackgroundTasks extraction), paste text, list, get.
All scoped by current user id.
"""
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.document import Document
from app.schemas.document import DocumentCreatePaste, DocumentResponse, DocumentListResponse, DocumentDetailResponse
from app.api.deps import get_current_user
from app.config import settings
from app.services.pdf_extract import extract_text_from_pdf

router = APIRouter(prefix="/documents", tags=["documents"])


def _document_to_response(d: Document) -> DocumentResponse:
    return DocumentResponse(
        id=str(d.id),
        user_id=str(d.user_id),
        source_type=d.source_type,
        filename=d.filename,
        title=d.title,
        status=d.status,
        created_at=d.created_at,
    )


def _run_pdf_extraction(document_id: uuid.UUID) -> None:
    """Background task: load document, extract PDF text, update status and extracted_text."""
    import logging
    logger = logging.getLogger(__name__)
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc or doc.source_type != "pdf" or not doc.file_path:
            return
        try:
            text = extract_text_from_pdf(doc.file_path)
            doc.extracted_text = text or ""
            doc.status = "ready"
        except Exception as e:
            logger.warning("PDF extraction failed for document %s: %s", document_id, e)
            doc.status = "failed"
            doc.extracted_text = ""
        db.commit()
    finally:
        db.close()


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload PDF; save file, create document (status uploaded), enqueue extraction."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PDF file required")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4()
    ext = Path(file.filename).suffix or ".pdf"
    save_path = settings.upload_dir / f"{file_id}{ext}"
    with open(save_path, "wb") as f:
        f.write(file.file.read())
    size = save_path.stat().st_size
    doc = Document(
        user_id=current_user.id,
        source_type="pdf",
        filename=file.filename,
        file_path=str(save_path),
        file_size_bytes=size,
        status="uploaded",
        extracted_text="",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    background_tasks.add_task(_run_pdf_extraction, doc.id)
    return _document_to_response(doc)


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def create_from_paste(
    data: DocumentCreatePaste,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create document from pasted text; no job, status ready immediately."""
    doc = Document(
        user_id=current_user.id,
        source_type="pasted_text",
        filename=None,
        file_path=None,
        title=data.title,
        status="ready",
        extracted_text=data.content,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _document_to_response(doc)


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
    return DocumentListResponse(items=[_document_to_response(d) for d in items], total=total)


@router.get("/{document_id}", response_model=DocumentDetailResponse)
def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get one document (with extracted_text); 404 if not found or not owned."""
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    base = _document_to_response(doc)
    return DocumentDetailResponse(**base.model_dump(), extracted_text=doc.extracted_text or None)
