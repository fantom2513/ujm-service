from __future__ import annotations

import hashlib
import json


def compute_generate_request_hash(
    *, source_type: str, details: str, link: str, filename: str, file_content: bytes
) -> str:
    payload = {
        "version": 1,
        "sourceType": source_type,
        "details": details,
        "link": link,
        "filename": filename,
        "fileSha256": hashlib.sha256(file_content).hexdigest(),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
