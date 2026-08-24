"""insert the four C002 prompt templates

Revision ID: 6b8e3f0a1d24
Revises: 3ad09fb566ed
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6b8e3f0a1d24"
down_revision: Union[str, None] = "3ad09fb566ed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    prompt_templates = sa.table(
        "prompt_templates",
        sa.column("key", sa.String()),
        sa.column("content", sa.Text()),
    )
    op.bulk_insert(
        prompt_templates,
        [
            {
                "key": "script2assets",
                "content": "[占位] script2assets 初始内容待需求方提供",
            },
            {
                "key": "script2shots",
                "content": "[占位] script2shots 初始内容待需求方提供",
            },
            {
                "key": "zimage",
                "content": "[占位] zimage 初始内容待需求方提供",
            },
            {
                "key": "minimaxh3",
                "content": "[占位] minimaxh3 初始内容待需求方提供",
            },
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM prompt_templates "
            "WHERE key IN ('script2assets', 'script2shots', 'zimage', 'minimaxh3')"
        )
    )
