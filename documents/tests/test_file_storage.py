"""
Magazyn wgrywanych plików i ekstrakcja niezależna od niego.

Dwie rzeczy, które łatwo przeoczyć, bo obie zawodzą po cichu:

1. Bez skonfigurowanego magazynu obiektowego pliki lądują na dysku kontenera,
   który Render kasuje przy każdym wdrożeniu. Zapis się udaje, błędu nie ma,
   a logo klienta znika po kilku dniach.
2. FieldFile.path działa wyłącznie z magazynem na dysku. Na S3 czy R2 rzuca
   NotImplementedError, więc samo przepięcie magazynu zabiłoby przetwarzanie
   dokumentów — i to dopiero na produkcji, bo testy chodzą na dysku lokalnym.
"""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from reportlab.pdfgen import canvas

from documents.models import Document
from documents.tasks import extract_text_from_document
from documents.utils.text_extraction import extract_text


def pdf_bytes(text):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(100, 750, text)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


class TestEkstrakcjaBezSciezki:
    """Ekstrakcja musi działać na uchwycie pliku, nie na ścieżce dyskowej."""

    def test_pdf_z_obiektu_pliku(self):
        handle = io.BytesIO(pdf_bytes("Przeglad kosztuje 120 zl"))

        assert "120" in extract_text(handle, filename="cennik.pdf")

    def test_tekst_z_obiektu_pliku(self):
        handle = io.BytesIO(b"Godziny otwarcia: 9-17")

        assert extract_text(handle, filename="notatki.txt") == "Godziny otwarcia: 9-17"

    def test_format_rozpoznany_po_atrybucie_name(self):
        """Pliki Django niosą nazwę w .name — nie trzeba jej podawać osobno."""
        handle = io.BytesIO(b"# Oferta\n\nSerwis rowerowy")
        handle.name = "readme.md"

        assert "Serwis rowerowy" in extract_text(handle)


def _wgrany_dokument(tenant, tresc="Serwis 250 zl"):
    return Document.objects.create(
        tenant=tenant,
        name="cennik.pdf",
        file=SimpleUploadedFile("cennik.pdf", pdf_bytes(tresc), content_type="application/pdf"),
    )


@pytest.mark.django_db
def test_zadanie_przetwarza_plik_z_magazynu(tenant):
    """
    Zadanie wołamy wprost: conftest wyłącza .delay() dla zadań dokumentów,
    więc samo wgranie pliku niczego w testach nie uruchamia.
    """
    document = _wgrany_dokument(tenant)

    extract_text_from_document(document.id)

    document.refresh_from_db()
    assert document.processed is True
    assert "250" in document.content


@pytest.mark.django_db
def test_zadanie_nie_siega_po_sciezke_na_dysku(tenant, monkeypatch):
    """
    Najważniejszy test w tym pliku.

    FieldFile.path istnieje wyłącznie dla magazynu na dysku — na S3 czy R2
    rzuca NotImplementedError. Podstawiamy tu takie zachowanie, żeby powrót
    do .path wyszedł na testach, a nie dopiero po przepięciu magazynu na
    produkcji, gdzie objawiłby się cichym brakiem przetworzonych dokumentów
    (zadanie łapie wyjątki i tylko loguje).
    """
    from django.db.models.fields.files import FieldFile

    document = _wgrany_dokument(tenant, "Przeglad 120 zl")

    def brak_sciezki(self):
        raise NotImplementedError("magazyn zdalny nie udostępnia ścieżek lokalnych")

    monkeypatch.setattr(FieldFile, "path", property(brak_sciezki))

    extract_text_from_document(document.id)

    document.refresh_from_db()
    assert document.processed is True
    assert "120" in document.content


class TestOstrzezenieOMagazynie:
    def test_brak_magazynu_daje_ostrzezenie(self, settings):
        settings.DEBUG = False
        settings.USE_OBJECT_STORAGE = False
        from documents.checks import ephemeral_file_storage

        wyniki = ephemeral_file_storage(None)

        assert [w.id for w in wyniki] == ["documents.W001"]

    def test_skonfigurowany_magazyn_milczy(self, settings):
        settings.DEBUG = False
        settings.USE_OBJECT_STORAGE = True
        from documents.checks import ephemeral_file_storage

        assert ephemeral_file_storage(None) == []

    def test_lokalnie_nie_zawracamy_glowy(self, settings):
        """Na maszynie dewelopera dysk jest trwały — ostrzeżenie byłoby szumem."""
        settings.DEBUG = True
        settings.USE_OBJECT_STORAGE = False
        from documents.checks import ephemeral_file_storage

        assert ephemeral_file_storage(None) == []
