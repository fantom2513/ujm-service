"""Add generate request lookup and wrap completed legacy turns.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generate_requests",
        sa.Column("request_id", sa.Text(), primary_key=True),
        sa.Column(
            "session_id", sa.Text(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
        ),
    )
    op.execute(
        "UPDATE turns SET response_json = jsonb_build_object('ok', true, 'result', response_json) "
        "WHERE response_json IS NOT NULL AND NOT (response_json ? 'ok')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM turns WHERE response_json->>'ok' = 'false'")
    op.execute(
        "UPDATE turns SET response_json = response_json->'result' "
        "WHERE response_json->>'ok' = 'true'"
    )
    op.drop_table("generate_requests")
