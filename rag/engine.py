from openai import OpenAI
from documents.models import DocumentChunk
from pgvector.django import L2Distance

client = OpenAI()


def query_similar_chunks_pgvector(tenant_id: int, query: str, top_k: int = 5):
    # Pobieramy embedding zapytania
    embedding_response = client.embeddings.create(
        input=query,
        model="text-embedding-3-small"
    )
    query_embedding = embedding_response.data[0].embedding

    results = (
        DocumentChunk.objects
        .filter(document__tenant_id=tenant_id)
        .annotate(distance=L2Distance("embedding", query_embedding))
        .order_by("distance")[:top_k]
    )

    return list(results)
