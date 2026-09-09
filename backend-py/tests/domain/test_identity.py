import pytest

from app.domain.identity import Principal


def test_anonymous_principal_has_no_subject() -> None:
    principal = Principal.anonymous()

    assert principal.subject is None
    assert principal.is_anonymous is True
    assert principal.is_authenticated is False


def test_authenticated_principal_preserves_opaque_case_sensitive_subject() -> None:
    principal = Principal.authenticated("Alice")

    assert principal.subject == "Alice"
    assert principal.is_anonymous is False
    assert principal.is_authenticated is True
    assert principal != Principal.authenticated("alice")


@pytest.mark.parametrize("subject", ["", " ", "\t\r\n"])
def test_authenticated_principal_rejects_blank_subject(subject: str) -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        Principal.authenticated(subject)


def test_direct_construction_cannot_bypass_subject_validation() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        Principal(subject="")


def test_authenticated_constructor_rejects_none() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        Principal.authenticated(None)  # type: ignore[arg-type]


def test_principal_is_immutable() -> None:
    principal = Principal.authenticated("alice")

    with pytest.raises(AttributeError):
        principal.subject = "mallory"  # type: ignore[misc]
