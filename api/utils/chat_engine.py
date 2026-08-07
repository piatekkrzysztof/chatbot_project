import json
import logging

import openai
from openai import OpenAI
from rapidfuzz import fuzz
from django.conf import settings

from chat.models import ChatMessage, ChatUsageLog, PromptLog, FAQ
from rag.engine import query_similar_chunks_pgvector

logger = logging.getLogger(__name__)

FALLBACK_MESSAGE = "Wystąpił błąd po stronie modelu. Spróbuj ponownie później."
MAX_FAQ_IN_PROMPT = 20


def get_client(tenant=None):
    api_key = tenant.openai_api_key if tenant and tenant.openai_api_key else settings.OPENAI_API_KEY
    return OpenAI(api_key=api_key)


def build_system_prompt(tenant, chunks, faqs):
    """
    Buduje wiadomość systemową: kim jest bot, co wie o firmie i jak ma się zachowywać.
    Wiedza (dokumenty + FAQ) trafia tutaj, żeby historia rozmowy pozostała czysta.
    """
    parts = [
        f"Jesteś asystentem firmy {tenant.name}. Odpowiadasz klientom na stronie internetowej.",
        "Odpowiadaj po polsku, zwięźle i konkretnie, w uprzejmym tonie.",
        "Opieraj się wyłącznie na wiedzy podanej niżej. Jeśli nie znasz odpowiedzi, "
        "powiedz to wprost i zaproponuj kontakt z firmą — nie zmyślaj.",
    ]

    if tenant.gpt_prompt:
        parts.append(f"\nO firmie:\n{tenant.gpt_prompt.strip()}")

    if faqs:
        faq_text = "\n\n".join(f"P: {f.question}\nO: {f.answer}" for f in faqs)
        parts.append(f"\nNajczęstsze pytania i odpowiedzi:\n{faq_text}")

    if chunks:
        docs_text = "\n\n---\n\n".join(
            f"[Źródło: {chunk.document.name}]\n{chunk.content}" for chunk in chunks
        )
        parts.append(f"\nFragmenty dokumentów firmy:\n{docs_text}")

    if tenant.regulamin:
        parts.append(f"\nRegulamin:\n{tenant.regulamin.strip()}")

    return "\n".join(parts)


def build_history_messages(conversation, limit=None):
    """
    Ostatnie wiadomości konwersacji w formacie OpenAI, od najstarszej do najnowszej.
    Bez tego bot nie rozumie pytań odnoszących się do wcześniejszej części rozmowy.
    """
    limit = limit or settings.CHAT_HISTORY_LIMIT
    # id rozstrzyga remis, gdy kilka wiadomości ma identyczny timestamp
    recent = (
        ChatMessage.objects
        .filter(conversation=conversation)
        .order_by("-timestamp", "-id")[:limit]
    )
    messages = []
    for msg in reversed(list(recent)):
        if msg.sender == "user":
            messages.append({"role": "user", "content": msg.message})
        elif msg.sender == "bot":
            messages.append({"role": "assistant", "content": msg.message})
    return messages


def collect_sources(chunks):
    """Unikalne nazwy dokumentów, z których pochodzi kontekst — do pokazania użytkownikowi."""
    seen, sources = set(), []
    for chunk in chunks:
        name = chunk.document.name
        if name not in seen:
            seen.add(name)
            sources.append(name)
    return sources


def build_chat_messages(tenant, conversation, message_text):
    """
    Składa komplet wiadomości do modelu: system (wiedza) + historia + bieżące pytanie.
    Zwraca też chunki, żeby wywołujący mógł zbudować listę źródeł.
    """
    try:
        chunks = query_similar_chunks_pgvector(tenant.id, message_text, top_k=5)
    except Exception as e:
        logger.exception("Błąd podczas pobierania chunków: %s", e)
        chunks = []

    faqs = list(FAQ.objects.filter(tenant=tenant).order_by("id")[:MAX_FAQ_IN_PROMPT])

    messages = [{"role": "system", "content": build_system_prompt(tenant, chunks, faqs)}]
    messages.extend(build_history_messages(conversation))
    messages.append({"role": "user", "content": message_text})

    return messages, chunks, faqs


def get_openai_response(messages, model=None, tenant=None):
    model = model or settings.OPENAI_CHAT_MODEL
    try:
        response = get_client(tenant).chat.completions.create(
            model=model,
            messages=messages,
        )
        return {
            "content": response.choices[0].message.content,
            "tokens": response.usage.total_tokens,
        }
    except openai.OpenAIError as e:
        logger.exception("Błąd w OpenAI: %s", e)
        raise


def faq_matches_question(faqs, message_text):
    """
    Czy któryś wpis FAQ faktycznie dotyczy zadanego pytania.

    Samo istnienie wpisów FAQ nic nie mówi — bez tego sprawdzenia każda odpowiedź
    u klienta z jednym wpisem FAQ byłaby liczona jako pokryta, a raport
    "pytania bez pokrycia" zostawałby pusty na zawsze.
    """
    threshold = settings.FAQ_MATCH_THRESHOLD
    return any(
        fuzz.token_set_ratio(message_text, faq.question) >= threshold
        for faq in faqs
    )


def determine_source(chunks, faqs, message_text):
    """
    Skąd realnie pochodzi pokrycie odpowiedzi — sterruje raportem luk w wiedzy.
    """
    if chunks:
        return "document"
    if faq_matches_question(faqs, message_text):
        return "faq"
    return "gpt"


def persist_exchange(tenant, conversation, response_text, source, tokens, model, prompt_text):
    """Zapisuje odpowiedź bota wraz z logami zużycia i promptu."""
    ChatMessage.objects.create(
        conversation=conversation,
        sender="bot",
        message=response_text,
        source=source,
        token_count=tokens,
    )
    ChatUsageLog.objects.create(
        tenant=tenant,
        conversation=conversation,
        tokens_used=tokens,
        model_used=model,
        source=source,
    )
    PromptLog.objects.create(
        tenant=tenant,
        conversation=conversation,
        prompt=prompt_text,
        response=response_text,
        source=source,
        tokens=tokens,
        model=model,
    )


def process_chat_message(tenant, conversation, message_text):
    """
    Procesuje wiadomość użytkownika w ramach konwersacji: zapisuje pytanie,
    buduje kontekst (dokumenty + FAQ + historia), odpytuje model i zapisuje odpowiedź.
    """
    model = settings.OPENAI_CHAT_MODEL

    ChatMessage.objects.create(
        conversation=conversation,
        sender="user",
        message=message_text,
        source="manual",
    )

    messages, chunks, faqs = build_chat_messages(tenant, conversation, message_text)
    source = determine_source(chunks, faqs, message_text)

    try:
        gpt_response = get_openai_response(messages, model=model, tenant=tenant)
        response_text = gpt_response["content"]
        tokens = gpt_response["tokens"]
    except Exception:
        response_text = FALLBACK_MESSAGE
        tokens = 0

    persist_exchange(
        tenant, conversation, response_text, source, tokens, model,
        prompt_text=message_text,
    )

    return {
        "response": response_text,
        "source": source,
        "tokens": tokens,
        "sources": collect_sources(chunks),
    }


def _sse(payload):
    """Pojedyncze zdarzenie Server-Sent Events."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def stream_chat_message(tenant, conversation, message_text):
    """
    Wariant strumieniowy: oddaje odpowiedź token po tokenie jako SSE,
    a po zakończeniu strumienia zapisuje ją tak samo jak wersja synchroniczna.
    """
    model = settings.OPENAI_CHAT_MODEL

    ChatMessage.objects.create(
        conversation=conversation,
        sender="user",
        message=message_text,
        source="manual",
    )

    messages, chunks, faqs = build_chat_messages(tenant, conversation, message_text)
    source = determine_source(chunks, faqs, message_text)

    pieces = []
    tokens = 0

    try:
        stream = get_client(tenant).chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
        )
        for event in stream:
            if getattr(event, "usage", None):
                tokens = event.usage.total_tokens
            if event.choices and event.choices[0].delta.content:
                piece = event.choices[0].delta.content
                pieces.append(piece)
                yield _sse({"type": "delta", "content": piece})
    except Exception as e:
        logger.exception("Błąd podczas streamowania odpowiedzi: %s", e)
        if not pieces:
            pieces.append(FALLBACK_MESSAGE)
            yield _sse({"type": "delta", "content": FALLBACK_MESSAGE})

    response_text = "".join(pieces)

    persist_exchange(
        tenant, conversation, response_text, source, tokens, model,
        prompt_text=message_text,
    )

    yield _sse({
        "type": "done",
        "source": source,
        "tokens": tokens,
        "sources": collect_sources(chunks),
    })
