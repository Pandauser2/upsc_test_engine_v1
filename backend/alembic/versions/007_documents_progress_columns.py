"""Add total_pages and progress_page to documents.

Revision ID: 007
Revises: 006
Create Date: 2026-04-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("total_pages", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("progress_page", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "progress_page")
    op.drop_column("documents", "total_pages")
