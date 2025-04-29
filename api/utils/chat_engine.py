import openai
import logging
from rag.engine import query_similar_chunks_pgvector

logger = logging.getLogger(__name__)


def build_prompt(user_message, chunks):
    context = "\n\n".join([chunk.content for chunk in chunks])
    return f"Kontekst:\n{context}\n\nPytanie:\n{user_message}"


def get_openai_response(prompt, model="gpt-3.5-turbo"):
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=[{"role": "user", "content": prompt}]
        )
        return {
            "content": response["choices"][0]["message"]["content"],
            "tokens": response["usage"]["total_tokens"]
        }
    except Exception as e:
        logger.exception("Błąd zapytania do OpenAI: %s", str(e))
        raise


def process_chat_message(tenant, conversation, user_message):
    user_message = user_message.strip()

    # Fallback 1: regulamin
    if user_message.lower() in ["regulamin", "regulamin."]:
        return {"response": tenant.regulamin or "Brak regulaminu."}

    # Fallback 2: dokumenty (RAG)
    try:
        chunks = query_similar_chunks_pgvector(tenant.id, user_message, top_k=5)
        if chunks:
            prompt = build_prompt(user_message, chunks)
            gpt_response = get_openai_response(prompt)
            return {"response": gpt_response["content"], "tokens": gpt_response["tokens"], "source": "document"}
    except Exception as e:
        logger.warning("Błąd pobierania chunków dokumentów: %s", str(e))

    # Fallback 3: GPT
    try:
        gpt_response = get_openai_response(user_message)
        return {"response": gpt_response["content"], "tokens": gpt_response["tokens"], "source": "gpt"}
    except Exception as e:
        logger.error("Błąd zapytania do GPT: %s", str(e))
        return {"response": "Wystąpił błąd po stronie modelu. Spróbuj ponownie później.", "tokens": 0, "source": "error"}
