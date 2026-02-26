"""
Document request/response schemas. PDF upload only; no pasted-text endpoint.
"""
from pydantic import BaseModel
from datetime import datetime


class DocumentResponse(BaseModel):
    id: str
    user_id: str
    source_type: str
    filename: str | None
    title: str | None
    status: str
    target_questions: int | None = None  # set server-side (fixed per generation), no user input
    elapsed_time: int | None = None  # extraction duration in seconds (integer)
    total_pages: int | None = None  # PDF page count; set when extraction starts
    extracted_pages: int = 0  # Progress during extraction: "Extracting pages X/Y"
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int


class DocumentDetailResponse(DocumentResponse):
    """Single document get; can include extracted_text."""
    extracted_text: str | None = None


class DocumentExtractResponse(BaseModel):
    """Response for GET /documents/{id}/extract: what was extracted from the document."""
    document_id: str
    source_type: str
    filename: str | None = None
    status: str
    elapsed_time: int | None = None  # extraction duration in seconds (integer)
    extracted_text: str
    character_count: int = 0
    word_count: int = 0
    page_count: int | None = None  # PDF only, when available
    used_ocr_pages: list[int] | None = None  # PDF only, 0-based page indices where OCR was used
    extraction_valid: bool | None = None  # PDF only, when extraction run on demand
    extraction_error: str | None = None  # PDF only, when extraction run on demand and failed
