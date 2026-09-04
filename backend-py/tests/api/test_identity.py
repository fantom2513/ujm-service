import pytest

from app.api.deps import get_current_identity
from app.config import Settings
from app.domain.identity import Principal


@pytest.mark.parametrize("header", [None, "alice", "  Alice  "])
def test_anonymous_mode_ignores_user_id_header(header: str | None) -> None:
    principal = get_current_identity(
        settings=Settings(_env_file=None, identity_mode="anonymous"),
        x_user_id=header,
    )

    assert principal == Principal.anonymous()


def test_trusted_header_mode_uses_trimmed_nonempty_subject() -> None:
    principal = get_current_identity(
        settings=Settings(_env_file=None, identity_mode="trusted_header"),
        x_user_id="  Alice  ",
    )

    assert principal == Principal.authenticated("Alice")


@pytest.mark.parametrize("header", [None, "", "   ", "\t\r\n"])
def test_trusted_header_mode_treats_missing_or_blank_header_as_anonymous(
    header: str | None,
) -> None:
    principal = get_current_identity(
        settings=Settings(_env_file=None, identity_mode="trusted_header"),
        x_user_id=header,
    )

    assert principal == Principal.anonymous()
