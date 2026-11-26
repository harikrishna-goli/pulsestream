"""add expires_at to idempotency_records

Revision ID: d3f1a2b4c5e6
Revises: ca20bac7c670
Create Date: 2026-11-26

"""
from alembic import op
import sqlalchemy as sa
import datetime

revision = 'd3f1a2b4c5e6'
down_revision = 'ca20bac7c670'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add expires_at column — existing rows get a 24hr window from now
    op.add_column(
        'idempotency_records',
        sa.Column('expires_at', sa.DateTime(), nullable=True)
    )
    # Backfill existing rows: set expires_at = created_at + 24 hours
    op.execute(
        "UPDATE idempotency_records SET expires_at = created_at + INTERVAL '24 hours' WHERE expires_at IS NULL"
    )
    # Now make it non-nullable
    op.alter_column('idempotency_records', 'expires_at', nullable=False)


def downgrade() -> None:
    op.drop_column('idempotency_records', 'expires_at')
