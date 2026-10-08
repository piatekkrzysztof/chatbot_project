import re

from django.conf import settings
from openai import OpenAI
from pgvector.django import L2Distance

from documents.models import DocumentChunk
from documents.wymiar import WYMIAR_WEKTORA

client = OpenAI(timeout=settings.CHAT_OPENAI_TIMEOUT_SECONDS, max_retries=0)


def fragmenty_do_przeszukania(tenant_id: int):
    """
    Fragmenty, które wolno przeszukiwać dla danej firmy.

    Wydzielone, bo istniały dwie kopie tego zapytania: tutaj i w komendzie
    zmierz_prog_rag. Filtr wyłączonych dokumentów trafił tylko do jednej,
    więc przyrząd pomiarowy pokazywał stan sprzed zmiany i wyglądało to na
    niedziałający filtr. Bot działał poprawnie, kłamał pomiar — czyli
    najgorszy możliwy układ.
    """
    return DocumentChunk.objects.filter(
        document__tenant_id=tenant_id,
        # Dokumenty odznaczone przez klienta nie biorą udziału. Fragmenty
        # zostają w bazie, więc włączenie z powrotem działa od razu.
        document__uzywaj_w_wyszukiwaniu=True,
    )


def query_similar_chunks_pgvector(
    tenant_id: int, query: str, top_k: int = 5, max_distance: float | None = None
):
    """
    Zwraca fragmenty dokumentów podobne do zapytania.

    Bez progu odległości zapytanie zawsze oddaje `top_k` najbliższych wektorów,
    nawet gdy nie mają nic wspólnego z pytaniem — dlatego odcinamy te powyżej
    `max_distance`, żeby dało się odróżnić trafienie od jego braku.
    """
    if max_distance is None:
        max_distance = settings.RAG_MAX_DISTANCE

    embedding_response = client.embeddings.create(
        input=query,
        model=settings.OPENAI_EMBEDDING_MODEL,
        # Wektor pytania musi byc tak dlugi jak wektory fragmentow. Gdyby
        # ta linia wypadla, Postgres odmowilby liczenia odleglosci miedzy
        # wektorem 1536 a kolumna 512 - czyli bot przestalby odpowiadac
        # na wszystko naraz.
        dimensions=WYMIAR_WEKTORA,
    )
    query_embedding = embedding_response.data[0].embedding

    results = list(
        fragmenty_do_przeszukania(tenant_id)
        .annotate(distance=L2Distance("embedding", query_embedding))
        .filter(distance__lte=max_distance)
        .order_by("distance")[:top_k]
    )

    return dolacz_trafienia_slowne(tenant_id, query, query_embedding, results, top_k)


#: Słowa, które są w pytaniu, ale nie mówią, O CZYM ono jest. Bez nich
#: „Ile kosztuje figurka?" wymagałoby od fragmentu słowa „kosztuje".
#: Tylko słowa od pięciu liter - krótsze i tak są pomijane.
SLOWA_PYTAJACE = frozenset(
    """
    kosztuje kosztują kosztuja kosztować kosztowac koszty kosztów kosztow
    macie możecie mozecie można mozna jakie jakich jakim jakiej który która
    które ktory ktora ktore którzy gdzie kiedy dlaczego proszę prosze chciałbym
    chcialbym chciałabym chcialabym chciałem chcialem chciałam chcialam
    dzień dzien dobry witam pozdrawiam dziękuję dziekuje jestem jesteście
    jestescie oferujecie oferta ofercie państwo panstwo pytanie informacje
    informacji trzeba bardzo takie także takze również rowniez wiecie
    powiedzieć powiedziec
    """.split()
)

#: Do jakiej odległości trafienie po słowach jest jeszcze wiarygodne - druga
#: bariera obok warunku „wszystkie słowa".
#:
#: Pomiar 7.10.2026 (cennik z DOCX, prawdziwe embeddingi): przy 1,05 odpadało
#: „Jakie kwiaty jadalne macie?" (wiersz o 1,068), przy 1,10 trafione 8 z 8.
#: Cisza bez zmian na tym zestawie i na wzorcu rag/ocena. Pytania kontrolne
#: spoza bazy (od 1,07 na produkcji) nie przechodzą, bo nie mają w wiedzy
#: wszystkich swoich słów - sama odległość ich tu nie zatrzymuje.
MAKS_ODLEGLOSC_SLOWNA = 1.10

#: Ile miejsc w wynikach gwarantujemy trafieniom po słowach.
MAKS_TRAFIEN_SLOWNYCH = 2


def slowa_kluczowe(pytanie):
    """
    Rdzenie słów, które niosą temat pytania.

    Polski odmienia rzeczowniki, więc porównujemy początki słów: „złocenia"
    z pytania ma znaleźć „Złocenia" w cenniku, „wypożyczacie" - „wypożyczenie".
    Odcinamy do czterech liter końcówki, ale zostawiamy co najmniej pięć,
    żeby krótkie słowa nie zamieniały się w przypadkowe zlepki liter.
    """
    rdzenie = []
    for slowo in re.findall(r"\w+", (pytanie or "").lower()):
        if len(slowo) < 5 or slowo.isdigit() or slowo in SLOWA_PYTAJACE:
            continue
        rdzen = slowo[: max(5, len(slowo) - 4)]
        if rdzen not in rdzenie:
            rdzenie.append(rdzen)
    return rdzenie


def dolacz_trafienia_slowne(tenant_id, pytanie, wektor, wyniki, top_k):
    """
    Dokłada fragmenty, które zawierają WSZYSTKIE słowa tematu pytania.

    Odbiór 7.10.2026: „Macie złocenia? Ile to kosztuje?" leżało o 1,03 od
    wiersza cennika „Złocenia płatkowym złotem | 60 zł", a „Jakie kwiaty
    jadalne macie?" o 0,99 - oba za progiem, choć słowa z pytania stały
    w dokumencie dosłownie. Model embeddingów słabo łączy krótkie polskie
    pytania z hasłami z tabel; dosłowne słowo jest tu mocniejszym dowodem.

    Warunek „wszystkie słowa", a nie „którekolwiek", pilnuje ciszy: pytanie
    o serwis amortyzatorów nie złapie fragmentu, w którym jest tylko „serwis".
    Trafienia po słowach dostają co najwyżej MAKS_TRAFIEN_SLOWNYCH miejsc,
    resztę wypełniają trafienia wektorowe w dotychczasowej kolejności.
    """
    rdzenie = slowa_kluczowe(pytanie)
    if not rdzenie:
        return wyniki
    zapytanie = fragmenty_do_przeszukania(tenant_id)
    for rdzen in rdzenie:
        zapytanie = zapytanie.filter(content__icontains=rdzen)
    slowne = list(
        zapytanie.annotate(distance=L2Distance("embedding", wektor))
        .filter(distance__lte=MAKS_ODLEGLOSC_SLOWNA)
        .order_by("distance")[:MAKS_TRAFIEN_SLOWNYCH]
    )
    if not slowne:
        return wyniki
    wybrane = {f.pk for f in slowne}
    reszta = [f for f in wyniki if f.pk not in wybrane][: max(0, top_k - len(slowne))]
    return sorted(slowne + reszta, key=lambda f: f.distance)
