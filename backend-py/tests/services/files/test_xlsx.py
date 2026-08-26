import io

from openpyxl import Workbook

from app.services.files.xlsx import parse_xlsx

GARBAGE_BUFFER = b"this is definitely not an xlsx file at all"


def _xlsx_with_rows_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Age"])
    sheet.append(["Alice", 30])
    sheet.append([None, None])
    sheet.append(["Bob", 25])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def test_parse_xlsx_returns_tab_separated_rows_and_skips_empty_rows():
    result = await parse_xlsx(_xlsx_with_rows_bytes())
    lines = result.split("\n")
    assert "Name\tAge" in lines
    assert "Alice\t30" in lines
    assert "Bob\t25" in lines
    # Строка, где все ячейки пустые (None), не должна попасть в результат
    # ни как содержательная строка, ни как пустая строка между другими.
    assert "" not in lines
    assert len(lines) == 3


async def test_parse_xlsx_never_throws_on_non_xlsx_buffer():
    result = await parse_xlsx(GARBAGE_BUFFER)
    assert result == ""


async def test_parse_xlsx_never_throws_on_empty_buffer():
    result = await parse_xlsx(b"")
    assert result == ""
