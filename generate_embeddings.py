import os
import django
import textwrap
import re
import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chatbot_project.settings")
django.setup()

from documents.models import Document
from accounts.models import Tenant

# Wymagana zmienna środowiskowa
openai_api_key = os.getenv("OPENAI_API_KEY")
assert openai_api_key, "Brak klucza OPENAI_API_KEY w zmiennych środowiskowych"

embedding_function = OpenAIEmbeddingFunction(
    api_key=openai_api_key,
    model_name="text-embedding-3-small"
)

chroma_client = chromadb.Client()

MAX_DOCUMENTS_PER_TENANT = 50
MAX_CHUNKS_PER_DOCUMENT = 20


def clean_text(text: str) -> str:
    """Czyści tekst z nadmiarowych spacji i enterów"""
    text = text.strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def split_text(text, max_chars=1500):
    """Dzieli dokument na kawałki ~1500 znaków (~500 tokenów)"""
    return textwrap.wrap(text, width=max_chars)


def generate_embeddings_for_tenant(tenant: Tenant):
    """Tworzy embeddingi dla dokumentów danego tenant'a"""
    collection_name = f"tenant_{tenant.id}"

    print(f"🧹 Resetuję kolekcję: {collection_name}")
    chroma_client.delete_collection(collection_name)

    collection = chroma_client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_function
    )

    documents = (
        Document.objects
        .filter(tenant=tenant)
        .order_by("-created_at")[:MAX_DOCUMENTS_PER_TENANT]
    )

    for doc in documents:
        if not doc.content:
            continue

        cleaned = clean_text(doc.content)
        chunks = split_text(cleaned)[:MAX_CHUNKS_PER_DOCUMENT]

        if len(chunks) == MAX_CHUNKS_PER_DOCUMENT:
            print(f"⚠️ Dokument '{doc.name}' przycięty do {MAX_CHUNKS_PER_DOCUMENT} chunków.")

        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc.id}-{i}"
            metadata = {
                "tenant_id": tenant.id,
                "document_id": doc.id,
                "document_name": doc.name
            }
            collection.add(
                ids=[chunk_id],
                documents=[chunk],
                metadatas=[metadata]
            )

    print(f"✅ Tenant '{tenant.name}' – przetworzono {len(documents)} dokumentów.")


if __name__ == "__main__":
    tenants = Tenant.objects.all()
    for tenant in tenants:
        generate_embeddings_for_tenant(tenant)
