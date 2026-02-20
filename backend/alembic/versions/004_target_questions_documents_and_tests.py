"""Add target_questions to documents and generated_tests (MVP: 1-20, default 15).

Revision ID: 004
Revises: 003
Create Date: 2025-02-20

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("target_questions", sa.Integer(), nullable=True, server_default="15"),
    )
    op.add_column(
        "generated_tests",
        sa.Column("target_questions", sa.Integer(), nullable=False, server_default="15"),
    )


def downgrade() -> None:
    op.drop_column("documents", "target_questions")
    op.drop_column("generated_tests", "target_questions")
