from app.services.files.extract import (
    get_extension,
    has_pdf_text_layer,
    is_text_source_format,
    normalize_text_file,
    sanitize_filename,
)


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


def test_has_pdf_text_layer_detects_bt_tj_operators():
    content = b"%PDF-1.4\nBT /F1 12 Tf 50 150 Td (Hello) Tj ET"
    assert has_pdf_text_layer("report.pdf", content) is True


def test_has_pdf_text_layer_false_without_operators():
    content = b"%PDF-1.4\n<< /Type /Catalog >>"
    assert has_pdf_text_layer("report.pdf", content) is False


def test_has_pdf_text_layer_non_pdf_always_true():
    assert has_pdf_text_layer("notes.txt", b"anything") is True


async def test_normalize_text_file_txt_uses_raw_content():
    result = await normalize_text_file("notes.txt", b"Hello world", size=11)
    assert result.type == "text-file"
    assert result.text == "Hello world"
    assert result.stub is False
    assert result.file["format"] == "TXT"


async def test_normalize_text_file_xlsx_is_stub():
    result = await normalize_text_file("data.xlsx", b"binary", size=6)
    assert result.stub is True
    assert "XLSX" in result.text
