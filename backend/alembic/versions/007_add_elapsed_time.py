"""Add extraction_elapsed_seconds to documents. Test elapsed_time is computed from created_at/updated_at in API.

Revision ID: 007
Revises: 006
Create Date: 2025-02-22

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("extraction_elapsed_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "extraction_elapsed_seconds")
