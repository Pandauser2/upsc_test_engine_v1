"""
Question: one MCQ; belongs to one GeneratedTest; topic_id FK to topic_list.
Up to 50 per test; partial test has <50; manual fill can add until 50.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.types import UuidType


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), primary_key=True, default=uuid.uuid4
    )
    generated_test_id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), ForeignKey("generated_tests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[dict | list] = mapped_column(JSON, nullable=False)  # [{"label":"A","text":"..."}, ...] (4 or 5 items)
    correct_option: Mapped[str] = mapped_column(String(1), nullable=False)  # A, B, C, D, or E
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), ForeignKey("topic_list.id"), nullable=False, index=True
    )
    validation_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("correct_option IN ('A', 'B', 'C', 'D', 'E')", name="questions_correct_option_check"),
        CheckConstraint("difficulty IN ('easy', 'medium', 'hard')", name="questions_difficulty_check"),
    )

    generated_test = relationship("GeneratedTest", back_populates="questions")
    topic = relationship("TopicList", back_populates="questions")
