from __future__ import annotations

from app.config import Settings, get_settings
from app.infrastructure.llm.client import VLLMClient
from app.infrastructure.llm.retry import execute_with_retry
from app.services.openai.prompts import build_generate_prompt


def make_client(settings: Settings | None = None) -> VLLMClient:
    settings = settings or get_settings()
    return VLLMClient(
        url=settings.llm_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout_ms=settings.llm_timeout_ms,
        connect_timeout_ms=settings.llm_connect_timeout_ms,
        pool_timeout_ms=settings.llm_pool_timeout_ms,
        temperature=settings.llm_temperature,
        seed=settings.llm_seed,
        response_format_mode=settings.llm_response_format_mode,
        insecure_tls=settings.llm_insecure_tls,
    )


async def generate_diagram(source_text: str, details: str, client: VLLMClient | None = None) -> str:
    client = client or make_client()
    prompt = build_generate_prompt(source_text, details)
    return await execute_with_retry(lambda: client.complete_text(prompt))
