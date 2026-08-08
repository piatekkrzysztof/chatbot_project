"""
Wyciąganie tekstu z wgranych plików.

Zastępuje textract, który ciągnął nierozwiązywalne zależności (m.in. wadliwy
specyfikator `extract-msg <=0.29.*` oraz przypięcia kolidujące z beautifulsoup4
i chardet używanymi w projekcie). Obsługiwane formaty pokrywamy bibliotekami,
które i tak są w zależnościach.
"""
import os

import docx2txt

from documents.utils.pdf_parser import extract_text_from_pdf

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")


class UnsupportedFileType(Exception):
    pass


def extract_text(path: str) -> str:
    """Zwraca tekst pliku albo rzuca UnsupportedFileType dla nieobsługiwanego formatu."""
    extension = os.path.splitext(path)[1].lower()

    if extension == ".pdf":
        with open(path, "rb") as handle:
            return extract_text_from_pdf(handle)

    if extension == ".docx":
        return (docx2txt.process(path) or "").strip()

    if extension in (".txt", ".md"):
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()

    raise UnsupportedFileType(
        f"Nieobsługiwany format pliku: {extension or 'brak rozszerzenia'}. "
        f"Obsługiwane: {', '.join(SUPPORTED_EXTENSIONS)}"
    )
