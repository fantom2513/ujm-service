"""Sanity checks that the hand-written ORM models match the Alembic schema.

No database is needed; these tests only inspect SQLAlchemy metadata.
"""

from sqlalchemy.dialects.postgresql import JSONB

from app.infrastructure.db.models import Base, DiagramVersion, Message, Session, Turn


def test_models_map_to_expected_tables():
    assert Session.__tablename__ == "sessions"
    assert DiagramVersion.__tablename__ == "diagram_versions"
    assert Message.__tablename__ == "messages"
    assert Turn.__tablename__ == "turns"
    assert set(Base.metadata.tables) == {
        "sessions",
        "diagram_versions",
        "messages",
        "turns",
    }


def test_sessions_columns_match_migration():
    cols = Session.__table__.columns
    assert set(cols.keys()) == {
        "id",
        "user_id",
        "source_text",
        "additional_details",
        "head_version_id",
        "locked_until",
        "lock_token",
        "created_at",
        "updated_at",
    }
    assert cols["id"].primary_key
    assert cols["source_text"].nullable is False
    assert cols["user_id"].nullable is True
    assert cols["additional_details"].nullable is True
    assert cols["head_version_id"].nullable is True


def test_diagram_versions_columns_and_keys():
    cols = DiagramVersion.__table__.columns
    assert set(cols.keys()) == {
        "id",
        "seq",
        "session_id",
        "mermaid_code",
        "parent_version_id",
        "created_at",
    }
    assert cols["id"].primary_key
    # seq is a distinct DB-generated ordering counter, not the PK.
    assert cols["seq"].primary_key is False
    assert cols["seq"].unique is True
    assert cols["mermaid_code"].nullable is False
    assert cols["parent_version_id"].nullable is True

    fk_targets = {fk.column.table.name for fk in cols["session_id"].foreign_keys}
    assert fk_targets == {"sessions"}
    self_fk = {fk.column.table.name for fk in cols["parent_version_id"].foreign_keys}
    assert self_fk == {"diagram_versions"}


def test_messages_columns_and_keys():
    cols = Message.__table__.columns
    assert set(cols.keys()) == {
        "id",
        "seq",
        "session_id",
        "role",
        "text",
        "created_at",
    }
    assert cols["id"].primary_key
    assert cols["seq"].unique is True
    assert cols["role"].nullable is False
    assert cols["text"].nullable is False

    fk_targets = {fk.column.table.name for fk in cols["session_id"].foreign_keys}
    assert fk_targets == {"sessions"}


def test_turns_columns_and_keys():
    cols = Turn.__table__.columns
    assert set(cols.keys()) == {
        "id",
        "session_id",
        "request_id",
        "request_hash",
        "response_json",
        "claimed_until",
        "claim_token",
        "created_at",
    }
    assert cols["id"].primary_key
    assert cols["request_id"].nullable is False
    assert cols["request_hash"].nullable is False
    assert cols["response_json"].nullable is True
    assert isinstance(cols["response_json"].type, JSONB)
    assert cols["response_json"].type.none_as_null is True
    assert cols["claimed_until"].nullable is True
    assert cols["claimed_until"].type.timezone is True
    assert cols["claim_token"].nullable is True
    assert cols["created_at"].type.timezone is True

    fk_targets = {fk.column.table.name for fk in cols["session_id"].foreign_keys}
    assert fk_targets == {"sessions"}

    unique_column_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in Turn.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("session_id", "request_id") in unique_column_sets
