from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.config import Settings, get_settings
from app.domain.mermaid import validate_mermaid
from app.infrastructure.llm.client import VLLMClient
from app.infrastructure.llm.errors import LLMError
from app.infrastructure.llm.retry import complete_json_with_fallback
from app.services.openai.prompts import build_chat_prompt, build_repair_prompt


CHAT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "mermaid": {"type": "string"},
        "message": {"type": "string"},
    },
    "required": ["mermaid", "message"],
    "additionalProperties": False,
}


@dataclass
class ChatEditOptions:
    source_text: str
    additional_details: str
    current_mermaid: str
    previous_mermaid: str | None
    history: Sequence[tuple[str, str]]
    action_type: str
    user_message: str
    attachment_context: str = ""


@dataclass
class ChatEditResult:
    mermaid_code: str
    message: str
    usage: dict[str, int] | None


ClientFactory = Callable[[str], VLLMClient]


def _make_client(settings: Settings, response_format_mode: str) -> VLLMClient:
    return VLLMClient(
        url=settings.llm_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout_ms=settings.llm_timeout_ms,
        connect_timeout_ms=settings.llm_connect_timeout_ms,
        pool_timeout_ms=settings.llm_pool_timeout_ms,
        temperature=settings.llm_temperature,
        seed=settings.llm_seed,
        response_format_mode=response_format_mode,
        insecure_tls=settings.llm_insecure_tls,
    )


async def chat_edit(
    options: ChatEditOptions,
    settings: Settings | None = None,
    make_client: ClientFactory | None = None,
) -> ChatEditResult:
    settings = settings or get_settings()
    client_factory = make_client or (lambda mode: _make_client(settings, mode))
    prompt = build_chat_prompt(
        source_text=options.source_text,
        additional_details=options.additional_details,
        current_mermaid=options.current_mermaid,
        previous_mermaid=options.previous_mermaid,
        history=options.history,
        action_type=options.action_type,
        user_message=options.user_message,
        attachment_context=options.attachment_context,
    )

    captured_usage: dict[str, int] | None = None

    async def complete(client: VLLMClient) -> dict:
        nonlocal captured_usage
        result = await client.complete_json(prompt, CHAT_OUTPUT_SCHEMA, "ChatOutput")
        captured_usage = client.last_usage
        return result

    raw = await complete_json_with_fallback(
        client_factory,
        settings.llm_response_format_mode,
        complete,
    )
    mermaid_value = raw.get("mermaid")
    message_value = raw.get("message")
    mermaid_code = str(mermaid_value if mermaid_value is not None else "").strip()
    message = str(message_value if message_value is not None else "").strip()

    validation = validate_mermaid(mermaid_code)
    if not validation.ok:
        repair_client = client_factory(settings.llm_response_format_mode)
        try:
            repaired = await repair_client.complete_text(
                build_repair_prompt(mermaid_code, validation.reason or "", [])
            )
            revalidation = validate_mermaid(repaired)
            if not revalidation.ok:
                raise ValueError(f"Repair failed: {revalidation.reason}")
            mermaid_code = repaired
        except Exception as err:
            raise LLMError(
                "SCHEMA_MISMATCH",
                "Generated Mermaid failed validation after repair",
                err,
            ) from err

    # Matches the TS path: repair-call usage is not merged into primary usage.
    return ChatEditResult(mermaid_code=mermaid_code, message=message, usage=captured_usage)
