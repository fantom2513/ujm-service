from __future__ import annotations

import pytest

from app.infrastructure.llm.deadline import LLMDeadline
from app.infrastructure.llm.errors import LLMError


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_deadline_tracks_remaining_time_from_an_absolute_monotonic_expiry():
    clock = FakeClock(now=10.0)
    deadline = LLMDeadline.from_timeout_ms(2_500, clock=clock)

    assert deadline.expires_at == pytest.approx(12.5)
    assert deadline.remaining_seconds() == pytest.approx(2.5)

    clock.advance(1.25)
    assert deadline.remaining_seconds() == pytest.approx(1.25)


def test_deadline_clamps_expired_remaining_time_to_zero():
    clock = FakeClock()
    deadline = LLMDeadline.from_timeout_ms(1_000, clock=clock)

    clock.advance(1.5)

    assert deadline.remaining_seconds() == 0.0


def test_require_remaining_returns_budget_then_normalizes_expiry_to_timeout():
    clock = FakeClock()
    deadline = LLMDeadline.from_timeout_ms(1_000, clock=clock)

    assert deadline.require_remaining() == pytest.approx(1.0)

    clock.advance(1.0)
    with pytest.raises(LLMError) as exc_info:
        deadline.require_remaining()

    assert exc_info.value.code == "TIMEOUT"
    assert str(exc_info.value) == "LLM deadline exhausted"


def test_non_positive_budget_is_expired_immediately():
    clock = FakeClock(now=5.0)

    deadline = LLMDeadline.from_timeout_ms(0, clock=clock)

    assert deadline.expires_at == 5.0
    with pytest.raises(LLMError, match="deadline exhausted"):
        deadline.require_remaining()
