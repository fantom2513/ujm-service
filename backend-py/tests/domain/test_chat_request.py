import re

from app.domain.chat_request import CHAT_REQUEST_HASH_VERSION, compute_chat_request_hash


def test_chat_request_hash_is_stable_versioned_sha256():
    assert CHAT_REQUEST_HASH_VERSION == 2

    request_hash = compute_chat_request_hash(
        message="add B",
        effective_action_type="FREEFORM",
    )

    assert request_hash == (
        "d3f2c13204e57e5253dbd0f6b56930298f8c31181230fde6d708fdec89304a57"
    )
    assert re.fullmatch(r"[0-9a-f]{64}", request_hash)


def test_chat_request_hash_defaults_attachment_to_empty():
    without_kwarg = compute_chat_request_hash(
        message="add B",
        effective_action_type="FREEFORM",
    )
    with_empty_attachment = compute_chat_request_hash(
        message="add B",
        effective_action_type="FREEFORM",
        attachment_context="",
    )

    assert without_kwarg == with_empty_attachment


def test_chat_request_hash_changes_when_attachment_content_differs():
    # Requirement: reusing one requestId with different file content must be
    # treated as a different request, not replay a result produced for
    # another file (docs/superpowers/specs/2026-09-09-chat-attachments-tech-debt.md #7).
    first = compute_chat_request_hash(
        message="explain the attachment",
        effective_action_type="FREEFORM",
        attachment_context="Invoice total: 100 USD",
    )
    second = compute_chat_request_hash(
        message="explain the attachment",
        effective_action_type="FREEFORM",
        attachment_context="Invoice total: 200 USD",
    )
    no_attachment = compute_chat_request_hash(
        message="explain the attachment",
        effective_action_type="FREEFORM",
    )

    assert first != second
    assert first != no_attachment
    assert second != no_attachment


def test_chat_request_hash_is_stable_for_the_same_attachment_content():
    first = compute_chat_request_hash(
        message="explain the attachment",
        effective_action_type="FREEFORM",
        attachment_context="Invoice total: 100 USD",
    )
    repeated = compute_chat_request_hash(
        message="explain the attachment",
        effective_action_type="FREEFORM",
        attachment_context="Invoice total: 100 USD",
    )

    assert first == repeated


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
