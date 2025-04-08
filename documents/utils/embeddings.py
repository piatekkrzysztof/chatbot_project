import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from django.conf import settings

client = chromadb.PersistentClient(path="./chroma_db")


def add_document_to_embeddings(tenant, document_text, document_id):
    collection_name = f"tenant_{tenant.id}_documents"

    embedding_function = OpenAIEmbeddingFunction(
        api_key=tenant.openai_api_key or settings.OPENAI_API_KEY,
        model_name="text-embedding-3-small"
    )

    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_function
    )

    collection.add(
        documents=[document_text],
        ids=[str(document_id)]
    )
