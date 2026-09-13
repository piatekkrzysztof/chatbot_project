"""
Liczenie wektorów dla fragmentów dokumentu i ich publikacja.

Sam podział siedzi w documents/utils/fragmenty.py — tutaj rozmowa z modelem
embeddingów i zapis do bazy.

Publikacja jest atomowa (F17). Szczegóły i powody: docstring
`generate_embeddings_for_document` oraz docs/atomowa-publikacja-wektorow.md.
"""

import logging

from django.conf import settings
from django.db import transaction
from openai import OpenAI

from documents.models import Document, DocumentChunk
from documents.utils.fragmenty import podziel_na_fragmenty, tekst_do_wektora
from documents.wymiar import WYMIAR_WEKTORA

logger = logging.getLogger(__name__)

# Ile fragmentów wysyłamy w jednym żądaniu. Wcześniej leciało po jednym, więc
# dokument na 40 fragmentów to było 40 osobnych połączeń HTTP — przy pobieraniu
# strony klienta z dwudziestoma podstronami robiło się z tego kilkaset.
# API przyjmuje listę, a limit jest znacznie wyższy; 64 zostawia zapas na
# długie fragmenty, żeby nie przekroczyć limitu tokenów w jednym żądaniu.
ROZMIAR_PARTII = 64

#: Komunikat zapisywany w `processing_error`, gdy przeliczenie się nie udało.
#:
#: Panel pokazuje wtedy status „failed". Bez tego dokument, którego wektory
#: nie powstały, wyglądał na przetworzony - a bot go nie znał albo odpowiadał
#: z jego poprzedniej wersji. Czyścimy WYŁĄCZNIE ten komunikat, nigdy błąd
#: wyodrębniania tekstu: udane przeliczenie starej treści nie znaczy, że nowy
#: plik dał się przeczytać.
BLAD_WEKTOROW = (
    "Nie udało się przeliczyć dokumentu do wyszukiwania. Do czasu ponownej próby "
    "bot korzysta z jego poprzedniej wersji, o ile taka była. Wgraj plik ponownie "
    "albo odśwież stronę źródłową."
)


def get_client(tenant=None):
    """
    Klient OpenAI z kluczem klienta, jeśli go ma.

    Tak samo jak w silniku czatu. Wcześniej ten moduł miał klienta tworzonego
    przy imporcie, z globalnym kluczem — więc klient z własnym kluczem płacił
    za rozmowy, a za przeliczanie własnej bazy wiedzy płaciliśmy my.
    """
    klucz = tenant.openai_api_key if tenant and tenant.openai_api_key else settings.OPENAI_API_KEY
    return OpenAI(api_key=klucz)


def _wektory(klient, teksty):
    """Wektory dla listy tekstów, partiami."""
    wynik = []
    for poczatek in range(0, len(teksty), ROZMIAR_PARTII):
        partia = teksty[poczatek : poczatek + ROZMIAR_PARTII]
        odpowiedz = klient.embeddings.create(
            model=settings.OPENAI_EMBEDDING_MODEL,
            input=partia,
            # Bez tego API oddaje 1536 liczb, a kolumna przyjmuje 512 - zapis
            # konczy sie bledem. To dobra wiadomosc: gorszy bylby wariant,
            # w ktorym cos sie zapisuje i po cichu znaczy co innego.
            dimensions=WYMIAR_WEKTORA,
        )
        # API gwarantuje kolejność, ale sortujemy po indeksie i tak: pomyłka
        # tutaj przypisałaby wektory do niewłaściwych fragmentów, a taki błąd
        # jest niewidoczny — wyszukiwanie po prostu zaczyna zwracać bzdury.
        wynik.extend(pozycja.embedding for pozycja in sorted(odpowiedz.data, key=lambda p: p.index))
    return wynik


def _opublikowane_tresci(document_id):
    """Treść fragmentów, które bot widzi teraz, w kolejności zapisu."""
    return list(
        DocumentChunk.objects.filter(document_id=document_id)
        .order_by("id")
        .values_list("content", flat=True)
    )


def generate_embeddings_for_document(document, wymus=False):
    """
    Przelicza fragmenty dokumentu i publikuje je atomowo.

    Zwraca liczbę fragmentów, które bot widzi dla tego dokumentu po zakończeniu.

    Co było zepsute (F17)
    ---------------------
    Stara wersja kasowała fragmenty i zapisywała nowe dwoma osobnymi
    poleceniami, poza transakcją, i w tej kolejności. Z tego wynikały cztery
    ciche awarie:

    1. Przerwanie między kasowaniem a zapisem - restart workera, błąd bazy,
       wdrożenie - zostawiało dokument z ZEREM fragmentów przy
       `processed=True`. Bot tracił tę wiedzę, a panel pokazywał gotowe.
    2. Model zwracający mniej wektorów niż fragmentów wywalał `zip(strict=True)`
       już PO skasowaniu starych fragmentów - ten sam skutek.
    3. Dwa zadania dla tego samego dokumentu (odświeżenie strony w trakcie
       poprzedniego przeliczenia) publikowały w kolejności ZAKOŃCZENIA, nie
       w kolejności treści. Starsze zadanie, które skończyło później, nadpisywało
       nowsze fragmenty nieaktualnymi - i to już na stałe, do następnej zmiany.
    4. Treść dzieląca się na zero fragmentów kończyła funkcję przed kasowaniem,
       więc zostawały fragmenty POPRZEDNIEJ treści, której nie ma już nigdzie.

    Jak jest teraz
    --------------
    - Migawka treści z BAZY, nie z obiektu podanego przez wywołującego: to,
      co zapisane, jest tym, co publikujemy.
    - Wektory liczymy poza transakcją. Wywołanie API trwa sekundy i nie może
      trzymać blokady wiersza przez ten czas.
    - Publikacja w jednej transakcji, pod `select_for_update` wiersza dokumentu:
      skasowanie i zapis są widoczne dla wyszukiwania naraz albo wcale.
    - Pod blokadą sprawdzamy, czy treść i nazwa są nadal te z migawki. Jeśli nie,
      nie publikujemy - nowszą wersję opublikuje zadanie zlecone przy jej zapisie.

    Powtarzalność
    -------------
    Jeśli opublikowane fragmenty mają dokładnie te treści, które da podział
    obecnej treści, nie wołamy API wcale. Zadanie zlecone dwukrotnie albo
    ponowione po utracie workera kosztuje wtedy zero. `wymus=True` pomija to
    sprawdzenie - używa go `przelicz_fragmenty`, które istnieje właśnie po to,
    żeby przeliczyć mimo braku zmian w treści (inny model, inny wymiar).

    Świadome ograniczenie: porównujemy treść fragmentów, nie ich wektory. Sama
    zmiana NAZWY dokumentu (wchodzi do wektora, nie do treści) nie wywoła
    przeliczenia. Nie wywoływała go też wcześniej - nic nie zleca zadania po
    zmianie nazwy.
    """
    try:
        migawka = Document.objects.select_related("tenant").get(pk=document.pk)
    except Document.DoesNotExist:
        return 0

    tresc = (migawka.content or "").strip()
    fragmenty = podziel_na_fragmenty(tresc) if tresc else []

    if not wymus and _opublikowane_tresci(migawka.pk) == fragmenty:
        return len(fragmenty)

    wektory = []
    if fragmenty:
        klient = get_client(migawka.tenant)
        # Nazwa dokumentu wchodzi do wektora, ale nie do zapisanej treści — patrz
        # tekst_do_wektora. "180 zł od pokoju" znaczy co innego w cenniku hotelu
        # niż w regulaminie parkingu.
        wektory = _wektory(klient, [tekst_do_wektora(f, migawka.name) for f in fragmenty])

    # strict=True PRZED transakcją: model, który zwrócił mniej wektorów niż
    # fragmentów, ma przerwać przeliczenie, zanim cokolwiek zniknie z bazy.
    pary = list(zip(fragmenty, wektory, strict=True))

    with transaction.atomic():
        try:
            biezacy = (
                Document.objects.select_for_update()
                .only("id", "content", "name")
                .get(pk=migawka.pk)
            )
        except Document.DoesNotExist:
            # Skasowany w trakcie liczenia. Fragmenty zniknęły razem z nim
            # (CASCADE); zapis nowych skończyłby się błędem klucza obcego.
            return 0

        if (biezacy.content, biezacy.name) != (migawka.content, migawka.name):
            logger.info(
                "Dokument %s zmienil sie w trakcie liczenia wektorow - pomijam publikacje "
                "nieaktualnej wersji.",
                migawka.pk,
            )
            return DocumentChunk.objects.filter(document_id=migawka.pk).count()

        # Równoległe zadanie mogło w międzyczasie opublikować dokładnie to samo.
        if not wymus and _opublikowane_tresci(migawka.pk) == fragmenty:
            return len(fragmenty)

        DocumentChunk.objects.filter(document_id=migawka.pk).delete()
        DocumentChunk.objects.bulk_create(
            [
                DocumentChunk(document_id=migawka.pk, content=fragment, embedding=wektor)
                for fragment, wektor in pary
            ]
        )
        Document.objects.filter(pk=migawka.pk, processing_error=BLAD_WEKTOROW).update(
            processing_error=""
        )

    if not fragmenty:
        logger.warning(
            "Dokument %s nie ma tresci do wyszukiwania - usunieto jego fragmenty.", migawka.pk
        )
    return len(fragmenty)
