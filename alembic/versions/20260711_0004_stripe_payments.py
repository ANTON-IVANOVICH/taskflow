"""stripe payment records

Revision ID: 20260711_0004
Revises: 20260701_0003
Create Date: 2026-07-11 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260711_0004"
down_revision = "20260701_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("customer_email", sa.String(length=320), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("checkout_url", sa.String(length=1000), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
    )
    op.create_index(
        op.f("ix_payments_provider_external"),
        "payments",
        ["provider", "external_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_payments_provider_idempotency"),
        "payments",
        ["provider", "idempotency_key"],
        unique=True,
    )
    op.create_index(op.f("ix_payments_status"), "payments", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_payments_status"), table_name="payments")
    op.drop_index(op.f("ix_payments_provider_idempotency"), table_name="payments")
    op.drop_index(op.f("ix_payments_provider_external"), table_name="payments")
    op.drop_table("payments")
