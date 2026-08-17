from __future__ import annotations

import re
from dataclasses import dataclass

# Mermaid flowchart directions: TB (top-bottom), TD (top-down, synonym of
# TB), BT, RL, LR. The generate/edit prompts instruct the model to start
# with `flowchart LR` or `flowchart TB` (TB for complex >12-node diagrams),
# so both must pass validation — accept the full set to be safe.
_FLOWCHART_HEADER = re.compile(r"^flowchart\s+(TB|TD|BT|RL|LR)\b")
_UNSAFE_CONTENT = re.compile(r"<script|</script|onerror=|onload=", re.IGNORECASE)


@dataclass
class ValidationResult:
    ok: bool
    reason: str | None = None


def validate_mermaid(code: str) -> ValidationResult:
    trimmed = code.strip()
    if not _FLOWCHART_HEADER.search(trimmed):
        return ValidationResult(False, "Mermaid must start with 'flowchart' and a direction (LR/TB/TD/BT/RL)")
    if _UNSAFE_CONTENT.search(trimmed):
        return ValidationResult(False, "Unsafe content in Mermaid")
    return ValidationResult(True)
