"""Add progress_mcq and total_mcq to generated_tests.

Revision ID: 008
Revises: 007
Create Date: 2026-04-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("generated_tests", sa.Column("progress_mcq", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("generated_tests", sa.Column("total_mcq", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("generated_tests", "total_mcq")
    op.drop_column("generated_tests", "progress_mcq")
