"""Add failure_reason to generated_tests.

Revision ID: 003
Revises: 002
Create Date: 2025-02-20

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generated_tests",
        sa.Column("failure_reason", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generated_tests", "failure_reason")
