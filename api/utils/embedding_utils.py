import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from django.conf import settings

client = chromadb.PersistentClient(path="./chroma_db")


def find_relevant_documents(tenant, user_message, top_k=3):
    collection_name = f"tenant_{tenant.id}_documents"

    embedding_function = OpenAIEmbeddingFunction(
        api_key=tenant.openai_api_key or settings.OPENAI_API_KEY,
        model_name="text-embedding-3-small"
    )

    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_function
    )

    results = collection.query(query_texts=[user_message], n_results=top_k)
    return "\n\n".join(results["documents"][0]) if results["documents"] else ""
