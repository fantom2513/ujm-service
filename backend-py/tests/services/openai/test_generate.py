import pytest

from app.infrastructure.llm.client import VLLMClient
from app.services.openai.generate import generate_diagram


def _llm_response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


async def test_generate_diagram_builds_prompt_and_returns_mermaid(mock_llm_server):
    url = mock_llm_server(_llm_response("flowchart LR\nA --> B"))
    client = VLLMClient(url=url, model="test", response_format_mode="none")
    result = await generate_diagram("Some technical spec", "extra details", client)
    assert result.startswith("flowchart LR")


async def test_generate_diagram_propagates_llm_error_on_repeated_failure(mock_llm_server):
    url = mock_llm_server({"error": "boom"}, status_code=500)
    client = VLLMClient(url=url, model="test", response_format_mode="none")
    with pytest.raises(Exception):
        await generate_diagram("spec", "", client)
