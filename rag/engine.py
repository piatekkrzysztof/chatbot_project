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
    tenant_id: int, query: str, top_k: int = 5, max_distance: float = None
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

    results = (
        fragmenty_do_przeszukania(tenant_id)
        .annotate(distance=L2Distance("embedding", query_embedding))
        .filter(distance__lte=max_distance)
        .order_by("distance")[:top_k]
    )

    return list(results)
