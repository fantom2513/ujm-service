from app.services.files.docx import parse_docx


async def test_parse_docx_returns_string_for_invalid_buffer():
    result = await parse_docx(b"not a docx")
    assert isinstance(result, str)


async def test_parse_docx_never_throws_on_garbage_input():
    result = await parse_docx(bytes([0x00, 0x01, 0x02, 0xFF, 0xFE]))
    assert isinstance(result, str)


async def test_parse_docx_returns_empty_string_on_empty_buffer():
    result = await parse_docx(b"")
    assert result == ""
