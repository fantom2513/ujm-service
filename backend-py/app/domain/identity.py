from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    """A normalized caller identity independent of its transport or provider."""

    subject: str | None

    def __post_init__(self) -> None:
        if self.subject is not None and not isinstance(self.subject, str):
            raise TypeError("Principal subject must be a string or None")
        if self.subject is not None and not self.subject.strip():
            raise ValueError("Authenticated principal subject must not be blank")

    @classmethod
    def anonymous(cls) -> Principal:
        return cls(subject=None)

    @classmethod
    def authenticated(cls, subject: str) -> Principal:
        if not isinstance(subject, str):
            raise TypeError("Authenticated principal subject must be a string")
        return cls(subject=subject)

    @property
    def is_anonymous(self) -> bool:
        return self.subject is None

    @property
    def is_authenticated(self) -> bool:
        return self.subject is not None
