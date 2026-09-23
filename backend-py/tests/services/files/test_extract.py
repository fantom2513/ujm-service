import io

from openpyxl import Workbook

from app.services.files.extract import (
    get_extension,
    is_chat_document_format,
    is_text_source_format,
    normalize_text_file,
    sanitize_filename,
)


def _xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Age"])
    sheet.append(["Alice", 30])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_get_extension_lowercases_and_strips_dot():
    assert get_extension("Report.PDF") == "pdf"


def test_get_extension_no_dot_returns_empty():
    assert get_extension("noext") == ""


def test_sanitize_filename_replaces_unsafe_chars():
    assert sanitize_filename('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"


def test_sanitize_filename_truncates_to_140_chars():
    assert len(sanitize_filename("a" * 300)) == 140


def test_is_text_source_format():
    assert is_text_source_format("txt") is True
    assert is_text_source_format("pdf") is True
    assert is_text_source_format("docx") is True
    assert is_text_source_format("mp3") is False


async def test_normalize_text_file_txt_uses_raw_content():
    result = await normalize_text_file("notes.txt", b"Hello world", size=11)
    assert result.type == "text-file"
    assert result.text == "Hello world"
    assert result.stub is False
    assert result.file["format"] == "TXT"


async def test_normalize_text_file_xlsx_extracts_real_content():
    content = _xlsx_bytes()
    result = await normalize_text_file("data.xlsx", content, size=len(content))
    assert result.stub is False
    assert "Alice" in result.text
    assert "30" in result.text
    assert result.file["format"] == "XLSX"


def test_is_chat_document_format_excludes_legacy_xls():
    # .xls is the legacy OLE2/BIFF format; openpyxl (used by parse_xlsx) can
    # only read OOXML .xlsx, so accepting .xls would silently lose the
    # attachment's content instead of extracting it. Reject it outright
    # instead of a NormalizedSource stub, matching the frontend's format list
    # (frontend/src/utils/chatAttachments.ts).
    assert is_chat_document_format("xls") is False


def test_is_chat_document_format_accepts_text_and_table_formats():
    for fmt in ("txt", "docx", "pdf", "xlsx", "csv"):
        assert is_chat_document_format(fmt) is True
    assert is_chat_document_format("mp3") is False
