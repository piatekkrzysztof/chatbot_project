from openai import OpenAI
from django.conf import settings
from documents.models import DocumentChunk
from pgvector.django import L2Distance

client = OpenAI()


def query_similar_chunks_pgvector(tenant_id: int, query: str, top_k: int = 5, max_distance: float = None):
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
        model=settings.OPENAI_EMBEDDING_MODEL
    )
    query_embedding = embedding_response.data[0].embedding

    results = (
        DocumentChunk.objects
        # Dokumenty odznaczone przez klienta nie biorą udziału. Fragmenty
        # zostają w bazie, więc włączenie z powrotem działa od razu.
        .filter(document__tenant_id=tenant_id, document__uzywaj_w_wyszukiwaniu=True)
        .annotate(distance=L2Distance("embedding", query_embedding))
        .filter(distance__lte=max_distance)
        .order_by("distance")[:top_k]
    )

    return list(results)
