"""
Document: PDF upload or pasted text. Has extracted_text (from PDF extraction or paste).
Documents are scoped by user_id.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, BigInteger, Integer, DateTime, CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.types import UuidType


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # pdf | pasted_text
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="uploaded", index=True)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    target_questions: Mapped[int | None] = mapped_column(Integer, nullable=True, default=15)  # 1-20, validated in API
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("source_type IN ('pdf', 'pasted_text')", name="documents_source_type_check"),
    )

    user = relationship("User", back_populates="documents")
    generated_tests = relationship("GeneratedTest", back_populates="document", cascade="all, delete-orphan")
