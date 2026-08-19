"""
Powiadomienie firmy o nowym zapytaniu z czatu.

Zapytanie zostawione w czacie jest najcenniejszą rzeczą, jaką ten produkt
wytwarza — i jedyną, której klient nie zobaczy sam z siebie. Dopóki nie
zajrzy do panelu, nie wie, że ktoś czekał na kontakt.

Dotychczasowa wersja miała trzy dziury:

  • w treści był tylko kontakt i ostatnia wiadomość, więc właściciel dostawał
    numer telefonu bez wiedzy, o co pytający się pytał — a to właśnie kontekst
    decyduje, czy warto oddzwonić w ciągu godziny, czy jutro,
  • wysyłka szła wewnątrz żądania HTTP, więc odwiedzający czekał na
    potwierdzenie tak długo, jak długo trwało łączenie z serwerem poczty,
  • błąd był wyciszony podwójnie: fail_silently=True wewnątrz try/except.
    Zepsuta konfiguracja poczty oznaczała ciszę bez żadnego sygnału.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

logger = logging.getLogger(__name__)

# Rozpoznawalny znacznik przyczyny „nie ma dokąd wysłać". Panel pokazuje przy
# nim inną podpowiedź niż przy awarii wysyłki — to dwa różne problemy i dwa
# różne działania, a wcześniej dostawały jeden komunikat: „sprawdź adres
# e-mail w ustawieniach konta". Przy zepsutej skrzynce nadawczej ta rada
# wysyłała do grzebania w niewłaściwym miejscu.
BRAK_ADRESU = "BRAK_ADRESU: firma nie ma ustawionego adresu e-mail właściciela."

# Ile ostatnich wiadomości wchodzi do maila. Cała rozmowa bywa długa, a do
# decyzji „oddzwonić czy nie" wystarcza ostatni fragment — reszta jest w panelu.
MAX_WIADOMOSCI = 12


def zapis_rozmowy(contact_request):
    """
    Ostatnie wiadomości z rozmowy, w formie czytelnej w kliencie poczty.

    Zwraca pusty napis, gdy rozmowy nie ma: kontakt można zostawić też bez
    wcześniejszej wymiany zdań, a wtedy „brak rozmowy” jest informacją,
    nie błędem.
    """
    rozmowa = contact_request.conversation
    if rozmowa is None:
        return ""

    # Sortowanie po samym znaczniku czasu nie wystarcza: pytanie i odpowiedź
    # zapisane w tej samej chwili dają remis, a przy remisie baza zwraca wiersze
    # w dowolnej kolejności. W mailu wyglądałoby to jak odpowiedź przed
    # pytaniem. Klucz główny rośnie monotonicznie, więc rozstrzyga jednoznacznie.
    wiadomosci = list(
        rozmowa.messages.order_by("-timestamp", "-id")[:MAX_WIADOMOSCI]
    )[::-1]
    if not wiadomosci:
        return ""

    etykiety = {"user": "Klient", "bot": "Chat", "system": "System"}
    wiersze = [
        f"[{w.timestamp.strftime('%H:%M')}] {etykiety.get(w.sender, w.sender)}: {w.message.strip()}"
        for w in wiadomosci
    ]
    return "\n".join(wiersze)


def zbuduj_wiadomosc(contact_request):
    """Treść maila. Najpierw to, co pozwala zadziałać, potem kontekst."""
    zapis = zapis_rozmowy(contact_request)
    panel = f"{settings.FRONTEND_URL.rstrip('/')}/leads"

    czesci = [
        "Ktoś zostawił kontakt w czacie na Twojej stronie.",
        "",
        f"Kontakt:  {contact_request.contact}",
    ]
    if contact_request.name:
        czesci.append(f"Imię:     {contact_request.name}")
    if contact_request.message:
        czesci.append(f"Sprawa:   {contact_request.message}")

    if zapis:
        czesci += [
            "",
            "─── Przebieg rozmowy ───",
            zapis,
        ]
    else:
        czesci += ["", "Kontakt zostawiony bez wcześniejszej rozmowy."]

    czesci += ["", f"Wszystkie zapytania: {panel}"]
    return "\n".join(czesci)


def powiadom_o_zapytaniu(contact_request_id):
    """
    Wysyła powiadomienie i zapisuje wynik przy zapytaniu.

    Wynik zapisujemy zawsze — i sukces, i porażkę. Bez tego nie da się
    odróżnić „powiadomienie doszło" od „poczta nie działa od tygodnia",
    a to jest różnica między spokojem a utraconymi klientami.
    """
    from chat.models import ContactRequest

    try:
        zapytanie = ContactRequest.objects.select_related(
            "tenant", "conversation"
        ).get(pk=contact_request_id)
    except ContactRequest.DoesNotExist:
        logger.warning("Powiadomienie: brak zapytania %s", contact_request_id)
        return

    adres = zapytanie.tenant.owner_email
    if not adres:
        ContactRequest.objects.filter(pk=contact_request_id).update(
            blad_powiadomienia=BRAK_ADRESU
        )
        logger.warning("Powiadomienie %s: firma %s bez adresu e-mail",
                       contact_request_id, zapytanie.tenant_id)
        return

    try:
        # fail_silently=False świadomie: chcemy wyjątek, żeby go zapisać.
        # Wyciszenie sprawiało, że nieudana wysyłka wyglądała jak udana.
        send_mail(
            subject=f"Nowe zapytanie z czatu — {zapytanie.tenant.name}",
            message=zbuduj_wiadomosc(zapytanie),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[adres],
            fail_silently=False,
        )
    except Exception as blad:
        logger.exception("Nie udało się powiadomić o zapytaniu %s", contact_request_id)
        ContactRequest.objects.filter(pk=contact_request_id).update(
            blad_powiadomienia=f"{type(blad).__name__}: {str(blad)[:400]}"
        )
        return

    ContactRequest.objects.filter(pk=contact_request_id).update(
        powiadomiono_at=timezone.now(), blad_powiadomienia=""
    )


def powiadom_o_rozmowie(conversation_id):
    """
    Powiadomienie o rozpoczętej rozmowie — niezależne od tego, czy ktoś
    zostawił kontakt.

    Powstało, bo przejęcie kontaktu ma wąski lejek: propozycja pojawia się
    tylko wtedy, gdy bot nie znalazł odpowiedzi, a odwiedzający musi ją
    jeszcze zauważyć i wypełnić. Rozmowa, która nie skończyła się kontaktem,
    bywa mimo to warta oddzwonienia — o ile ktokolwiek o niej wie.

    Wysyłamy wyłącznie przy PIERWSZEJ wiadomości w rozmowie. Powiadomienie
    po każdej wypowiedzi zamieniłoby dłuższą rozmowę w serię maili.
    """
    from chat.models import Conversation

    try:
        rozmowa = Conversation.objects.select_related("tenant").get(pk=conversation_id)
    except Conversation.DoesNotExist:
        logger.warning("Powiadomienie o rozmowie: brak rozmowy %s", conversation_id)
        return

    adres = rozmowa.tenant.owner_email
    if not adres:
        logger.warning("Powiadomienie o rozmowie %s: firma bez adresu", conversation_id)
        return

    pierwsze = rozmowa.messages.filter(sender="user").order_by("timestamp", "id").first()
    pytanie = pierwsze.message.strip() if pierwsze else "(brak treści)"
    panel = f"{settings.FRONTEND_URL.rstrip('/')}/conversations"

    tresc = "\n".join([
        "Ktoś właśnie zaczął rozmowę z chatem na Twojej stronie.",
        "",
        f"Pierwsze pytanie:  {pytanie}",
        "",
        "Jeśli rozmowa skończy się zostawieniem kontaktu, dostaniesz osobną",
        "wiadomość z całym przebiegiem.",
        "",
        f"Podgląd rozmów: {panel}",
    ])

    try:
        send_mail(
            subject=f"Nowa rozmowa na czacie — {rozmowa.tenant.name}",
            message=tresc,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[adres],
            fail_silently=False,
        )
    except Exception:
        # Bez zapisu przy obiekcie: rozmowa to nie zapytanie, a powiadomienie
        # o niej jest wygodą, nie zobowiązaniem. Log wystarczy, żeby dało się
        # to znaleźć, gdy klient zgłosi brak maili.
        logger.exception("Nie udało się powiadomić o rozmowie %s", conversation_id)
