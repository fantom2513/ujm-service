from __future__ import annotations


def required_source_error(source_type: str | None, has_file: bool, link: str) -> str | None:
    """Guards against "silent generation" (#12): a /api/generate request that
    carries no usable source must be rejected with a 400 before the LLM is
    ever called. Returns the error code to send back, or None when the
    source is valid."""
    if source_type in ("text-file", "recording"):
        return None if has_file else "file-required"
    if source_type == "link":
        return None if link.strip() else "link-required"
    return "diagram-generation"
