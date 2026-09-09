from app.services.openai.prompts import (
    _EDIT_SYSTEM,
    _REPAIR_SYSTEM,
    build_chat_prompt,
    build_repair_prompt,
)


def _chat_prompt(**overrides) -> str:
    kwargs = dict(
        source_text="SPEC",
        additional_details="DETAILS",
        current_mermaid="flowchart LR\nA-->B",
        previous_mermaid=None,
        history=[],
        action_type="FREEFORM",
        user_message="MESSAGE",
        attachment_context="",
    )
    kwargs.update(overrides)
    return build_chat_prompt(**kwargs)


def test_chat_prompt_starts_with_edit_system_and_carries_server_fields():
    result = _chat_prompt()
    assert result.startswith(_EDIT_SYSTEM)
    assert "<SOURCE_SPECIFICATION>\nSPEC\n</SOURCE_SPECIFICATION>" in result
    assert "<CURRENT_MERMAID>\nflowchart LR\nA-->B\n</CURRENT_MERMAID>" in result
    assert "<ACTION_TYPE>\nFREEFORM\n</ACTION_TYPE>" in result
    assert "<USER_MESSAGE>\nMESSAGE\n</USER_MESSAGE>" in result


def test_chat_prompt_optional_blocks_collapse_to_empty_tags():
    result = _chat_prompt(previous_mermaid=None, history=[], attachment_context="")
    assert "<PREVIOUS_MERMAID></PREVIOUS_MERMAID>" in result
    assert "<CHAT_HISTORY></CHAT_HISTORY>" in result
    assert "<ATTACHMENT_CONTEXT></ATTACHMENT_CONTEXT>" in result


def test_chat_prompt_additional_details_block_is_never_collapsed():
    # Unlike build_generate_prompt, the chat prompt always emits the
    # multi-line ADDITIONAL_DETAILS block even when empty (TS parity).
    result = _chat_prompt(additional_details="")
    assert "<ADDITIONAL_DETAILS>\n\n</ADDITIONAL_DETAILS>" in result
    assert "<ADDITIONAL_DETAILS></ADDITIONAL_DETAILS>" not in result


def test_chat_prompt_previous_mermaid_block_when_present():
    result = _chat_prompt(previous_mermaid="flowchart TB\nX-->Y")
    assert "<PREVIOUS_MERMAID>\nflowchart TB\nX-->Y\n</PREVIOUS_MERMAID>" in result


def test_chat_prompt_history_is_labelled_and_ordered():
    result = _chat_prompt(
        history=[("user", "add a check"), ("assistant", "done"), ("user", "undo that")]
    )
    assert (
        "<CHAT_HISTORY>\n"
        "Пользователь: add a check\n"
        "Ассистент: done\n"
        "Пользователь: undo that\n"
        "</CHAT_HISTORY>"
    ) in result


def test_chat_prompt_sanitizes_prose_but_not_mermaid_bodies():
    result = _chat_prompt(
        source_text="spec with ``` fence",
        user_message="msg with ``` fence",
        current_mermaid="flowchart LR\n%% ``` stays\nA-->B",
        previous_mermaid="flowchart TB\n%% ``` stays\nX-->Y",
        history=[("user", "hist ``` fence")],
    )
    # The system prompt itself documents tags like <SOURCE_SPECIFICATION>, so
    # look only at the body we appended after it.
    assert result.startswith(_EDIT_SYSTEM)
    body = result[len(_EDIT_SYSTEM):]

    def block(name: str) -> str:
        return body.split(f"<{name}>\n", 1)[1].split(f"\n</{name}>", 1)[0]

    assert "```" not in block("SOURCE_SPECIFICATION") and "'''" in block("SOURCE_SPECIFICATION")
    assert "```" not in block("USER_MESSAGE") and "'''" in block("USER_MESSAGE")
    assert "```" not in block("CHAT_HISTORY") and "'''" in block("CHAT_HISTORY")
    # Mermaid bodies pass through verbatim.
    assert "<CURRENT_MERMAID>\nflowchart LR\n%% ``` stays\nA-->B\n</CURRENT_MERMAID>" in body
    assert "<PREVIOUS_MERMAID>\nflowchart TB\n%% ``` stays\nX-->Y\n</PREVIOUS_MERMAID>" in body


def test_repair_prompt_structure():
    result = build_repair_prompt(
        "flowchart LR\nA-->B", "Parse error at line 2", ["missing node", "bad arrow"]
    )
    assert result.startswith(_REPAIR_SYSTEM)
    assert "<CANDIDATE_MERMAID>\nflowchart LR\nA-->B\n</CANDIDATE_MERMAID>" in result
    assert "<PARSER_ERROR>\nParse error at line 2\n</PARSER_ERROR>" in result
    assert "<VALIDATION_ISSUES>\nmissing node\nbad arrow\n</VALIDATION_ISSUES>" in result


def test_repair_prompt_empty_issues():
    result = build_repair_prompt("flowchart LR\nA-->B", "boom", [])
    assert "<VALIDATION_ISSUES>\n\n</VALIDATION_ISSUES>" in result
