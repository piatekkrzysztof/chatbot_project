from pypdf import PdfReader

from documents.file_limits import (
    MAX_PDF_PAGES,
    MAX_PDF_STREAM_BYTES,
    MAX_TEXT_CHARS,
    InvalidUpload,
    UploadTooLarge,
)


def extract_text_from_pdf(file_obj) -> str:
    reader = PdfReader(file_obj)
    if reader.is_encrypted:
        raise InvalidUpload("PDF jest zaszyfrowany. Wgraj wersję bez hasła.")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise UploadTooLarge("PDF przekracza limit 200 stron.")
    parts, length = [], 0
    for page in reader.pages:
        contents = page.get_contents()
        if contents is not None and len(contents.get_data()) > MAX_PDF_STREAM_BYTES:
            raise UploadTooLarge("Strona PDF jest zbyt złożona do przetworzenia.")
        text = page.extract_text() or ""
        length += len(text)
        if length > MAX_TEXT_CHARS:
            raise UploadTooLarge("Tekst PDF przekracza limit 2 097 152 znaków.")
        parts.append(text)
    return "\n".join(parts).strip()
