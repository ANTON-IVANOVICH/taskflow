"""async outbox

Revision ID: 20260610_0002
Revises: 20260526_0001
Create Date: 2026-06-10 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260610_0002"
down_revision = "20260526_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    op.create_index(
        op.f("ix_outbox_events_unpublished"),
        "outbox_events",
        ["published_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_outbox_events_unpublished"), table_name="outbox_events")
    op.drop_table("outbox_events")
