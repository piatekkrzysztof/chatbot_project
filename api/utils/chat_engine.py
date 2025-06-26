import logging
import openai
from django.conf import settings
from chat.models import ChatMessage, ChatUsageLog, PromptLog
from rag.engine import query_similar_chunks_pgvector
from openai import OpenAIError
from openai import ChatCompletion
from openai import OpenAI

client = OpenAI()

logger = logging.getLogger(__name__)


def get_openai_response(prompt, model="gpt-3.5-turbo", tenant=None):
    try:
        api_key = tenant.openai_api_key if tenant and tenant.openai_api_key else settings.OPENAI_API_KEY
        client = OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}]
        )

        return {
            "content": response.choices[0].message["content"],
            "tokens": response.usage.total_tokens,
        }

    except openai.OpenAIError as e:
        logger.exception("Błąd w OpenAI: %s", e)
        raise


def process_chat_message(tenant, conversation, message_text):
    """
    Procesuje wiadomość użytkownika w ramach jednej konwersacji.
    Wykonuje fallbacki: regulamin -> RAG -> GPT
    """
    user_message = message_text.strip().lower()

    # 1. Regulamin
    if user_message in ["regulamin", "regulamin."]:
        response_text = tenant.regulamin or "Brak regulaminu."
        ChatMessage.objects.create(
            conversation=conversation,
            sender="bot",
            message=response_text,
            source="manual"
        )
        return {"response": response_text, "source": "manual", "tokens": 0}

    # 2. Zapisz wiadomość użytkownika
    ChatMessage.objects.create(
        conversation=conversation,
        sender="user",
        message=message_text,
        source="manual"
    )

    # 3. Fallback RAG
    try:
        chunks = query_similar_chunks_pgvector(tenant.id, message_text, top_k=5)
    except Exception as e:
        logger.exception("Błąd podczas pobierania chunków: %s", e)
        chunks = []

    if chunks:
        prompt = build_prompt_from_chunks(message_text, chunks)
        try:
            gpt_response = get_openai_response(prompt)
            response_text = gpt_response["content"]
            tokens = gpt_response["tokens"]
        except Exception:
            response_text = "Wystąpił błąd po stronie modelu. Spróbuj ponownie później."
            tokens = 0

        ChatMessage.objects.create(
            conversation=conversation,
            sender="bot",
            message=response_text,
            source="document",
            token_count=tokens
        )
        ChatUsageLog.objects.create(
            tenant=tenant,
            conversation=conversation,
            tokens_used=tokens,
            model_used="gpt-3.5-turbo",
            source="document"
        )

        return {"response": response_text, "source": "document", "tokens": tokens}

    # 4. Fallback GPT
    try:
        fallback_prompt = build_prompt_without_docs(tenant, message_text)
        gpt_response = get_openai_response(fallback_prompt)
        response_text = gpt_response["content"]
        tokens = gpt_response["tokens"]
    except Exception:
        response_text = "Wystąpił błąd po stronie modelu. Spróbuj ponownie później."
        tokens = 0

    ChatMessage.objects.create(
        conversation=conversation,
        sender="bot",
        message=response_text,
        source="gpt",
        token_count=tokens
    )
    ChatUsageLog.objects.create(
        tenant=tenant,
        conversation=conversation,
        tokens_used=tokens,
        model_used="gpt-3.5-turbo",
        source="gpt"
    )
    PromptLog.objects.create(
        tenant=tenant,
        conversation=conversation,
        prompt=fallback_prompt,
        response=response_text,
        source="gpt",
        tokens=tokens,
        model="gpt-3.5-turbo"
    )
    return {"response": response_text, "source": "gpt", "tokens": tokens}


def build_prompt_from_chunks(user_message, chunks):
    """
    Tworzy prompt do GPT na podstawie znalezionych chunków.
    """
    sources = "\n\n".join(chunk.content for chunk in chunks)
    return f"Użytkownik zapytał: '{user_message}'\n\nZnane informacje:\n{sources}"


def build_prompt_without_docs(tenant, user_message):
    """
    Tworzy domyślny prompt do GPT bez dokumentów.
    Uwzględnia gpt_prompt jako kontekst biznesowy firmy.
    """
    prompt_prefix = tenant.gpt_prompt.strip() if tenant.gpt_prompt else f"Klient: {tenant.name}"
    return f"{prompt_prefix}\n\nPytanie: {user_message}"
