"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # sessions.head_version_id -> diagram_versions.id and
    # diagram_versions.session_id -> sessions.id form a cycle. Create
    # sessions first without the head_version_id FK, then diagram_versions
    # (which can reference sessions immediately), then add the deferred FK
    # via a separate ALTER (use_alter pattern) once both tables exist.
    op.create_table(
        "sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("additional_details", sa.Text(), nullable=True),
        sa.Column("head_version_id", sa.BigInteger(), nullable=True),
        sa.Column("locked_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("lock_token", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "diagram_versions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("seq", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column(
            "session_id",
            sa.Text(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mermaid_code", sa.Text(), nullable=True),
        sa.Column(
            "parent_version_id",
            sa.BigInteger(),
            sa.ForeignKey("diagram_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_diagram_versions_session_id", "diagram_versions", ["session_id"])

    op.create_foreign_key(
        "fk_sessions_head_version_id",
        source_table="sessions",
        referent_table="diagram_versions",
        local_cols=["head_version_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("seq", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column(
            "session_id",
            sa.Text(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])

    op.create_table(
        "turns",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Text(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("response_json", postgresql.JSONB(), nullable=True),
        sa.Column("claimed_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("claim_token", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("session_id", "request_id", name="uq_turns_session_id_request_id"),
    )
    op.create_index("ix_turns_session_id", "turns", ["session_id"])


def downgrade() -> None:
    # Drop the cyclic FK first — otherwise Postgres refuses to drop
    # diagram_versions while sessions.head_version_id still references it.
    op.drop_constraint("fk_sessions_head_version_id", "sessions", type_="foreignkey")

    op.drop_table("turns")
    op.drop_table("messages")
    op.drop_table("diagram_versions")
    op.drop_table("sessions")
