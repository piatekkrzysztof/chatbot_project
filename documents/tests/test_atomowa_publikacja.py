"""
Atomowa i powtarzalna publikacja fragmentów (F17).

Kategoria ryzyka: CICHA UTRATA WIEDZY KLIENTA.

Fragmenty są danymi pochodnymi treści, ale bot widzi WYŁĄCZNIE fragmenty.
Każdy stan, w którym fragmenty rozjeżdżają się z treścią, jest więc stanem,
w którym bot nie zna dokumentu albo zna jego wersję, której już nie ma - a panel
pokazuje przy tym status „gotowe".

Stara publikacja kasowała i zapisywała dwoma poleceniami, poza transakcją.
Każdy test w klasie `TestAtomowosci` i `TestKolejnosci` odtwarza jedną drogę
do takiego rozjazdu i czerwienił się na starym kodzie.
"""

from unittest.mock import MagicMock, patch

import pytest

import documents.utils.embedding_generator as generator
from accounts.models import Tenant
from documents import tasks
from documents.models import Document, DocumentChunk
from documents.utils.embedding_generator import BLAD_WEKTOROW, generate_embeddings_for_document
from documents.wymiar import WYMIAR_WEKTORA

pytestmark = pytest.mark.django_db

STARA = (
    "Oferta sezonowa.\n\nPrzeglad podstawowy kosztuje 4500 zl i obejmuje regulacje "
    "hamulcow, przerzutek oraz centrowanie kol."
)
SREDNIA = STARA.replace("4500", "4800")
NOWA = STARA.replace("4500", "5200")


def odpowiedz(teksty, brakujacych=0):
    return MagicMock(
        data=[
            MagicMock(index=i, embedding=[0.01] * WYMIAR_WEKTORA)
            for i in range(len(teksty) - brakujacych)
        ]
    )


@pytest.fixture
def klient(monkeypatch):
    """Model embeddingów zastąpiony liczydłem — sprawdzamy publikację, nie OpenAI."""
    udawany = MagicMock()
    udawany.embeddings.create.side_effect = lambda model, input, dimensions: odpowiedz(input)
    monkeypatch.setattr(generator, "get_client", lambda tenant=None: udawany)
    return udawany


def dokument(tresc=STARA):
    firma = Tenant.objects.create(name="Rowerownia", owner_email="x@example.com")
    # processed=False: bez tego sygnał post_save zlecałby własne przeliczenie.
    return Document.objects.create(tenant=firma, name="Cennik", content=tresc, processed=False)


def zmien_tresc(dok, tresc):
    # update(), nie save(): bez sygnałów, tak jak zmiana z innego procesu.
    Document.objects.filter(pk=dok.pk).update(content=tresc)


def tresci(dok):
    return list(
        DocumentChunk.objects.filter(document=dok).order_by("id").values_list("content", flat=True)
    )


class TestAtomowosci:
    def test_przerwany_zapis_zostawia_poprzednie_fragmenty(self, klient):
        """
        Najważniejszy test w tym pliku.

        Stary kod kasował fragmenty, zanim zapisał nowe. Przerwanie w tym
        miejscu - restart workera, błąd bazy, wdrożenie - zostawiało dokument
        z zerem fragmentów przy statusie „gotowe".
        """
        dok = dokument()
        generate_embeddings_for_document(dok)
        zmien_tresc(dok, NOWA)

        with (
            patch.object(
                DocumentChunk.objects, "bulk_create", side_effect=RuntimeError("zapis przerwany")
            ),
            pytest.raises(RuntimeError),
        ):
            generate_embeddings_for_document(dok)

        zostalo = tresci(dok)
        assert zostalo, "Przerwana publikacja zostawila dokument bez fragmentow."
        assert all("4500" in t for t in zostalo)

    def test_za_malo_wektorow_nie_kasuje_niczego(self, klient):
        """
        Model, który zwrócił mniej wektorów niż fragmentów, wywalał
        `zip(strict=True)` już PO skasowaniu starych fragmentów.
        """
        dok = dokument()
        generate_embeddings_for_document(dok)
        zmien_tresc(dok, NOWA)
        klient.embeddings.create.side_effect = lambda model, input, dimensions: odpowiedz(
            input, brakujacych=1
        )

        with pytest.raises(ValueError):
            generate_embeddings_for_document(dok)

        assert all("4500" in t for t in tresci(dok))
        assert tresci(dok)

    def test_tresc_bez_fragmentow_usuwa_fragmenty_poprzedniej_tresci(self, klient, monkeypatch):
        """
        Stary kod kończył funkcję przed kasowaniem, gdy podział nic nie dał -
        więc zostawały fragmenty treści, której nie ma już nigdzie.
        """
        dok = dokument()
        generate_embeddings_for_document(dok)
        zmien_tresc(dok, "cos, co nie daje zadnego fragmentu")
        monkeypatch.setattr(generator, "podziel_na_fragmenty", lambda tresc: [])

        assert generate_embeddings_for_document(dok) == 0
        assert tresci(dok) == []

    def test_dokument_skasowany_w_trakcie_liczenia(self, klient):
        # Zapis fragmentow dla nieistniejacego dokumentu konczyl sie bledem
        # klucza obcego. Skasowanie w trakcie jest zdarzeniem prawidlowym.
        dok = dokument()

        def skasuj_w_trakcie(model, input, dimensions):
            Document.objects.filter(pk=dok.pk).delete()
            return odpowiedz(input)

        klient.embeddings.create.side_effect = skasuj_w_trakcie

        assert generate_embeddings_for_document(dok) == 0
        assert not DocumentChunk.objects.filter(document_id=dok.pk).exists()


class TestKolejnosci:
    def test_starsze_zadanie_nie_nadpisuje_nowszej_publikacji(self, klient):
        """
        Dwa zadania dla tego samego dokumentu publikowały w kolejności
        ZAKOŃCZENIA, nie treści.

        Scenariusz: zadanie dla wersji średniej liczy wektory; w tym czasie
        strona zostaje odświeżona do wersji nowej i nowsze zadanie ją publikuje.
        Starsze kończy później. Stary kod nadpisywał wtedy nowe fragmenty
        średnimi - na stałe, do następnej zmiany na stronie.
        """
        dok = dokument()
        generate_embeddings_for_document(dok)
        zmien_tresc(dok, SREDNIA)

        wykonane = {"nowsze": False}

        def nowsze_zadanie_konczy_pierwsze(model, input, dimensions):
            if not wykonane["nowsze"]:
                wykonane["nowsze"] = True
                zmien_tresc(dok, NOWA)
                generate_embeddings_for_document(dok)
            return odpowiedz(input)

        klient.embeddings.create.side_effect = nowsze_zadanie_konczy_pierwsze

        generate_embeddings_for_document(dok)

        opublikowane = tresci(dok)
        assert any("5200" in t for t in opublikowane)
        assert all("4800" not in t for t in opublikowane), (
            "Starsze zadanie nadpisalo nowsze fragmenty nieaktualna wersja."
        )

    def test_publikuje_to_co_w_bazie_a_nie_obiekt_w_pamieci(self, klient):
        # To, co zapisane, jest tym, co publikujemy. Obiekt przekazany przez
        # wywolujacego moze byc starszy niz wiersz w bazie.
        dok = dokument()
        zmien_tresc(dok, NOWA)

        generate_embeddings_for_document(dok)

        assert any("5200" in t for t in tresci(dok))


class TestPowtarzalnosci:
    def test_niezmieniona_tresc_nie_wola_api(self, klient):
        """
        Zadanie zlecone dwukrotnie albo ponowione po utracie workera nie może
        płacić drugi raz za to samo.
        """
        dok = dokument()
        generate_embeddings_for_document(dok)
        generate_embeddings_for_document(dok)

        assert klient.embeddings.create.call_count == 1

    def test_wymuszenie_przelicza_mimo_braku_zmian(self, klient):
        # Po zmianie modelu albo wymiaru wektora tresci sa identyczne, a wektory
        # trzeba policzyc od nowa. Od tego jest przelicz_fragmenty.
        dok = dokument()
        generate_embeddings_for_document(dok)
        generate_embeddings_for_document(dok, wymus=True)

        assert klient.embeddings.create.call_count == 2

    def test_zmieniona_tresc_wola_api(self, klient):
        dok = dokument()
        generate_embeddings_for_document(dok)
        zmien_tresc(dok, NOWA)
        generate_embeddings_for_document(dok)

        assert klient.embeddings.create.call_count == 2


class TestZadaniaWTle:
    def test_potwierdza_dopiero_po_wykonaniu(self):
        """
        Domyślnie Celery potwierdza zadanie przy odebraniu, więc worker zabity
        w trakcie liczenia gubił je bez śladu.
        """
        assert tasks.generate_embeddings_for_document.acks_late is True
        assert tasks.generate_embeddings_for_document.reject_on_worker_lost is True

    def test_awaria_zostawia_slad_przy_dokumencie(self, klient):
        dok = dokument()
        klient.embeddings.create.side_effect = RuntimeError("API nie odpowiada")

        with pytest.raises(RuntimeError):
            tasks.generate_embeddings_for_document(dok.id)

        dok.refresh_from_db()
        assert dok.processing_error == BLAD_WEKTOROW

    def test_awaria_nie_zaslania_bledu_wyodrebniania(self, klient):
        # Blad odczytu pliku jest wazniejszy: mowi, ze nowy plik sie nie wgral.
        dok = dokument()
        Document.objects.filter(pk=dok.pk).update(processing_error="Plik uszkodzony.")
        klient.embeddings.create.side_effect = RuntimeError("API nie odpowiada")

        with pytest.raises(RuntimeError):
            tasks.generate_embeddings_for_document(dok.id)

        dok.refresh_from_db()
        assert dok.processing_error == "Plik uszkodzony."

    def test_udane_przeliczenie_czysci_tylko_wlasny_komunikat(self, klient):
        dok = dokument()
        Document.objects.filter(pk=dok.pk).update(processing_error=BLAD_WEKTOROW)

        tasks.generate_embeddings_for_document(dok.id)

        dok.refresh_from_db()
        assert dok.processing_error == ""

    def test_udane_przeliczenie_nie_czysci_bledu_wyodrebniania(self, klient):
        dok = dokument()
        Document.objects.filter(pk=dok.pk).update(processing_error="Plik uszkodzony.")

        tasks.generate_embeddings_for_document(dok.id)

        dok.refresh_from_db()
        assert dok.processing_error == "Plik uszkodzony."

    def test_skasowany_dokument_konczy_zadanie_bez_bledu(self):
        tasks.generate_embeddings_for_document(987654321)
