import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from django.conf import settings

embedding_function = OpenAIEmbeddingFunction(
    api_key=settings.OPENAI_API_KEY,
    model_name="text-embedding-3-small"
)

chroma_client = chromadb.Client()


def search_documents_chroma(tenant, message: str, top_k=3) -> list[str]:
    """Zwraca listę najtrafniejszych fragmentów dokumentów z ChromaDB"""
    collection_name = f"tenant_{tenant.id}"
    try:
        collection = chroma_client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_function
        )
        results = collection.query(query_texts=[message], n_results=top_k)
        docs = results.get("documents", [[]])[0]
        return docs if docs else []
    except Exception:
        return []
