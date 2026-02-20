"""
GeneratedTest: one run of 50 MCQs from one document.
Stores prompt_version, model, token/cost estimates; status partial | failed_timeout when applicable.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, DateTime, ForeignKey, Numeric
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.types import UuidType


class GeneratedTest(Base):
    __tablename__ = "generated_tests"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    generation_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    estimated_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)  # set when status=failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="generated_tests")
    document = relationship("Document", back_populates="generated_tests")
    questions = relationship("Question", back_populates="generated_test", cascade="all, delete-orphan", order_by="Question.sort_order")
