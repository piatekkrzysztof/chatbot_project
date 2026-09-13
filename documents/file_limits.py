"""File policy shared by HTTP uploads and the isolated parsing process."""

import io
import re
import zipfile
from pathlib import PurePosixPath

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 2 * 1024 * 1024
MAX_PDF_PAGES = 200
MAX_PDF_STREAM_BYTES = 8 * 1024 * 1024
MAX_ZIP_MEMBERS = 256
MAX_ZIP_BYTES = 20 * 1024 * 1024
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 4_000_000
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
IMAGE_EXTENSIONS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}


class InvalidUpload(ValueError):
    pass


class UploadTooLarge(InvalidUpload):
    pass


def extension(name):
    return PurePosixPath(str(name).replace("\\", "/")).suffix.lower()


def bounded_read(handle, limit):
    if getattr(handle, "size", 0) > limit:
        raise UploadTooLarge("Plik przekracza dozwolony rozmiar.")
    handle.seek(0)
    data = handle.read(limit + 1)
    handle.seek(0)
    if len(data) > limit:
        raise UploadTooLarge("Plik przekracza dozwolony rozmiar.")
    if not data:
        raise InvalidUpload("Plik jest pusty.")
    return data


POLSKIE_LITERY = re.compile("[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
ZNAKI_C1 = re.compile("[\x80-\x9f]")


def read_text(data):
    """
    Tekst pliku TXT/MD w UTF-8, UTF-16 z BOM, Windows-1250 albo ISO-8859-2.

    Wcześniej przyjmowaliśmy wyłącznie UTF-8, a cennik zapisany w starszym
    Notatniku albo wyeksportowany z programu księgowego bywa w Windows-1250.
    Plik był odrzucany jako „nie UTF-8", choć tekst był poprawny.

    Windows-1250 i ISO-8859-2 różnią się akurat polskimi literami (ą, ś, ź,
    Ą, Ś, Ź), więc wybieramy wariant z większą liczbą polskich liter, a przy
    remisie Windows-1250, domyślne kodowanie polskiego Windowsa. Bajty tych
    liter w drugim kodowaniu to znaki spoza alfabetu albo sterujące, więc
    liczenie rozstrzyga także plik z samymi ś, ź i Ą.

    Wariant ze znakami sterującymi C1 (U+0080-U+009F) odpada. ISO-8859-2
    dekoduje każdy bajt, więc bez tego plik z bajtami bez znaczenia w żadnym
    kodowaniu przechodził jako tekst z niewidocznymi znakami.
    """
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeError:
            raise InvalidUpload("Nie udało się odczytać pliku tekstowego w UTF-16.") from None
    try:
        return data.decode("utf-8-sig")
    except UnicodeError:
        pass
    candidates = []
    for position, encoding in enumerate(["cp1250", "iso-8859-2"]):
        try:
            text = data.decode(encoding)
        except UnicodeError:
            continue
        if ZNAKI_C1.search(text):
            continue
        candidates.append((len(POLSKIE_LITERY.findall(text)), -position, text))
    if not candidates:
        raise InvalidUpload(
            "Nie rozpoznano kodowania pliku tekstowego. Zapisz go w UTF-8 i wgraj ponownie."
        )
    return max(candidates)[2]


def check_text(data):
    text = read_text(data)
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", text):
        raise InvalidUpload("Plik tekstowy zawiera dane binarne lub niedozwolone znaki.")
    return check_extracted_text(text)


def check_extracted_text(text):
    if len(text) > MAX_TEXT_CHARS:
        raise UploadTooLarge("Wyodrębniony tekst przekracza limit 2 097 152 znaków na dokument.")
    return text.strip()


def inspect_docx(data):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        members = archive.infolist()
    except (zipfile.BadZipFile, ValueError):
        raise InvalidUpload("Nieprawidłowy plik DOCX.") from None
    try:
        if len(members) > MAX_ZIP_MEMBERS:
            raise UploadTooLarge("Plik DOCX zawiera zbyt wiele elementów.")
        names = set()
        size = 0
        for member in members:
            path = PurePosixPath(member.filename)
            if (
                member.orig_filename != member.filename
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in member.filename
                or ":" in member.filename
                or member.filename in names
                or member.flag_bits & 1
                or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                or "vbaproject" in member.filename.lower()
            ):
                raise InvalidUpload("Plik DOCX zawiera niedozwolone elementy.")
            names.add(member.filename)
            size += member.file_size
            if size > MAX_ZIP_BYTES or member.file_size > MAX_XML_BYTES:
                raise UploadTooLarge("Rozpakowany plik DOCX przekracza limit rozmiaru.")
        if "word/document.xml" not in names or "[Content_Types].xml" not in names:
            raise InvalidUpload("To archiwum nie jest dokumentem DOCX.")
    finally:
        archive.close()


def inspect_document(data, name, *, full=True):
    kind = extension(name)
    if kind not in DOCUMENT_EXTENSIONS:
        raise InvalidUpload("Obsługiwane dokumenty: PDF, DOCX, TXT i MD.")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise UploadTooLarge("Dokument przekracza limit 10 MiB.")
    if not data:
        raise InvalidUpload("Plik jest pusty.")
    if kind == ".pdf" and not data.startswith(b"%PDF-"):
        raise InvalidUpload("Zawartość pliku nie jest dokumentem PDF.")
    if kind == ".docx":
        if not data.startswith(b"PK\x03\x04"):
            raise InvalidUpload("Zawartość pliku nie jest dokumentem DOCX.")
        if full:
            inspect_docx(data)
    elif full and kind in {".txt", ".md"}:
        check_text(data)
    return kind


# Właściwości akapitów, przebiegów i tabel nie zawierają tekstu. Omijamy je
# w całości: `w:tab` wewnątrz `w:pPr/w:tabs` to definicja pozycji tabulatora,
# nie tabulator w treści, i wcześniej dopisywał zbędne znaki.
DOCX_PROPERTIES = {"pPr", "rPr", "tblPr", "trPr", "tcPr", "sectPr", "tblGrid"}


def _docx_name(node):
    return node.tag.rsplit("}", 1)[-1] if isinstance(node.tag, str) else ""


def _docx_nearest(node, name):
    """Najbliższe elementy o tej nazwie, także opakowane kontrolkami treści (w:sdt)."""
    for child in node:
        child_name = _docx_name(child)
        if child_name == name:
            yield child
        elif child_name not in {"tbl", "Fallback"}:
            yield from _docx_nearest(child, name)


def _docx_text(node, parts):
    name = _docx_name(node)
    if name == "Fallback" or name in DOCX_PROPERTIES:
        # mc:AlternateContent: Word zapisuje pole tekstowe dwa razy, w wersji
        # nowej (Choice) i zapasowej dla starszych programów (Fallback).
        # Wcześniej tekst każdego pola tekstowego trafiał do wiedzy podwójnie.
        return
    if name == "tbl":
        # Wiersz tabeli w jednej linii: "Strzyżenie | 50 zł". Wcześniej każda
        # komórka była osobną linią, więc usługa i jej cena mogły trafić do
        # różnych fragmentów, a bot odpowiadał ceną bez usługi.
        for row in _docx_nearest(node, "tr"):
            cells = []
            for cell in _docx_nearest(row, "tc"):
                inner = []
                _docx_text(cell, inner)
                cells.append(" ".join("".join(inner).split()))
            if any(cells):
                parts.append(" | ".join(cells) + "\n")
        return
    if name == "t" and node.text:
        parts.append(node.text)
    elif name == "tab":
        parts.append("\t")
    elif name in {"br", "cr"}:
        parts.append("\n")
    elif name == "noBreakHyphen":
        parts.append("-")
    for child in node:
        _docx_text(child, parts)
    if name == "p":
        parts.append("\n")


def extract_docx(data):
    from defusedxml import ElementTree
    from defusedxml.common import DefusedXmlException

    inspect_docx(data)
    parts, total = [], 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [
                name
                for name in archive.namelist()
                if re.fullmatch(r"word/(?:document|header\d+|footer\d+)\.xml", name)
            ]
            for name in names:
                with archive.open(name) as handle:
                    body = handle.read(MAX_XML_BYTES + 1)
                total += len(body)
                if len(body) > MAX_XML_BYTES or total > MAX_ZIP_BYTES:
                    raise UploadTooLarge("Rozpakowany plik DOCX przekracza limit rozmiaru.")
                tree = ElementTree.fromstring(body, forbid_dtd=True)
                _docx_text(tree, parts)
                parts.append("\n")
        return check_extracted_text("".join(parts))
    except (zipfile.BadZipFile, ElementTree.ParseError, DefusedXmlException, RuntimeError):
        raise InvalidUpload("Nie udało się odczytać pliku DOCX.") from None


def normalize_image(data, name):
    from PIL import Image, ImageOps, UnidentifiedImageError

    expected = IMAGE_EXTENSIONS.get(extension(name))
    if not expected:
        raise InvalidUpload("Logo i awatar muszą być obrazem PNG, JPEG lub WebP.")
    if len(data) > MAX_IMAGE_BYTES:
        raise UploadTooLarge("Obraz przekracza limit 2 MiB.")
    try:
        with Image.open(io.BytesIO(data), formats=[expected]) as image:
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS or max(width, height) > 4096:
                raise UploadTooLarge("Obraz przekracza limit 4 mln pikseli lub 4096 px na bok.")
            if getattr(image, "n_frames", 1) != 1:
                raise InvalidUpload("Logo i awatar muszą być obrazem bez animacji.")
            image.load()
            image = ImageOps.exif_transpose(image)
            image.thumbnail((1024, 1024))
            # New pixel-only image: remove EXIF, profiles, comments and appended data.
            pixels = image.convert("RGBA")
            clean = Image.frombytes("RGBA", pixels.size, pixels.tobytes())
            output = io.BytesIO()
            clean.save(output, format="PNG")
            result = output.getvalue()
        if len(result) > MAX_IMAGE_BYTES:
            raise UploadTooLarge("Obraz po optymalizacji przekracza limit 2 MiB.")
        return result
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise InvalidUpload(
            "Nie udało się odczytać obrazu. Sprawdź format i zawartość pliku."
        ) from None
