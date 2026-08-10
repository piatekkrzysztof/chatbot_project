import json
import logging

import openai
from openai import OpenAI
from rapidfuzz import fuzz
from django.conf import settings

from accounts.models import WIDGET_LANGUAGE_ADVERBS
from api.utils.language import jezyk_odpowiedzi
from api.utils.tokens import przytnij_do_budzetu
from chat.models import ChatMessage, ChatUsageLog, PromptLog, FAQ
from rag.engine import query_similar_chunks_pgvector

logger = logging.getLogger(__name__)

FALLBACK_MESSAGE = "Wystąpił błąd po stronie modelu. Spróbuj ponownie później."
MAX_FAQ_IN_PROMPT = 20


def get_client(tenant=None):
    api_key = tenant.openai_api_key if tenant and tenant.openai_api_key else settings.OPENAI_API_KEY
    return OpenAI(api_key=api_key)


def has_company_knowledge(tenant, chunks, faqs):
    """
    Czy do tej odpowiedzi bot ma jakąkolwiek wiedzę o firmie.

    Liczy się wszystko, co realnie trafia do promptu — opis firmy, regulamin,
    dopasowane fragmenty dokumentów i wpisy FAQ. Pusto oznacza, że model
    odpowiadałby wyłącznie z własnych domysłów.
    """
    return bool(tenant.gpt_prompt or tenant.regulamin or chunks or faqs)


def language_instruction(tenant, message=None):
    """
    W jakim języku bot ma odpowiadać.

    Prompt miał wcześniej zaszyte "odpowiadaj po polsku", więc anglojęzyczny
    odwiedzający dostawał polską odpowiedź na angielskie pytanie.

    Instrukcja wskazuje zawsze JEDEN język, nigdy listy dozwolonych. Wersje
    opisujące listę wypadały na modelu niestabilnie: albo lustrzanie dopasowywał
    język pytania i ignorował listę klienta, albo zwijał wszystko do domyślnego
    i ignorował zezwolenie. Wybór należy więc do kodu (api.utils.language),
    a model dostaje gotową decyzję.
    """
    domyslny = tenant.default_language()
    if tenant.uses_fixed_language() or not message:
        kod = domyslny
    else:
        kod = jezyk_odpowiedzi(message, tenant.languages(), domyslny)
    forma = WIDGET_LANGUAGE_ADVERBS[kod]
    return f"Odpowiadaj wyłącznie {forma}, niezależnie od języka pytania."


def build_system_prompt(tenant, chunks, faqs, message=None):
    """
    Buduje wiadomość systemową: kim jest bot, co wie o firmie i jak ma się zachowywać.
    Wiedza (dokumenty + FAQ) trafia tutaj, żeby historia rozmowy pozostała czysta.

    `message` to bieżące pytanie odwiedzającego — potrzebne wyłącznie do
    ustalenia języka odpowiedzi. Bez niego prompt wychodzi w języku domyślnym.
    """
    parts = [
        f"Jesteś asystentem firmy {tenant.name}. Odpowiadasz klientom na stronie internetowej.",
        "Odpowiadaj zwięźle i konkretnie, w uprzejmym tonie.",
        language_instruction(tenant, message),
        # Sama instrukcja "nie zmyślaj" nie wystarcza: model odmawia przy pytaniach
        # o ceny czy godziny, ale na "czym zajmuje się wasza firma?" wnioskuje profil
        # działalności z samej nazwy i podaje go jako fakt. Dlatego ta klasa pytań
        # jest tu wymieniona wprost.
        "Opieraj się wyłącznie na wiedzy podanej niżej. Jeśli odpowiedź nie wynika "
        "z niej wprost, powiedz że nie masz tej informacji i zaproponuj kontakt z firmą.",
        "Nigdy nie zgaduj na podstawie nazwy firmy ani ogólnej wiedzy o branży. "
        "Dotyczy to zwłaszcza pytań o to, czym firma się zajmuje, co oferuje, "
        "jakie ma ceny, godziny otwarcia i zasady — o tym wypowiadasz się tylko wtedy, "
        "gdy wynika to z wiedzy podanej niżej.",
    ]

    if not has_company_knowledge(tenant, chunks, faqs):
        # Bez tego bloku model dostaje pusty prompt z samą nazwą firmy i wypełnia
        # lukę własnymi domysłami — na stronie klienta wygląda to jak wymyślona oferta.
        parts.append(
            "\nUWAGA: nie masz żadnych informacji o tej firmie. Na każde pytanie "
            "dotyczące jej działalności, oferty lub zasad odpowiedz wprost, że nie "
            "posiadasz tych informacji, i poproś o kontakt z firmą. Możesz jedynie "
            "uprzejmie się przywitać i podtrzymać rozmowę. Samą odmowę napisz "
            "w języku wskazanym wyżej, nie zawsze po polsku."
        )

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

    messages = [{"role": "system", "content": build_system_prompt(tenant, chunks, faqs, message_text)}]
    messages.extend(build_history_messages(conversation))
    messages.append({"role": "user", "content": message_text})

    # Sufit kosztu wejścia. Bez tego prompt rósł z wielkością regulaminu klienta
    # i liczbą wpisów FAQ, a płacimy za każdy token przy każdej wiadomości.
    messages = przytnij_do_budzetu(messages, settings.OPENAI_MAX_INPUT_TOKENS)

    return messages, chunks, faqs


def get_openai_response(messages, model=None, tenant=None):
    model = model or settings.OPENAI_CHAT_MODEL
    try:
        response = get_client(tenant).chat.completions.create(
            model=model,
            messages=messages,
            temperature=settings.OPENAI_TEMPERATURE,
            max_tokens=settings.OPENAI_MAX_OUTPUT_TOKENS,
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
    """
    Zapisuje odpowiedź bota wraz z logami zużycia i promptu.

    Zwraca zapisaną wiadomość, bo widget potrzebuje jej identyfikatora,
    żeby dało się tę konkretną odpowiedź ocenić kciukiem.
    """
    wiadomosc = ChatMessage.objects.create(
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

    return wiadomosc


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

    # Nieudane wywołanie modelu nie może kosztować klienta wiadomości z planu.
    # Wcześniej widok naliczał bezwarunkowo, więc awaria po naszej stronie
    # zjadała limit, za który klient zapłacił, i zwracała komunikat o błędzie.
    billable = True
    try:
        gpt_response = get_openai_response(messages, model=model, tenant=tenant)
        response_text = gpt_response["content"]
        tokens = gpt_response["tokens"]
    except Exception:
        response_text = FALLBACK_MESSAGE
        tokens = 0
        billable = False

    wiadomosc = persist_exchange(
        tenant, conversation, response_text, source, tokens, model,
        prompt_text=message_text,
    )

    return {
        "response": response_text,
        "source": source,
        "tokens": tokens,
        "sources": collect_sources(chunks),
        "message_id": wiadomosc.id,
        # Zdejmowane przez widok — to informacja rozliczeniowa, nie treść dla widgetu
        "billable": billable,
    }


def split_billing(result):
    """
    Rozdziela wynik na treść dla klienta i informację rozliczeniową.

    Celowo bez mutowania wejścia: `result.pop(...)` w widoku wyglądał niewinnie,
    ale zjadał pole ze słownika współdzielonego przez kolejne wywołania i przez
    to gubił naliczenia.
    """
    payload = {klucz: wartosc for klucz, wartosc in result.items() if klucz != "billable"}
    return payload, bool(result.get("billable"))


def _sse(payload):
    """Pojedyncze zdarzenie Server-Sent Events."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def stream_chat_message(tenant, conversation, message_text, on_billable=None):
    """
    Wariant strumieniowy: oddaje odpowiedź token po tokenie jako SSE,
    a po zakończeniu strumienia zapisuje ją tak samo jak wersja synchroniczna.

    `on_billable` wywołujemy dopiero wtedy, gdy odwiedzający realnie dostał
    treść od modelu. Rozliczenie musi dziać się tutaj, w generatorze: widok
    kończy się, zanim strumień zostanie skonsumowany, więc nie ma jak sprawdzić
    wyniku po fakcie. Sam limit jest egzekwowany wcześniej, w middleware —
    to dwie różne rzeczy i wcześniej były mylone.
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
            temperature=settings.OPENAI_TEMPERATURE,
            max_tokens=settings.OPENAI_MAX_OUTPUT_TOKENS,
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

    # Urwany strumień też się liczy: odwiedzający zobaczył treść od modelu,
    # a my zapłaciliśmy za tokeny. Nie liczy się wyłącznie sama awaria,
    # po której poszedł jedynie komunikat zastępczy.
    billable = bool(pieces) and response_text != FALLBACK_MESSAGE
    if billable and on_billable:
        on_billable()

    wiadomosc = persist_exchange(
        tenant, conversation, response_text, source, tokens, model,
        prompt_text=message_text,
    )

    yield _sse({
        "type": "done",
        "source": source,
        "tokens": tokens,
        "sources": collect_sources(chunks),
        "message_id": wiadomosc.id,
    })
