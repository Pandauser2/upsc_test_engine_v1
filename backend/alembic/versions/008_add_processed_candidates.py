"""Add processed_candidates to generated_tests (0–4 during parallel generation).

Revision ID: 008
Revises: 007
Create Date: 2025-02-25

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("generated_tests", sa.Column("processed_candidates", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("generated_tests", "processed_candidates")
