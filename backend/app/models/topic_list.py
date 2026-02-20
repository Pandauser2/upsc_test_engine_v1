"""
Topic list: fixed list of allowed topics. Questions reference topic_id (FK).
Prompt must inject exact slugs; model must output one verbatim to avoid FK errors.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.types import UuidType


class TopicList(Base):
    __tablename__ = "topic_list"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    questions = relationship("Question", back_populates="topic")
