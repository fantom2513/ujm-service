import logging

import pytest

from app.services.files._common import parse_in_thread


def _boom(buffer: bytes) -> str:
    raise ValueError("super secret file content: 4111-1111-1111-1111")


async def test_parse_in_thread_never_raises(caplog):
    result = await parse_in_thread(_boom, b"payload", logging.getLogger("test"), "pdf")
    assert result == ""


async def test_parse_in_thread_does_not_log_the_raw_exception_message(caplog):
    with caplog.at_level(logging.ERROR):
        await parse_in_thread(_boom, b"payload", logging.getLogger("test"), "pdf")

    logged_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "super secret" not in logged_text
    assert "4111-1111-1111-1111" not in logged_text


async def test_parse_in_thread_logs_enough_to_identify_the_root_cause(caplog):
    with caplog.at_level(logging.ERROR):
        await parse_in_thread(_boom, b"payload!!", logging.getLogger("test"), "pdf")

    logged_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "pdf" in logged_text
    assert "ValueError" in logged_text
    assert str(len(b"payload!!")) in logged_text


async def test_parse_in_thread_does_not_attach_a_traceback(caplog):
    with caplog.at_level(logging.ERROR):
        await parse_in_thread(_boom, b"payload", logging.getLogger("test"), "pdf")

    assert all(record.exc_info is None for record in caplog.records)
