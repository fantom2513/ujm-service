import re

from app.domain.chat_request import compute_chat_request_hash


def test_chat_request_hash_is_stable_versioned_sha256():
    request_hash = compute_chat_request_hash(
        message="add B",
        effective_action_type="FREEFORM",
    )

    assert request_hash == (
        "4f7e91bf8adc81787f6f1af1a6409cf4c0b54a53f1952e24ddf1f01d7bde8eb2"
    )
    assert re.fullmatch(r"[0-9a-f]{64}", request_hash)


def test_chat_request_hash_uses_exact_message():
    plain = compute_chat_request_hash(
        message="Измени блок",
        effective_action_type="FREEFORM",
    )
    repeated = compute_chat_request_hash(
        message="Измени блок",
        effective_action_type="FREEFORM",
    )
    padded = compute_chat_request_hash(
        message=" Измени блок ",
        effective_action_type="FREEFORM",
    )

    assert repeated == plain
    assert padded != plain


def test_chat_request_hash_uses_effective_action_type():
    freeform = compute_chat_request_hash(
        message="undo",
        effective_action_type="FREEFORM",
    )
    restore = compute_chat_request_hash(
        message="undo",
        effective_action_type="RESTORE_PREVIOUS",
    )

    assert restore != freeform
