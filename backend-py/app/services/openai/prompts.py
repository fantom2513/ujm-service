from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

# Reuses the same authored .prompt.txt files as the TS backend
# (backend/src/prompts/) instead of duplicating their content — avoids the
# two backends' generation behavior drifting apart during the Phase 0-4
# parallel-build period. Relocate to a shared location at the Phase 5
# cutover once backend/ (TS) is retired.
_PROMPTS_DIR = Path(__file__).resolve().parents[4] / "backend" / "src" / "prompts"


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


_GENERATE_SYSTEM = _load_prompt("generateMermaid.prompt.txt")
_EDIT_SYSTEM = _load_prompt("editMermaid.prompt.txt")
_REPAIR_SYSTEM = _load_prompt("repairMermaid.prompt.txt")


def _sanitize(text: str) -> str:
    return text.strip()[:60_000].replace("```", "'''")


def build_generate_prompt(source_text: str, additional_details: str) -> str:
    safe_source = _sanitize(source_text)
    safe_details = _sanitize(additional_details)
    details_block = (
        f"<ADDITIONAL_DETAILS>\n{safe_details}\n</ADDITIONAL_DETAILS>"
        if safe_details
        else "<ADDITIONAL_DETAILS></ADDITIONAL_DETAILS>"
    )
    return (
        f"{_GENERATE_SYSTEM}\n\n"
        f"<SOURCE_SPECIFICATION>\n{safe_source}\n</SOURCE_SPECIFICATION>\n\n"
        f"{details_block}"
    )


def _format_history(history: Sequence[tuple[str, str]]) -> str:
    # Same wording as TS buildChatPrompt.formatHistory: "Пользователь"/
    # "Ассистент" labels, message text sanitized, one entry per line.
    return "\n".join(
        f"{'Пользователь' if role == 'user' else 'Ассистент'}: {_sanitize(text)}"
        for role, text in history
    )


def build_chat_prompt(
    *,
    source_text: str,
    additional_details: str,
    current_mermaid: str,
    previous_mermaid: str | None,
    history: Sequence[tuple[str, str]],
    action_type: str,
    user_message: str,
    attachment_context: str = "",
) -> str:
    # Mirrors TS buildChatPrompt exactly, including which fields are
    # sanitized (source/details/user_message/history text) and which are
    # passed through raw (the Mermaid bodies). All three optional blocks
    # collapse to an empty `<TAG></TAG>` when their input is falsy, so the
    # single-version / no-history / no-attachment cases still emit a stable,
    # explicit shape for the model.
    prev_block = (
        f"<PREVIOUS_MERMAID>\n{previous_mermaid}\n</PREVIOUS_MERMAID>"
        if previous_mermaid
        else "<PREVIOUS_MERMAID></PREVIOUS_MERMAID>"
    )
    attach_block = (
        f"<ATTACHMENT_CONTEXT>\n{_sanitize(attachment_context)}\n</ATTACHMENT_CONTEXT>"
        if attachment_context
        else "<ATTACHMENT_CONTEXT></ATTACHMENT_CONTEXT>"
    )
    history_block = (
        f"<CHAT_HISTORY>\n{_format_history(history)}\n</CHAT_HISTORY>"
        if history
        else "<CHAT_HISTORY></CHAT_HISTORY>"
    )
    return (
        f"{_EDIT_SYSTEM}\n\n"
        f"<SOURCE_SPECIFICATION>\n{_sanitize(source_text)}\n</SOURCE_SPECIFICATION>\n\n"
        f"<ADDITIONAL_DETAILS>\n{_sanitize(additional_details)}\n</ADDITIONAL_DETAILS>\n\n"
        f"<CURRENT_MERMAID>\n{current_mermaid}\n</CURRENT_MERMAID>\n\n"
        f"{prev_block}\n\n"
        f"{history_block}\n\n"
        f"<ACTION_TYPE>\n{action_type}\n</ACTION_TYPE>\n\n"
        f"<USER_MESSAGE>\n{_sanitize(user_message)}\n</USER_MESSAGE>\n\n"
        f"{attach_block}"
    )


def build_repair_prompt(
    candidate_mermaid: str,
    parser_error: str,
    validation_issues: list[str],
) -> str:
    issues = "\n".join(validation_issues)
    return (
        f"{_REPAIR_SYSTEM}\n\n"
        f"<CANDIDATE_MERMAID>\n{candidate_mermaid}\n</CANDIDATE_MERMAID>\n\n"
        f"<PARSER_ERROR>\n{parser_error}\n</PARSER_ERROR>\n\n"
        f"<VALIDATION_ISSUES>\n{issues}\n</VALIDATION_ISSUES>"
    )
