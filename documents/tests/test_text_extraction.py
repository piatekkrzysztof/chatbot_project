import io

import pytest
from reportlab.pdfgen import canvas

from documents.utils.text_extraction import UnsupportedFileType, extract_text


def write_pdf(path, text):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(100, 750, text)
    pdf.showPage()
    pdf.save()
    path.write_bytes(buffer.getvalue())


def test_extracts_pdf(tmp_path):
    path = tmp_path / "cennik.pdf"
    write_pdf(path, "Przeglad kosztuje 120 zl")

    assert "120" in extract_text(str(path))


def test_extracts_plain_text(tmp_path):
    path = tmp_path / "notatki.txt"
    path.write_text("Godziny otwarcia: 9-17", encoding="utf-8")

    assert extract_text(str(path)) == "Godziny otwarcia: 9-17"


def test_extracts_markdown(tmp_path):
    path = tmp_path / "readme.md"
    path.write_text("# Oferta\n\nSerwis rowerowy", encoding="utf-8")

    assert "Serwis rowerowy" in extract_text(str(path))


def test_rejects_unsupported_format(tmp_path):
    path = tmp_path / "stary.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0")

    with pytest.raises(UnsupportedFileType) as exc:
        extract_text(str(path))
    assert ".doc" in str(exc.value)


def test_rejects_file_without_extension(tmp_path):
    path = tmp_path / "bezrozszerzenia"
    path.write_text("cokolwiek", encoding="utf-8")

    with pytest.raises(UnsupportedFileType):
        extract_text(str(path))
