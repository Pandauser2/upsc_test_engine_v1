"""Drop batch_id from generated_tests (Message Batches removed; parallel single calls only).

Revision ID: 006
Revises: 005
Create Date: 2025-02-21

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("generated_tests", "batch_id")


def downgrade() -> None:
    op.add_column("generated_tests", sa.Column("batch_id", sa.String(128), nullable=True))
