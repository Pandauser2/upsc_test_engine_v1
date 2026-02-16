"""
Document request/response schemas.
"""
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class DocumentCreatePaste(BaseModel):
    title: str | None = None
    content: str


class DocumentResponse(BaseModel):
    id: str
    user_id: str
    source_type: str
    filename: str | None
    title: str | None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int


class DocumentDetailResponse(DocumentResponse):
    """Single document get; can include extracted_text."""
    extracted_text: str | None = None
