from __future__ import annotations

from collections import defaultdict, deque

import pytest

from app.config import Settings
from app.domain.mermaid import validate_mermaid
from app.infrastructure.llm.deadline import LLMDeadline
from app.infrastructure.llm.errors import LLMError
from app.services.openai.chat import (
    CHAT_OUTPUT_SCHEMA,
    ChatEditOptions,
    chat_edit,
)


class FakeClient:
    def __init__(
        self,
        *,
        json_result: dict | None = None,
        text_result: str | None = None,
        error: LLMError | None = None,
        usage: dict[str, int] | None = None,
    ):
        self.json_result = json_result
        self.text_result = text_result
        self.error = error
        self.last_usage = usage
        self.json_calls: list[tuple[str, dict, str]] = []
        self.text_calls: list[str] = []

    async def complete_json(self, prompt: str, schema: dict, schema_name: str) -> dict:
        self.json_calls.append((prompt, schema, schema_name))
        if self.error:
            raise self.error
        assert self.json_result is not None
        return self.json_result

    async def complete_text(self, prompt: str) -> str:
        self.text_calls.append(prompt)
        if self.error:
            raise self.error
        assert self.text_result is not None
        return self.text_result


class ClientFactory:
    def __init__(self):
        self.clients: defaultdict[str, deque[FakeClient]] = defaultdict(deque)
        self.modes: list[str] = []
        self.deadlines: list[LLMDeadline] = []

    def add(self, mode: str, client: FakeClient) -> FakeClient:
        self.clients[mode].append(client)
        return client

    def __call__(self, mode: str, deadline: LLMDeadline) -> FakeClient:
        self.modes.append(mode)
        self.deadlines.append(deadline)
        assert self.clients[mode], f"No fake client configured for mode {mode!r}"
        return self.clients[mode].popleft()


def _options() -> ChatEditOptions:
    return ChatEditOptions(
        source_text="SERVER SPEC",
        additional_details="SERVER DETAILS",
        current_mermaid="flowchart LR\nA-->B",
        previous_mermaid=None,
        history=[("user", "add B"), ("assistant", "done")],
        action_type="FREEFORM",
        user_message="add C",
    )


def _settings(mode: str = "json_schema") -> Settings:
    return Settings(llm_response_format_mode=mode)


def _deadline() -> LLMDeadline:
    return LLMDeadline.from_timeout_ms(120_000)


async def test_chat_edit_returns_structured_result_and_primary_usage():
    factory = ClientFactory()
    client = factory.add(
        "json_schema",
        FakeClient(
            json_result={"mermaid": "  flowchart LR\nA-->B\nB-->C  ", "message": "  Added C.  "},
            usage={"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        ),
    )

    result = await chat_edit(
        _options(),
        _settings(),
        factory,
        deadline=_deadline(),
    )

    assert result.mermaid_code == "flowchart LR\nA-->B\nB-->C"
    assert result.message == "Added C."
    assert result.usage == {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}
    assert factory.modes == ["json_schema"]
    assert len(client.json_calls) == 1
    prompt, schema, schema_name = client.json_calls[0]
    assert "<SOURCE_SPECIFICATION>\nSERVER SPEC\n</SOURCE_SPECIFICATION>" in prompt
    assert "<CURRENT_MERMAID>\nflowchart LR\nA-->B\n</CURRENT_MERMAID>" in prompt
    assert "<USER_MESSAGE>\nadd C\n</USER_MESSAGE>" in prompt
    assert schema == CHAT_OUTPUT_SCHEMA
    assert schema_name == "ChatOutput"


async def test_chat_edit_falls_back_through_response_format_modes():
    factory = ClientFactory()
    factory.add(
        "json_schema",
        FakeClient(error=LLMError("STRUCTURED_OUTPUT_UNSUPPORTED", "no schema support")),
    )
    factory.add(
        "json_object",
        FakeClient(error=LLMError("INVALID_JSON", "not valid JSON")),
    )
    factory.add(
        "none",
        FakeClient(json_result={"mermaid": "flowchart TB\nA-->B", "message": "Done"}),
    )

    result = await chat_edit(
        _options(),
        _settings(),
        factory,
        deadline=_deadline(),
    )

    assert result.mermaid_code == "flowchart TB\nA-->B"
    assert factory.modes == ["json_schema", "json_object", "none"]
    assert len({id(deadline) for deadline in factory.deadlines}) == 1


async def test_chat_edit_repairs_invalid_mermaid_and_keeps_primary_usage():
    factory = ClientFactory()
    primary = factory.add(
        "json_schema",
        FakeClient(
            json_result={"mermaid": "not a flowchart", "message": "Fixed it"},
            usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        ),
    )
    repair = factory.add(
        "json_schema",
        FakeClient(
            text_result="flowchart LR\nA-->B",
            usage={"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11},
        ),
    )

    result = await chat_edit(
        _options(),
        _settings(),
        factory,
        deadline=_deadline(),
    )

    assert result.mermaid_code == "flowchart LR\nA-->B"
    assert result.message == "Fixed it"
    assert result.usage == primary.last_usage
    assert result.usage != repair.last_usage
    assert factory.modes == ["json_schema", "json_schema"]
    assert len({id(deadline) for deadline in factory.deadlines}) == 1
    assert len(repair.text_calls) == 1
    assert "<CANDIDATE_MERMAID>\nnot a flowchart\n</CANDIDATE_MERMAID>" in repair.text_calls[0]
    assert "Mermaid must start with 'flowchart'" in repair.text_calls[0]


async def test_chat_edit_raises_schema_mismatch_when_repair_is_still_invalid():
    factory = ClientFactory()
    factory.add(
        "json_schema",
        FakeClient(json_result={"mermaid": "bad first result", "message": "Done"}),
    )
    factory.add("json_schema", FakeClient(text_result="bad repair result"))

    with pytest.raises(LLMError) as raised:
        await chat_edit(
            _options(),
            _settings(),
            factory,
            deadline=_deadline(),
        )

    assert raised.value.code == "SCHEMA_MISMATCH"
    assert str(raised.value) == "Generated Mermaid failed validation after repair"


async def test_chat_edit_preserves_timeout_from_repair():
    factory = ClientFactory()
    factory.add(
        "json_schema",
        FakeClient(json_result={"mermaid": "bad first result", "message": "Done"}),
    )
    factory.add(
        "json_schema",
        FakeClient(error=LLMError("TIMEOUT", "repair deadline exhausted")),
    )

    with pytest.raises(LLMError) as raised:
        await chat_edit(
            _options(),
            _settings(),
            factory,
            deadline=_deadline(),
        )

    assert raised.value.code == "TIMEOUT"
    assert str(raised.value) == "repair deadline exhausted"
    assert len({id(deadline) for deadline in factory.deadlines}) == 1


async def test_chat_edit_does_not_start_repair_after_validation_expires_deadline(
    monkeypatch,
):
    now = [0.0]
    deadline = LLMDeadline.from_timeout_ms(1_000, clock=lambda: now[0])
    factory = ClientFactory()
    factory.add(
        "json_schema",
        FakeClient(json_result={"mermaid": "bad first result", "message": "Done"}),
    )

    def expiring_validation(mermaid_code: str):
        result = validate_mermaid(mermaid_code)
        now[0] = 1.0
        return result

    monkeypatch.setattr(
        "app.services.openai.chat.validate_mermaid",
        expiring_validation,
    )

    with pytest.raises(LLMError) as raised:
        await chat_edit(
            _options(),
            _settings(),
            factory,
            deadline=deadline,
        )

    assert raised.value.code == "TIMEOUT"
    assert factory.modes == ["json_schema"]
