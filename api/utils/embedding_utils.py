import openai
import logging

logger = logging.getLogger(__name__)


def get_embedding(text, model="text-embedding-3-small"):
    """
    Pobiera embedding dla pojedynczego tekstu przy użyciu modelu OpenAI.
    """
    try:
        response = openai.Embedding.create(
            input=[text],
            model=model
        )
        return response["data"][0]["embedding"]
    except Exception as e:
        logger.exception("Błąd podczas generowania embeddingu: %s", str(e))
        raise ValueError(f"Błąd generowania embeddingu: {e}")


def prepare_document_chunks_for_embedding(chunks):
    """
    Przygotowuje listę tekstów z chunków dokumentu do embeddingu.
    """
    return [chunk.content for chunk in chunks]

