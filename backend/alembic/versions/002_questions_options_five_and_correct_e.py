"""Questions: allow correct_option E and options as array (4 or 5).

Revision ID: 002
Revises: 001
Create Date: 2025-02-20

"""
from typing import Sequence, Union
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("questions_correct_option_check", "questions", type_="check")
    op.create_check_constraint(
        "questions_correct_option_check",
        "questions",
        "correct_option IN ('A', 'B', 'C', 'D', 'E')",
    )


def downgrade() -> None:
    op.drop_constraint("questions_correct_option_check", "questions", type_="check")
    op.create_check_constraint(
        "questions_correct_option_check",
        "questions",
        "correct_option IN ('A', 'B', 'C', 'D')",
    )
