"""Add questions_generated and batch_id to generated_tests (batch polling progress).

Revision ID: 005
Revises: 004
Create Date: 2025-02-21

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generated_tests",
        sa.Column("batch_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "generated_tests",
        sa.Column("questions_generated", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("generated_tests", "questions_generated")
    op.drop_column("generated_tests", "batch_id")
