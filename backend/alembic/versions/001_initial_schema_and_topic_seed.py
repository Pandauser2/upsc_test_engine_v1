"""Initial schema and topic_list seed.

Revision ID: 001
Revises:
Create Date: Initial

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(30), nullable=False, server_default="faculty"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('faculty', 'admin', 'super_admin')", name="users_role_check"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("filename", sa.String(512), nullable=True),
        sa.Column("file_path", sa.String(1024), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="uploaded"),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("source_type IN ('pdf', 'pasted_text')", name="documents_source_type_check"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_user_id", "documents", ["user_id"], unique=False)
    op.create_index("ix_documents_status", "documents", ["status"], unique=False)

    op.create_table(
        "topic_list",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_topic_list_slug", "topic_list", ["slug"], unique=True)

    op.create_table(
        "generated_tests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("generation_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("estimated_input_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_generated_tests_user_id", "generated_tests", ["user_id"], unique=False)
    op.create_index("ix_generated_tests_document_id", "generated_tests", ["document_id"], unique=False)

    op.create_table(
        "questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generated_test_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("correct_option", sa.String(1), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.String(20), nullable=False),
        sa.Column("topic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("validation_result", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("correct_option IN ('A', 'B', 'C', 'D')", name="questions_correct_option_check"),
        sa.CheckConstraint("difficulty IN ('easy', 'medium', 'hard')", name="questions_difficulty_check"),
        sa.ForeignKeyConstraint(["generated_test_id"], ["generated_tests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["topic_list.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generated_test_id", "sort_order", name="uq_questions_test_order"),
    )
    op.create_index("ix_questions_generated_test_id", "questions", ["generated_test_id"], unique=False)
    op.create_index("ix_questions_topic_id", "questions", ["topic_id"], unique=False)

    # Seed topic_list (EXPLORATION: polity, economy, history, geography, science, environment)
    op.execute(
        """
        INSERT INTO topic_list (id, slug, name, sort_order)
        VALUES
            (gen_random_uuid(), 'polity', 'Polity', 1),
            (gen_random_uuid(), 'economy', 'Economy', 2),
            (gen_random_uuid(), 'history', 'History', 3),
            (gen_random_uuid(), 'geography', 'Geography', 4),
            (gen_random_uuid(), 'science', 'Science', 5),
            (gen_random_uuid(), 'environment', 'Environment', 6)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_questions_topic_id", table_name="questions")
    op.drop_index("ix_questions_generated_test_id", table_name="questions")
    op.drop_table("questions")
    op.drop_index("ix_generated_tests_document_id", table_name="generated_tests")
    op.drop_index("ix_generated_tests_user_id", table_name="generated_tests")
    op.drop_table("generated_tests")
    op.drop_index("ix_topic_list_slug", table_name="topic_list")
    op.drop_table("topic_list")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_user_id", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
