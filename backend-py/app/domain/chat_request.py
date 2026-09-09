from __future__ import annotations

import hashlib
import json

CHAT_REQUEST_HASH_VERSION = 1


def compute_chat_request_hash(*, message: str, effective_action_type: str) -> str:
    """Return a stable identity check for the effective chat payload."""
    payload = {
        "version": CHAT_REQUEST_HASH_VERSION,
        "message": message,
        "actionType": effective_action_type,
    }
    canonical_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
