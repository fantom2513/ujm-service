import pytest

from app.infrastructure.llm.deadline import LLMDeadline
from app.infrastructure.llm.errors import LLMError
from app.infrastructure.llm.retry import complete_json_with_fallback, execute_with_retry


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def test_execute_with_retry_returns_value_on_first_success():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        return 42

    result = await execute_with_retry(fn)
    assert result == 42
    assert calls == 1


async def test_execute_with_retry_does_not_retry_timeout():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        raise LLMError("TIMEOUT", "timed out")

    with pytest.raises(LLMError) as exc_info:
        await execute_with_retry(fn, max_attempts=3, base_delay_ms=0, max_delay_ms=0)
    assert calls == 1
    assert exc_info.value.code == "TIMEOUT"


async def test_execute_with_retry_retries_on_network_error():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise LLMError("NETWORK_ERROR", "connection reset")
        return "ok"

    result = await execute_with_retry(fn, max_attempts=3, base_delay_ms=0, max_delay_ms=0)
    assert result == "ok"
    assert calls == 3


async def test_execute_with_retry_does_not_retry_schema_mismatch():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        raise LLMError("SCHEMA_MISMATCH", "bad schema")

    with pytest.raises(LLMError) as exc_info:
        await execute_with_retry(fn, max_attempts=3, base_delay_ms=0, max_delay_ms=0)
    assert calls == 1
    assert exc_info.value.code == "SCHEMA_MISMATCH"


async def test_execute_with_retry_raises_last_error_after_exhausting():
    async def fn():
        raise LLMError("HTTP_ERROR", "bad")

    with pytest.raises(LLMError) as exc_info:
        await execute_with_retry(fn, max_attempts=2, base_delay_ms=0, max_delay_ms=0)
    assert exc_info.value.code == "HTTP_ERROR"


class _CustomError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


async def test_execute_with_retry_supports_custom_error_type():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        if calls < 2:
            raise _CustomError("TRANSIENT")
        return "ok"

    result = await execute_with_retry(
        fn,
        max_attempts=3,
        base_delay_ms=0,
        max_delay_ms=0,
        error_type=_CustomError,
        no_retry_codes={"PERMANENT"},
    )
    assert result == "ok"
    assert calls == 2


async def test_execute_with_retry_custom_no_retry_codes_stop_immediately():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        raise _CustomError("PERMANENT")

    with pytest.raises(_CustomError):
        await execute_with_retry(
            fn,
            max_attempts=3,
            base_delay_ms=0,
            max_delay_ms=0,
            error_type=_CustomError,
            no_retry_codes={"PERMANENT"},
        )
    assert calls == 1


async def test_retry_and_backoff_share_deadline_and_do_not_start_next_attempt():
    clock = FakeClock()
    deadline = LLMDeadline.from_timeout_ms(2_000, clock=clock)
    calls = 0
    sleeps: list[float] = []

    async def fn():
        nonlocal calls
        calls += 1
        clock.advance(1.5)
        raise LLMError("NETWORK_ERROR", "connection reset")

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)

    with pytest.raises(LLMError) as exc_info:
        await execute_with_retry(
            fn,
            max_attempts=3,
            base_delay_ms=1_000,
            max_delay_ms=1_000,
            deadline=deadline,
            sleep=fake_sleep,
        )

    assert exc_info.value.code == "TIMEOUT"
    assert calls == 1
    assert sleeps == [pytest.approx(0.5)]


async def test_success_returned_after_deadline_is_normalized_to_timeout():
    clock = FakeClock()
    deadline = LLMDeadline.from_timeout_ms(1_000, clock=clock)

    async def fn():
        clock.advance(1.0)
        return "too late"

    with pytest.raises(LLMError) as exc_info:
        await execute_with_retry(fn, deadline=deadline)

    assert exc_info.value.code == "TIMEOUT"


async def test_complete_json_with_fallback_falls_back_on_structured_output_unsupported():
    modes: list[str] = []

    class FakeClient:
        def __init__(self, mode: str):
            self.mode = mode

        async def complete_json(self, *_args):
            if self.mode == "json_schema":
                raise LLMError("STRUCTURED_OUTPUT_UNSUPPORTED", "no")
            return {"ok": True}

    deadline = LLMDeadline.from_timeout_ms(120_000)

    def make_client(mode: str, shared_deadline: LLMDeadline):
        assert shared_deadline is deadline
        modes.append(mode)
        return FakeClient(mode)

    result = await complete_json_with_fallback(
        make_client,
        "json_schema",
        lambda client: client.complete_json("", {}, ""),
        deadline,
        max_attempts_first=2,
        max_attempts_rest=1,
    )
    assert result == {"ok": True}
    assert "json_schema" in modes
    assert "json_object" in modes


async def test_complete_json_with_fallback_does_not_fall_back_on_http_error():
    modes: list[str] = []

    class FakeClient:
        async def complete_json(self, *_args):
            raise LLMError("HTTP_ERROR", "bad")

    deadline = LLMDeadline.from_timeout_ms(120_000)

    def make_client(mode: str, shared_deadline: LLMDeadline):
        assert shared_deadline is deadline
        modes.append(mode)
        return FakeClient()

    with pytest.raises(LLMError) as exc_info:
        await complete_json_with_fallback(
            make_client,
            "json_schema",
            lambda client: client.complete_json("", {}, ""),
            deadline,
            max_attempts_first=1,
            max_attempts_rest=1,
        )
    assert exc_info.value.code == "HTTP_ERROR"
    assert len(modes) == 1


async def test_fallback_does_not_create_next_client_after_deadline_expiry():
    clock = FakeClock()
    deadline = LLMDeadline.from_timeout_ms(1_000, clock=clock)
    modes: list[str] = []

    class FakeClient:
        async def complete_json(self, *_args):
            clock.advance(1.0)
            raise LLMError("STRUCTURED_OUTPUT_UNSUPPORTED", "no")

    def make_client(mode: str, shared_deadline: LLMDeadline):
        assert shared_deadline is deadline
        modes.append(mode)
        return FakeClient()

    with pytest.raises(LLMError) as exc_info:
        await complete_json_with_fallback(
            make_client,
            "json_schema",
            lambda client: client.complete_json("", {}, ""),
            deadline,
            max_attempts_first=1,
            max_attempts_rest=1,
        )

    assert exc_info.value.code == "TIMEOUT"
    assert modes == ["json_schema"]


async def test_fallback_client_receives_only_original_deadline_remainder():
    clock = FakeClock()
    deadline = LLMDeadline.from_timeout_ms(1_000, clock=clock)
    remaining_at_creation: list[float] = []

    class FakeClient:
        def __init__(self, mode: str) -> None:
            self.mode = mode

        async def complete_json(self, *_args):
            if self.mode == "json_schema":
                clock.advance(0.4)
                raise LLMError("STRUCTURED_OUTPUT_UNSUPPORTED", "no")
            return {"ok": True}

    def make_client(mode: str, shared_deadline: LLMDeadline):
        assert shared_deadline is deadline
        remaining_at_creation.append(shared_deadline.remaining_seconds())
        return FakeClient(mode)

    result = await complete_json_with_fallback(
        make_client,
        "json_schema",
        lambda client: client.complete_json("", {}, ""),
        deadline,
        max_attempts_first=1,
        max_attempts_rest=1,
    )

    assert result == {"ok": True}
    assert remaining_at_creation == [pytest.approx(1.0), pytest.approx(0.6)]
