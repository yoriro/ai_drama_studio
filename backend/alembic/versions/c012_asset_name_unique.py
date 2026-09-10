"""add the project-scoped asset name constraint

Revision ID: c012_asset_name_unique
Revises: 6b8e3f0a1d24
Create Date: 2026-09-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c012_asset_name_unique"
down_revision: Union[str, None] = "6b8e3f0a1d24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _name_row(
    project_id: int,
    asset_id: int,
    original_name: str,
) -> tuple[int, int, str, str]:
    return project_id, asset_id, original_name, original_name.strip()


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT project_id, id, name "
            "FROM assets "
            "ORDER BY project_id, id"
        )
    ).mappings()

    normalized_groups: dict[tuple[int, str], list[tuple[int, int, str, str]]] = {}
    non_normalized: list[tuple[int, int, str, str]] = []
    for row in rows:
        item = _name_row(int(row["project_id"]), int(row["id"]), row["name"])
        normalized_groups.setdefault((item[0], item[3]), []).append(item)
        if not item[3] or item[2] != item[3]:
            non_normalized.append(item)

    conflicts = [
        group for group in normalized_groups.values() if len(group) > 1
    ]
    if conflicts or non_normalized:
        details: list[str] = []
        if conflicts:
            details.append(f"normalized_conflicts={conflicts!r}")
        if non_normalized:
            details.append(f"non_normalized={non_normalized!r}")
        raise RuntimeError(
            "assets name precheck failed "
            "(project_id, asset_id, original_name, normalized_name): "
            + "; ".join(details)
        )

    op.create_unique_constraint(
        "uq_assets_project_name",
        "assets",
        ["project_id", "name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_assets_project_name", "assets", type_="unique")
