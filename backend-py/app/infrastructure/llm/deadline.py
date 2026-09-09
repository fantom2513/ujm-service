from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.infrastructure.llm.errors import LLMError

Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class LLMDeadline:
    """A process-local, monotonic time budget for one logical LLM operation."""

    expires_at: float
    _clock: Clock = field(repr=False, compare=False)

    @classmethod
    def from_timeout_ms(
        cls,
        timeout_ms: int,
        *,
        clock: Clock | None = None,
    ) -> LLMDeadline:
        monotonic_clock = clock or time.monotonic
        return cls(
            expires_at=monotonic_clock() + max(0, timeout_ms) / 1000,
            _clock=monotonic_clock,
        )

    def remaining_seconds(self) -> float:
        return max(0.0, self.expires_at - self._clock())

    def require_remaining(self) -> float:
        remaining = self.remaining_seconds()
        if remaining <= 0:
            raise LLMError("TIMEOUT", "LLM deadline exhausted")
        return remaining
