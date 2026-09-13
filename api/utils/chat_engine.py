import json
import logging
import time

import openai
from django.conf import settings
from openai import OpenAI

from api.utils.pokrycie import (
    MAKS_FAQ_DO_PRZESZUKANIA,
    ObcinaczZnacznika,
    determine_source,
    wybierz_faq,
)
from api.utils.prompt_systemowy import build_system_prompt
from api.utils.tokens import przytnij_do_budzetu
from chat.models import (
    FAQ,
    ZRODLO_BRAK_WIEDZY,
    ChatMessage,
    ChatUsageLog,
    PromptLog,
)
from documents.utils.queue import enqueue
from rag.engine import query_similar_chunks_pgvector

logger = logging.getLogger(__name__)

FALLBACK_MESSAGE = "Wystąpił błąd po stronie modelu. Spróbuj ponownie później."


def get_client(tenant=None):
    api_key = tenant.openai_api_key if tenant and tenant.openai_api_key else settings.OPENAI_API_KEY
    return OpenAI(api_key=api_key, timeout=settings.CHAT_OPENAI_TIMEOUT_SECONDS, max_retries=0)


def build_history_messages(conversation, limit=None):
    """
    Ostatnie wiadomości konwersacji w formacie OpenAI, od najstarszej do najnowszej.
    Bez tego bot nie rozumie pytań odnoszących się do wcześniejszej części rozmowy.
    """
    limit = limit or settings.CHAT_HISTORY_LIMIT
    # id rozstrzyga remis, gdy kilka wiadomości ma identyczny timestamp
    recent = ChatMessage.objects.filter(conversation=conversation).order_by("-timestamp", "-id")[
        :limit
    ]
    messages = []
    for msg in reversed(list(recent)):
        if msg.sender == "user":
            messages.append({"role": "user", "content": msg.message})
        elif msg.sender == "bot":
            messages.append({"role": "assistant", "content": msg.message})
    return messages


def zrodla_do_pokazania(chunks, source):
    """
    Lista źródeł pod odpowiedzią — pusta, gdy bot nie odpowiedział.

    Na screenie od klienta pod zdaniem „nie posiadam informacji na temat
    organizacji chrzcin" wisiały cztery dokumenty. To nie były źródła
    odpowiedzi, tylko najbliższe trafienia wyszukiwarki — czyli podpis
    pod czymś, czego nie ma.
    """
    # Rozmowa (powitanie) tez nie ma zrodel, ale przez pusta liste fragmentow,
    # nie przez ten warunek - dlatego wystarczy tu samo "brak wiedzy".
    return [] if source == ZRODLO_BRAK_WIEDZY else collect_sources(chunks)


def collect_sources(chunks):
    """
    Źródła odpowiedzi — do pokazania odwiedzającemu pod wiadomością bota.

    Każde źródło to nazwa i adres. Adres bywa pusty i to nie jest brak danych,
    tylko decyzja: wypełniamy go wyłącznie dla stron zaimportowanych z witryny
    klienta, bo tylko one są i tak publiczne. Link do wgranego pliku oznaczałby,
    że każdy odwiedzający pobierze dokument, który klient wgrał wyłącznie po to,
    żeby bot z niego korzystał.
    """
    seen, sources = set(), []
    for chunk in chunks:
        name = chunk.document.name
        if name in seen:
            continue
        seen.add(name)
        sources.append(
            {
                "name": name,
                "url": chunk.document.source_url or "",
            }
        )
    return sources


def _faq_do_promptu(tenant, message_text):
    """
    Wpisy FAQ dla tego pytania - najbardziej pasujące, nie pierwsze z brzegu.

    Czytamy do `MAKS_FAQ_DO_PRZESZUKANIA` wpisów i wybieramy z nich. Powyżej
    tego pułapu wracamy do kolejności wstawiania i mówimy o tym w logu, bo
    wtedy wracają też skutki opisane w `wybierz_faq`.
    """
    wszystkie = list(FAQ.objects.filter(tenant=tenant).order_by("id")[:MAKS_FAQ_DO_PRZESZUKANIA])

    if len(wszystkie) == MAKS_FAQ_DO_PRZESZUKANIA:
        logger.warning(
            "Firma %s ma co najmniej %s wpisow FAQ - powyzej tego pulapu wybieramy "
            "sposrod pierwszych wedlug id, wiec dalsze moga nie trafic do modelu. "
            "Czas przeniesc wyszukiwanie FAQ do bazy albo policzyc je wektorowo.",
            tenant.id,
            MAKS_FAQ_DO_PRZESZUKANIA,
        )

    return wybierz_faq(wszystkie, message_text)


def build_chat_messages(tenant, conversation, message_text):
    """
    Składa komplet wiadomości do modelu: system (wiedza) + historia + bieżące pytanie.

    Zwraca `(wiadomości, fragmenty, faq, wyszukiwanie_padło)`.

    Czwarta wartość istnieje, bo od 8 września pusta lista fragmentów przestała
    znaczyć jedno. Brak trafień to normalny wynik — tak wygląda „dzień dobry".
    Awaria wyszukiwania to co innego: pytanie mogło być prawdziwe, a bot i tak
    odpowiadał bez bazy wiedzy. Bez tego rozróżnienia awaria pgvectora byłaby
    zapisywana jako miła pogawędka i znikała z raportu luk.
    """
    wyszukiwanie_padlo = False
    try:
        chunks = query_similar_chunks_pgvector(tenant.id, message_text, top_k=5)
    except Exception as e:
        logger.exception("Błąd podczas pobierania chunków: %s", e)
        chunks = []
        wyszukiwanie_padlo = True

    faqs = _faq_do_promptu(tenant, message_text)

    messages = [
        {"role": "system", "content": build_system_prompt(tenant, chunks, faqs, message_text)}
    ]
    messages.extend(build_history_messages(conversation))
    messages.append({"role": "user", "content": message_text})

    # Sufit kosztu wejścia. Bez tego prompt rósł z wielkością regulaminu klienta
    # i liczbą wpisów FAQ, a płacimy za każdy token przy każdej wiadomości.
    messages = przytnij_do_budzetu(messages, settings.OPENAI_MAX_INPUT_TOKENS)

    return messages, chunks, faqs, wyszukiwanie_padlo


def parametry_modelu(temperatura=...):
    """
    Parametry wywołania, które rozumieją i stare, i nowe modele.

    Jedno miejsce, bo call sites są dwa - zwykły i strumieniowy - i rozjazd
    między nimi znaczyłby, że czat działa, a strumień pada (albo odwrotnie),
    zależnie od tego, którą ścieżką poszło zapytanie.

    Dwie rzeczy, obie wymuszone przez nowsze modele:

    `max_completion_tokens` zamiast `max_tokens`. Modele od gpt-5.x odrzucają
    `max_tokens` błędem 400 („Use 'max_completion_tokens' instead"), a starsze,
    w tym gpt-4o-mini, przyjmują obie nazwy. Nowa działa więc wszędzie.

    `temperature` wysyłamy tylko wtedy, gdy jest ustawiona. `gpt-5.6-luna`
    odrzuca każdą wartość poza domyślną. Przy pustym `OPENAI_TEMPERATURE`
    parametr nie leci wcale i model używa swojej.

    Sprawdzone 8 września 2026 na gpt-4o-mini i gpt-5.6-luna. To nie jest
    ostrożność na zapas: bez tej poprawki zmiana modelu na nowszy zwracała 400
    przy każdym pytaniu, a `process_chat_message` łapie wyjątek i oddaje
    komunikat awaryjny - czyli bot odpowiadałby „coś poszło nie tak" wszystkim
    klientom naraz i ŻADEN alert by tego nie zgłosił. Wpis w PromptLog szedłby
    ze źródłem „document", bo fragmenty przecież wróciły.
    """
    if temperatura is ...:
        temperatura = settings.OPENAI_TEMPERATURE

    parametry = {"max_completion_tokens": settings.OPENAI_MAX_OUTPUT_TOKENS}
    if temperatura is not None:
        parametry["temperature"] = temperatura
    return parametry


def get_openai_response(messages, model=None, tenant=None, temperatura=...):
    model = model or settings.OPENAI_CHAT_MODEL
    try:
        response = get_client(tenant).chat.completions.create(
            model=model,
            messages=messages,
            **parametry_modelu(temperatura),
        )
        return {
            "content": response.choices[0].message.content,
            "tokens": response.usage.total_tokens,
        }
    except openai.OpenAIError as e:
        logger.exception("Błąd w OpenAI: %s", e)
        raise


def zapisz_pytanie_i_zglos_start(tenant, conversation, message_text):
    """
    Zapisuje wiadomość odwiedzającego i — przy pierwszej w rozmowie —
    zleca powiadomienie właściciela.

    Jeden pomocnik dla obu ścieżek czatu (strumieniowej i zwykłej), bo zapis
    pytania był w nich zduplikowany. Przy dwóch kopiach powiadomienie
    trafiłoby prędzej czy później tylko do jednej.
    """
    # Zadanie importowane lokalnie: chat.tasks ciągnie za sobą Celery,
    # a ten moduł jest importowany przy starcie każdego procesu.
    from chat.tasks import powiadom_o_rozmowie_task

    ChatMessage.objects.create(
        conversation=conversation,
        sender="user",
        message=message_text,
        source="manual",
    )

    if not tenant.powiadom_o_rozmowie:
        return

    # Tylko pierwsza wypowiedź w rozmowie. Bez tego dłuższa wymiana zdań
    # zamieniłaby się w serię maili o tej samej rozmowie.
    czy_pierwsza = ChatMessage.objects.filter(conversation=conversation, sender="user").count() == 1
    if czy_pierwsza:
        enqueue(powiadom_o_rozmowie_task, conversation.id)


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


def process_chat_message(tenant, conversation, message_text, on_billable=None):
    """
    Procesuje wiadomość użytkownika w ramach konwersacji: zapisuje pytanie,
    buduje kontekst (dokumenty + FAQ + historia), odpytuje model i zapisuje odpowiedź.
    """
    model = settings.OPENAI_CHAT_MODEL

    zapisz_pytanie_i_zglos_start(tenant, conversation, message_text)

    messages, chunks, faqs, wyszukiwanie_padlo = build_chat_messages(
        tenant, conversation, message_text
    )

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

    if billable and on_billable:
        on_billable()

    obcinacz = ObcinaczZnacznika()
    response_text = obcinacz.podaj(response_text) + obcinacz.zakoncz()
    source = determine_source(
        chunks, faqs, message_text, obcinacz.brak_pokrycia, wyszukiwanie_padlo
    )

    wiadomosc = persist_exchange(
        tenant,
        conversation,
        response_text,
        source,
        tokens,
        model,
        prompt_text=message_text,
    )

    return {
        "response": response_text,
        "source": source,
        "tokens": tokens,
        "sources": zrodla_do_pokazania(chunks, source),
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
    """Close the provider and persist partial replies even on GeneratorExit."""
    model = settings.OPENAI_CHAT_MODEL
    zapisz_pytanie_i_zglos_start(tenant, conversation, message_text)
    messages, chunks, faqs, wyszukiwanie_padlo = build_chat_messages(
        tenant, conversation, message_text
    )
    obcinacz = ObcinaczZnacznika()
    pieces = []
    tokens = 0
    awaria = False
    charged = False
    stream = None
    deadline = time.monotonic() + settings.CHAT_STREAM_SECONDS

    def charge():
        nonlocal charged
        if not charged and on_billable:
            on_billable()
        charged = True

    try:
        try:
            stream = get_client(tenant).chat.completions.create(
                model=model,
                messages=messages,
                **parametry_modelu(),
                stream=True,
                stream_options={"include_usage": True},
            )
            for event in stream:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Chat stream deadline exceeded")
                if getattr(event, "usage", None):
                    tokens = event.usage.total_tokens
                if event.choices and event.choices[0].delta.content:
                    piece = obcinacz.podaj(event.choices[0].delta.content)
                    if piece:
                        charge()
                        pieces.append(piece)
                        yield _sse({"type": "delta", "content": piece})
        except Exception:
            logger.exception("Błąd podczas streamowania odpowiedzi")
            if not pieces:
                pieces.append(FALLBACK_MESSAGE)
                awaria = True
                yield _sse({"type": "delta", "content": FALLBACK_MESSAGE})

        reszta = "" if awaria else obcinacz.zakoncz()
        if reszta:
            charge()
            pieces.append(reszta)
            yield _sse({"type": "delta", "content": reszta})
    finally:
        if stream is not None:
            close = getattr(stream, "close", None)
            if close:
                try:
                    close()
                except Exception:
                    logger.exception("Could not close OpenAI stream")
        response_text = "".join(pieces)
        source = determine_source(
            chunks, faqs, message_text, obcinacz.brak_pokrycia, wyszukiwanie_padlo
        )
        wiadomosc = persist_exchange(
            tenant,
            conversation,
            response_text,
            source,
            tokens,
            model,
            prompt_text=message_text,
        )

    yield _sse(
        {
            "type": "done",
            "source": source,
            "tokens": tokens,
            "sources": zrodla_do_pokazania(chunks, source),
            "message_id": wiadomosc.id,
        }
    )
