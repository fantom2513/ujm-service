from __future__ import annotations

import hashlib
import json

CHAT_REQUEST_HASH_VERSION = 2


def compute_chat_request_hash(
    *, message: str, effective_action_type: str, attachment_context: str = ""
) -> str:
    """Return a stable identity check for the effective chat payload.

    attachment_context is the text extracted from an optional chat file
    attachment (see app.api.chat) -- included so that reusing one requestId
    with a different attachment is treated as a different request instead of
    replaying a result produced for another file.
    """
    payload = {
        "version": CHAT_REQUEST_HASH_VERSION,
        "message": message,
        "actionType": effective_action_type,
        "attachment": attachment_context,
    }
    canonical_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
