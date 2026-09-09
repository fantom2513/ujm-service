import pytest

from app.config import Settings
from app.infrastructure.llm.client import VLLMClient
from app.infrastructure.llm.deadline import LLMDeadline
from app.services.openai.generate import generate_diagram


def _llm_response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


async def test_generate_diagram_builds_prompt_and_returns_mermaid(mock_llm_server):
    url = mock_llm_server(_llm_response("flowchart LR\nA --> B"))
    client = VLLMClient(
        url=url,
        model="test",
        deadline=LLMDeadline.from_timeout_ms(120_000),
        response_format_mode="none",
    )
    result = await generate_diagram("Some technical spec", "extra details", client)
    assert result.startswith("flowchart LR")


async def test_generate_diagram_propagates_llm_error_on_repeated_failure(mock_llm_server):
    url = mock_llm_server({"error": "boom"}, status_code=500)
    client = VLLMClient(
        url=url,
        model="test",
        deadline=LLMDeadline.from_timeout_ms(120_000),
        response_format_mode="none",
    )
    with pytest.raises(Exception):
        await generate_diagram("spec", "", client)


async def test_generate_diagram_creates_one_deadline_for_client_and_retry():
    captured_deadlines: list[LLMDeadline] = []

    class FakeClient:
        def __init__(self, deadline: LLMDeadline) -> None:
            self.deadline = deadline

        async def complete_text(self, _prompt: str) -> str:
            captured_deadlines.append(self.deadline)
            return "flowchart LR\nA --> B"

    def client_factory(deadline: LLMDeadline):
        captured_deadlines.append(deadline)
        return FakeClient(deadline)

    result = await generate_diagram(
        "spec",
        "details",
        settings=Settings(llm_deadline_ms=5_000),
        client_factory=client_factory,
    )

    assert result == "flowchart LR\nA --> B"
    assert len(captured_deadlines) == 2
    assert captured_deadlines[0] is captured_deadlines[1]
