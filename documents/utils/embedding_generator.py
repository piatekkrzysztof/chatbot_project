import textwrap
from documents.models import Document
import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from documents.models import DocumentChunk
from openai import OpenAI
from django.conf import settings

chroma_client = chromadb.Client()
embedding_function = OpenAIEmbeddingFunction(
    api_key=settings.OPENAI_API_KEY,
    model_name="text-embedding-3-small"
)

client = OpenAI(api_key=settings.OPENAI_API_KEY)

CHUNK_SIZE = 500  # znaków
EMBEDDING_MODEL = "text-embedding-3-small"


def split_text(text: str, max_chars: int = 1500) -> list[str]:
    return textwrap.wrap(text, width=max_chars)


def generate_embeddings_for_document(document):
    # Dzielenie tekstu na fragmenty
    chunks = textwrap.wrap(document.content, CHUNK_SIZE)

    # Tworzenie embeddingów
    for chunk in chunks:
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=chunk
        )
        embedding = response.data[0].embedding

        # Zapis do bazy
        DocumentChunk.objects.create(
            document=document,
            content=chunk,
            embedding=embedding
        )
