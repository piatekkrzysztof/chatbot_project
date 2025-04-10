import textwrap
from documents.models import Document
import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from django.conf import settings

chroma_client = chromadb.Client()
embedding_function = OpenAIEmbeddingFunction(
    api_key=settings.OPENAI_API_KEY,
    model_name="text-embedding-3-small"
)


def split_text(text: str, max_chars: int = 1500) -> list[str]:
    return textwrap.wrap(text, width=max_chars)


def generate_embeddings_for_document(document: Document):
    if not document.content:
        return

    collection_name = f"tenant_{document.tenant.id}"
    collection = chroma_client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_function
    )

    chunks = split_text(document.content)
    for i, chunk in enumerate(chunks):
        chunk_id = f"{document.id}-{i}"
        metadata = {
            "document_id": document.id,
            "tenant_id": document.tenant.id,
            "document_name": document.name
        }
        collection.add(
            ids=[chunk_id],
            documents=[chunk],
            metadatas=[metadata]
        )

    document.processed = True
    document.save()
