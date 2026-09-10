"""Real child-process limits and hostile documents; no network/storage services."""

import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin
from pypdf import PdfWriter

from documents import isolated_parser as parser
from documents.file_limits import InvalidUpload, UploadTooLarge, normalize_image


def docx(body=None, extras=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr(
            "word/document.xml",
            body
            or (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
                "Oferta 120 zł</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
        for name, content in (extras or {}).items():
            archive.writestr(name.replace("\\", "/"), content)
    data = output.getvalue()
    # Windows ZipInfo normalizes backslashes; construct the hostile wire name.
    for name in extras or {}:
        if "\\" in name:
            data = data.replace(name.replace("\\", "/").encode(), name.encode())
    return data


def picture(format="PNG", size=(20, 10), **options):
    output = io.BytesIO()
    mode = "RGB" if format == "JPEG" else "RGBA"
    Image.new(mode, size, "red").save(output, format=format, **options)
    return output.getvalue()


def test_real_docx_and_unicode_text():
    assert parser.parse_bytes(docx(), "oferta.docx") == "Oferta 120 zł"
    assert (
        parser.parse_bytes("\ufeff# Zażółć\nCena 120 zł".encode(), "oferta.MD")
        == "# Zażółć\nCena 120 zł"
    )


@pytest.mark.parametrize(
    "extra", ["../escape", "/root", "C:drive", "word\\evil", "word/vbaProject.bin"]
)
def test_docx_rejects_unsafe_archive_members(extra):
    with pytest.raises(InvalidUpload):
        parser.parse_bytes(docx(extras={extra: b"test"}), "unsafe.docx")


def test_docx_rejects_external_entities():
    content = '<!DOCTYPE document [<!ENTITY secret SYSTEM "file:///nonexistent/audit-secret">]><document><t>&secret;</t></document>'
    with pytest.raises(InvalidUpload):
        parser.parse_bytes(docx(content), "entity.docx")


def test_docx_rejects_names_truncated_by_zip_reader():
    data = docx(extras={"word/null_bad": b"ignored"})
    data = data.replace(b"word/null_bad", b"word/null\x00bad")
    with pytest.raises(InvalidUpload):
        parser.parse_bytes(data, "null.docx")


def test_docx_bounds_decompressed_member_and_count():
    with pytest.raises(UploadTooLarge):
        parser.parse_bytes(
            docx(extras={"word/large.xml": b"x" * (8 * 1024 * 1024 + 1)}), "bomb.docx"
        )
    with pytest.raises(UploadTooLarge):
        parser.parse_bytes(
            docx(extras={f"word/x{n}.xml": b"x" for n in range(255)}), "members.docx"
        )


def test_pdf_rejects_encryption_and_page_limit():
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.encrypt("private")
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(InvalidUpload):
        parser.parse_bytes(output.getvalue(), "locked.pdf")
    writer = PdfWriter()
    for _ in range(201):
        writer.add_blank_page(100, 100)
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(UploadTooLarge):
        parser.parse_bytes(output.getvalue(), "pages.pdf")


def test_text_has_character_and_encoding_limits():
    with pytest.raises(UploadTooLarge):
        parser.parse_bytes(b"x" * (2 * 1024 * 1024 + 1), "large.txt")
    with pytest.raises(InvalidUpload):
        parser.parse_bytes(b"\xff\xfe", "invalid.txt")


def test_pdf_bounds_decompressed_page_stream():
    from pypdf.generic import DecodedStreamObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(100, 100)
    stream = DecodedStreamObject()
    stream.set_data(b" " * (8 * 1024 * 1024 + 1))
    page[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    output = io.BytesIO()
    writer.write(output)
    assert len(output.getvalue()) < 20000
    with pytest.raises(InvalidUpload):
        parser.parse_bytes(output.getvalue(), "compressed.pdf")


@pytest.mark.parametrize("format,suffix", [("PNG", "png"), ("JPEG", "jpeg"), ("WEBP", "webp")])
def test_images_are_reencoded_as_png(format, suffix):
    result = parser.parse_bytes(
        picture(format) + b"<script>audit_marker</script>", "logo." + suffix, image=True
    )
    assert b"audit_marker" not in result
    with Image.open(io.BytesIO(result)) as image:
        assert image.format == "PNG"
        assert image.size == (20, 10)


def test_image_metadata_removed_and_alpha_preserved():
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "private_metadata_marker")
    output = io.BytesIO()
    Image.new("RGBA", (5, 5), (20, 40, 60, 80)).save(output, format="PNG", pnginfo=info)
    result = normalize_image(output.getvalue(), "alpha.png")
    assert b"private_metadata_marker" not in result
    with Image.open(io.BytesIO(result)) as image:
        assert image.getpixel((0, 0)) == (20, 40, 60, 80)
        assert not image.info


def test_image_orientation_is_applied_before_stripping_exif():
    exif = Image.Exif()
    exif[274] = 6
    result = normalize_image(picture("JPEG", exif=exif), "portrait.jpg")
    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (10, 20)
        assert not image.getexif()


def test_image_resize_and_pixel_limit():
    result = normalize_image(picture(size=(2000, 1000)), "logo.png")
    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (1024, 512)
    with pytest.raises(UploadTooLarge):
        parser.parse_bytes(picture(size=(2001, 2000)), "huge.png", image=True)


def test_image_real_format_and_animation_are_checked():
    with pytest.raises(InvalidUpload):
        parser.parse_bytes(picture("JPEG"), "fake.png", image=True)
    animation = picture(
        save_all=True, append_images=[Image.new("RGBA", (20, 10), "blue")], duration=100, loop=0
    )
    with pytest.raises(InvalidUpload):
        parser.parse_bytes(animation, "animated.png", image=True)


def test_parser_does_not_inherit_secrets(monkeypatch, tmp_path):
    script = tmp_path / "environment.py"
    script.write_text('import os,json\nprint(json.dumps({"text": json.dumps(dict(os.environ))}))')
    monkeypatch.setattr(parser, "PARSER_SCRIPT", script)
    monkeypatch.setenv("DATABASE_URL", "synthetic-private-marker")
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", "synthetic-private-marker")
    monkeypatch.setenv("PYTHONPATH", "synthetic-private-marker")
    environment = json.loads(parser.parse_bytes(b"test", "test.txt"))
    assert "DATABASE_URL" not in environment
    assert "BACKUP_ENCRYPTION_KEY" not in environment
    assert "PYTHONPATH" not in environment


def test_timeout_kills_and_reaps_child_and_releases_slot(monkeypatch, tmp_path):
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(60)")
    monkeypatch.setattr(parser, "PARSER_SCRIPT", script)
    monkeypatch.setattr(parser, "PARSER_SECONDS", 0.3)
    children = []
    original = subprocess.Popen

    def tracked(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", tracked)
    with pytest.raises(InvalidUpload, match="zbyt długo"):
        parser.parse_bytes(b"test", "test.txt")
    assert len(children) == 1
    assert children[0].poll() is not None
    with parser.parser_slot():
        pass


def test_memory_limit_rejects_real_allocation_in_child():
    root = str(Path(__file__).resolve().parents[2])
    program = (
        f"import sys; sys.path.insert(0, {root!r})\n"
        "from documents.parser_limits import apply_limits\n"
        "apply_limits(96 * 1024 * 1024)\n"
        "try:\n bytearray(256 * 1024 * 1024)\n"
        "except MemoryError:\n print('allocation_rejected')\n"
        "else:\n raise SystemExit('memory limit failed')\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", program], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "allocation_rejected"


def test_slot_prevents_concurrent_threads_and_processes():
    root = str(Path(__file__).resolve().parents[2])
    program = (
        f"import sys; sys.path.insert(0, {root!r})\n"
        "from documents.isolated_parser import parser_slot, ParserUnavailable\n"
        "try:\n with parser_slot(): print('unexpected_slot')\n"
        "except ParserUnavailable:\n print('busy')\n"
    )
    with parser.parser_slot():
        with pytest.raises(parser.ParserUnavailable):
            with parser.parser_slot():
                pytest.fail("Concurrent parser entered")
        result = subprocess.run(
            [sys.executable, "-I", "-c", program], capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "busy"


def test_low_container_headroom_fails_before_starting_parser(monkeypatch):
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self: str(512 * 1024 * 1024 if self.name == "memory.max" else 400 * 1024 * 1024),
    )
    with pytest.raises(parser.ParserUnavailable, match="zasobów"):
        parser.memory_budget()


def test_os_limit_setup_failure_is_closed(monkeypatch, tmp_path):
    script = tmp_path / "unavailable.py"
    script.write_text('import json\nprint(json.dumps({"error": "unavailable"}))')
    monkeypatch.setattr(parser, "PARSER_SCRIPT", script)
    with pytest.raises(parser.ParserUnavailable):
        parser.parse_bytes(b"test", "test.txt")
