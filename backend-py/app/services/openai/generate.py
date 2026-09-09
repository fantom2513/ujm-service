from __future__ import annotations

from collections.abc import Callable

from app.config import Settings, get_settings
from app.infrastructure.llm.client import VLLMClient
from app.infrastructure.llm.deadline import LLMDeadline
from app.infrastructure.llm.retry import execute_with_retry
from app.services.openai.prompts import build_generate_prompt

ClientFactory = Callable[[LLMDeadline], VLLMClient]


def make_client(deadline: LLMDeadline, settings: Settings | None = None) -> VLLMClient:
    settings = settings or get_settings()
    return VLLMClient(
        url=settings.llm_url,
        model=settings.llm_model,
        deadline=deadline,
        api_key=settings.llm_api_key,
        connect_timeout_ms=settings.llm_connect_timeout_ms,
        pool_timeout_ms=settings.llm_pool_timeout_ms,
        temperature=settings.llm_temperature,
        seed=settings.llm_seed,
        response_format_mode=settings.llm_response_format_mode,
        insecure_tls=settings.llm_insecure_tls,
    )


async def generate_diagram(
    source_text: str,
    details: str,
    client: VLLMClient | None = None,
    *,
    settings: Settings | None = None,
    client_factory: ClientFactory | None = None,
) -> str:
    if client is not None:
        deadline = client.deadline
    else:
        settings = settings or get_settings()
        deadline = LLMDeadline.from_timeout_ms(settings.llm_deadline_ms)
        factory = client_factory or (
            lambda shared_deadline: make_client(shared_deadline, settings)
        )
        client = factory(deadline)
    prompt = build_generate_prompt(source_text, details)
    return await execute_with_retry(
        lambda: client.complete_text(prompt),
        deadline=deadline,
    )
