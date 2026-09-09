"""add request hash to chat turns

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-04

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Task 08 is the first Python flow that writes turns, so normally there are no
# pre-existing rows. Keep the migration safe for an unexpectedly populated
# table nevertheless. This SHA-256-shaped sentinel cannot be mistaken for the
# hash of a known legacy payload: the old schema did not retain message/action.
_UNKNOWN_LEGACY_REQUEST_HASH = "0" * 64


def upgrade() -> None:
    op.add_column(
        "turns",
        sa.Column(
            "request_hash",
            sa.Text(),
            nullable=False,
            server_default=sa.text(f"'{_UNKNOWN_LEGACY_REQUEST_HASH}'"),
        ),
    )
    # The default exists only to backfill rows created before this migration.
    # New claims must always supply the hash computed from their own payload.
    op.alter_column("turns", "request_hash", server_default=None)


def downgrade() -> None:
    op.drop_column("turns", "request_hash")
