"""
Wyciąganie tekstu z wgranych plików.

Zastępuje textract, który ciągnął nierozwiązywalne zależności (m.in. wadliwy
specyfikator `extract-msg <=0.29.*` oraz przypięcia kolidujące z beautifulsoup4
i chardet używanymi w projekcie). Obsługiwane formaty pokrywamy bibliotekami,
które i tak są w zależnościach.

Funkcja przyjmuje zarówno ścieżkę, jak i otwarty plik. Wariant z plikiem jest
tym, którego używa produkcja: FieldFile.path istnieje wyłącznie dla magazynu
na dysku i na S3 czy R2 rzuca NotImplementedError. Bez tego przetwarzanie
dokumentów przestałoby działać w momencie przepięcia magazynu na zewnętrzny.
"""

import os
from pathlib import Path

from documents.isolated_parser import parse_document

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")


class UnsupportedFileType(Exception):
    pass


def extract_text(source, filename: str | None = None) -> str:
    """
    Zwraca tekst dokumentu albo rzuca UnsupportedFileType.

    `source` to ścieżka na dysku albo otwarty plik binarny. Przy pliku format
    rozpoznajemy po `filename`, a gdy go nie podano — po atrybucie `name`,
    który mają zarówno pliki Django, jak i zwykłe uchwyty.
    """
    if isinstance(source, (str, Path)):
        with open(source, "rb") as handle:
            return _extract(handle, filename or str(source))

    return _extract(source, filename or getattr(source, "name", ""))


def _extract(handle, name: str) -> str:
    extension = os.path.splitext(name or "")[1].lower()

    if extension in SUPPORTED_EXTENSIONS:
        return parse_document(handle, name)

    raise UnsupportedFileType(
        f"Nieobsługiwany format pliku: {extension or 'brak rozszerzenia'}. "
        f"Obsługiwane: {', '.join(SUPPORTED_EXTENSIONS)}"
    )
