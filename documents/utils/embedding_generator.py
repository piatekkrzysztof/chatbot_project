"""
Liczenie wektorów dla fragmentów dokumentu.

Sam podział siedzi w documents/utils/fragmenty.py — tutaj tylko rozmowa
z modelem embeddingów i zapis do bazy.
"""
import logging

from django.conf import settings
from openai import OpenAI

from documents.models import DocumentChunk
from documents.utils.fragmenty import podziel_na_fragmenty, tekst_do_wektora

logger = logging.getLogger(__name__)

# Ile fragmentów wysyłamy w jednym żądaniu. Wcześniej leciało po jednym, więc
# dokument na 40 fragmentów to było 40 osobnych połączeń HTTP — przy pobieraniu
# strony klienta z dwudziestoma podstronami robiło się z tego kilkaset.
# API przyjmuje listę, a limit jest znacznie wyższy; 64 zostawia zapas na
# długie fragmenty, żeby nie przekroczyć limitu tokenów w jednym żądaniu.
ROZMIAR_PARTII = 64


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
        partia = teksty[poczatek:poczatek + ROZMIAR_PARTII]
        odpowiedz = klient.embeddings.create(
            model=settings.OPENAI_EMBEDDING_MODEL,
            input=partia,
        )
        # API gwarantuje kolejność, ale sortujemy po indeksie i tak: pomyłka
        # tutaj przypisałaby wektory do niewłaściwych fragmentów, a taki błąd
        # jest niewidoczny — wyszukiwanie po prostu zaczyna zwracać bzdury.
        wynik.extend(pozycja.embedding for pozycja in sorted(odpowiedz.data, key=lambda p: p.index))
    return wynik


def generate_embeddings_for_document(document):
    """
    Przelicza fragmenty dokumentu od nowa.

    Idempotentne: stare fragmenty najpierw znikają. Bez tego ponowne wywołanie
    (po odświeżeniu treści ze strony klienta) dokładało drugi komplet, a bot
    odpowiadał z obu wersji naraz — także z tej nieaktualnej.
    """
    tresc = (document.content or "").strip()
    if not tresc:
        logger.warning("Dokument %s nie zawiera treści — pomijam wektory.", document.id)
        DocumentChunk.objects.filter(document=document).delete()
        return 0

    fragmenty = podziel_na_fragmenty(tresc)
    if not fragmenty:
        return 0

    klient = get_client(getattr(document, "tenant", None))
    # Nazwa dokumentu wchodzi do wektora, ale nie do zapisanej treści — patrz
    # tekst_do_wektora. "180 zł od pokoju" znaczy co innego w cenniku hotelu
    # niż w regulaminie parkingu.
    wektory = _wektory(klient, [tekst_do_wektora(f, document.name) for f in fragmenty])

    DocumentChunk.objects.filter(document=document).delete()
    DocumentChunk.objects.bulk_create([
        DocumentChunk(document=document, content=fragment, embedding=wektor)
        for fragment, wektor in zip(fragmenty, wektory)
    ])
    return len(fragmenty)
