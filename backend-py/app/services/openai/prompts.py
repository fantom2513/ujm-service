from __future__ import annotations

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
