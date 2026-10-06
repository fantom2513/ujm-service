import pytest

from app.domain.mermaid import validate_mermaid
from app.domain.mermaid_syntax import MermaidParserUnavailable, validate_mermaid_syntax
from app.infrastructure.llm.deadline import LLMDeadline


def test_accepts_flowchart_lr():
    assert validate_mermaid("flowchart LR\nA-->B").ok is True


def test_accepts_flowchart_tb():
    assert validate_mermaid("flowchart TB\nA-->B").ok is True


def test_accepts_td_bt_rl_directions():
    for direction in ("TD", "BT", "RL"):
        assert validate_mermaid(f"flowchart {direction}\nA-->B").ok is True, direction


def test_rejects_non_flowchart():
    assert validate_mermaid("graph LR\nA-->B").ok is False


def test_rejects_xss_content():
    result = validate_mermaid('flowchart LR\nA-->B["<script>alert(1)</script>"]')
    assert result.ok is False


async def test_rejects_broken_arrow_with_mermaid_parser():
    result = await validate_mermaid_syntax(
        "flowchart LR\nA -->", LLMDeadline.from_timeout_ms(30_000)
    )
    assert result.ok is False
    assert "Parse error" in (result.reason or "")


async def test_accepts_valid_flowchart_with_mermaid_parser():
    result = await validate_mermaid_syntax(
        "flowchart LR\nA --> B", LLMDeadline.from_timeout_ms(30_000)
    )
    assert result.ok is True


async def test_parser_startup_failure_is_not_treated_as_invalid_mermaid(monkeypatch):
    monkeypatch.setenv("MERMAID_MODULE_PATH", "C:/missing/mermaid.mjs")
    with pytest.raises(MermaidParserUnavailable):
        await validate_mermaid_syntax(
            "flowchart LR\nA --> B", LLMDeadline.from_timeout_ms(30_000)
        )

async def test_syntax_validation_accepts_a_result_after_llm_budget_expires():
    now = [0.0]
    deadline = LLMDeadline.from_timeout_ms(1_000, clock=lambda: now[0])
    now[0] = 400.0
    result = await validate_mermaid_syntax("flowchart LR\nA --> B", deadline)
    assert result.ok is True


@pytest.mark.parametrize("code", [
    'flowchart LR\nA["Start"] --> B["Finish"]',
    'flowchart TD\nsubgraph portal["Portal"]\nA["Request"] -->|"approved"| B["Result"]\nend',
    'flowchart LR\nA["<b>Start</b><br/>Next"] --> B["Finish"]',
])
async def test_accepts_flowchart_labels_with_mermaid_parser(code):
    result = await validate_mermaid_syntax(code, LLMDeadline.from_timeout_ms(30_000))
    assert result.ok is True, result.reason


async def test_rejects_broken_labeled_flowchart_with_mermaid_parser():
    result = await validate_mermaid_syntax(
        'flowchart LR\nA["Start"] -->', LLMDeadline.from_timeout_ms(30_000)
    )
    assert result.ok is False
    assert "Parse error" in (result.reason or "")


async def test_parser_runtime_failure_is_not_treated_as_invalid_mermaid(monkeypatch, tmp_path):
    module = tmp_path / "broken-mermaid.mjs"
    module.write_text(
        'export default { initialize() {}, async parse() { throw new TypeError("sanitizer unavailable"); } };',
        encoding="utf-8",
    )
    monkeypatch.setenv("MERMAID_MODULE_PATH", str(module))
    with pytest.raises(MermaidParserUnavailable, match="sanitizer unavailable"):
        await validate_mermaid_syntax(
            'flowchart LR\nA["Start"] --> B', LLMDeadline.from_timeout_ms(30_000)
        )
