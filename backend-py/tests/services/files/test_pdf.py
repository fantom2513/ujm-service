from app.services.files.pdf import parse_pdf

GARBAGE_BUFFER = b"this is definitely not a pdf file at all"


async def test_parse_pdf_never_throws_on_non_pdf_buffer():
    text = await parse_pdf(GARBAGE_BUFFER)
    assert text == ""


async def test_parse_pdf_never_throws_on_empty_buffer():
    text = await parse_pdf(b"")
    assert text == ""
