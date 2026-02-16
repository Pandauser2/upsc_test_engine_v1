"""
User model: auth (email + password), role (faculty | admin | super_admin).
Documents and tests are scoped by user_id (faculty_id).
"""
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(30), nullable=False, default="faculty"
    )  # faculty | admin | super_admin
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (CheckConstraint("role IN ('faculty', 'admin', 'super_admin')", name="users_role_check"),)

    documents = relationship("Document", back_populates="user", cascade="all, delete-orphan")
    generated_tests = relationship("GeneratedTest", back_populates="user", cascade="all, delete-orphan")
