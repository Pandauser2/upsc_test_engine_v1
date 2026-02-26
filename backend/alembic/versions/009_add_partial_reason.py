"""Add partial_reason to generated_tests (when status=partial, questions_generated < target_n).

Revision ID: 009
Revises: 008
Create Date: 2026-02-26

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generated_tests",
        sa.Column("partial_reason", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generated_tests", "partial_reason")
