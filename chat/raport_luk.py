"""
Luki w wiedzy — pytania, na które bot nie umiał odpowiedzieć.

To jedyna rzecz, jaką ten produkt mówi klientowi o jego własnych klientach,
a nie o sobie. Reszta panelu odpowiada na pytanie „czy chatbot działa";
ta lista odpowiada na „czego ludzie chcą, a Ty im tego nie dajesz".

Do niedawna była praktycznie zawsze pusta i nikt tego nie zauważył: źródło
odpowiedzi ustalano po tym, czy wyszukiwarka cokolwiek zwróciła, a ona
zwraca zawsze. Odmowy bota szły więc jako „odpowiedź z dokumentów". Dane są
wiarygodne od momentu, w którym zaczął o tym decydować sam model.

UWAGA na wnioski historyczne: wpisy sprzed tej zmiany mają błędne `source`
i nie da się ich odtworzyć. Wykres luk zaczyna się od tamtej daty, nie od
początku istnienia konta.
"""
from collections import OrderedDict

from django.utils import timezone

from chat.models import PromptLog

# Ile różnych pytań pokazujemy. Lista ma być do przeczytania przy kawie
# i do załatwienia w kwadrans, nie do archiwizacji.
LIMIT_POZYCJI = 15


def luki_w_wiedzy(tenant, od=None, do=None, limit=LIMIT_POZYCJI):
    """
    Pytania bez pokrycia, zgrupowane po treści, najczęstsze na górze.

    Grupowanie jest tu istotą, nie ozdobą. Surowa lista dziesięciu wpisów
    potrafi być jednym pytaniem zadanym dziesięć razy — i wtedy wygląda na
    dziesięć problemów zamiast na jeden, za to pilny. Klient ma zobaczyć,
    CO uzupełnić najpierw.

    Zwraca listę słowników: {"pytanie", "ile", "ostatnio"}.
    """
    wpisy = PromptLog.objects.filter(tenant=tenant, source="gpt")
    if od is not None:
        wpisy = wpisy.filter(created_at__gte=od)
    if do is not None:
        # Granica domknięta z obu stron. Przy `__lt` pytanie zadane w tej samej
        # chwili, w której liczony jest raport, wypadało z niego — wyszło to
        # w teście, bo zegar systemowy potrafi zwrócić dwa razy ten sam
        # znacznik. Skutkiem domknięcia jest to, że pytanie stojące dokładnie
        # na granicy tygodni trafi do dwóch raportów. Powtórzyć pozycję jest
        # znacznie mniej szkodliwie niż ją zgubić: zgubionej nikt nie odzyska.
        wpisy = wpisy.filter(created_at__lte=do)

    # Grupujemy w Pythonie, nie w bazie: klucz to znormalizowana treść
    # (bez różnic w wielkości liter i spacjach), a pokazać chcemy oryginalne
    # brzmienie pierwszego wystąpienia. SQL-owe GROUP BY po samym `prompt`
    # rozbiłoby "Robicie chrzciny?" i "robicie chrzciny ?" na dwie pozycje.
    zgrupowane = OrderedDict()
    for wpis in wpisy.order_by("-created_at").iterator():
        tresc = (wpis.prompt or "").strip()
        if not tresc:
            continue
        klucz = " ".join(tresc.lower().split())
        if klucz in zgrupowane:
            zgrupowane[klucz]["ile"] += 1
        else:
            zgrupowane[klucz] = {
                "pytanie": tresc,
                "ile": 1,
                # Iterujemy od najnowszych, więc pierwsze trafienie jest
                # zarazem ostatnim wystąpieniem tego pytania.
                "ostatnio": wpis.created_at,
            }

    posortowane = sorted(
        zgrupowane.values(), key=lambda p: (-p["ile"], -p["ostatnio"].timestamp())
    )
    return posortowane[:limit]


def okno_tygodnia(teraz=None):
    """Ostatnie siedem dni. Wydzielone, żeby raport i test liczyły tak samo."""
    teraz = teraz or timezone.now()
    return teraz - timezone.timedelta(days=7), teraz


def zbuduj_raport(tenant, luki, od, do):
    """Treść listu. Najpierw to, co do zrobienia, potem skąd się wzięło."""
    from django.conf import settings

    panel = f"{settings.FRONTEND_URL.rstrip('/')}/faq"
    okres = f"{od.strftime('%d.%m')}–{do.strftime('%d.%m.%Y')}"
    razem = sum(pozycja["ile"] for pozycja in luki)

    czesci = [
        f"W okresie {okres} Twój chatbot {razem} razy nie potrafił odpowiedzieć "
        f"na pytanie odwiedzającego.",
        "",
        "Każde z nich to coś, czego ktoś u Ciebie szukał i nie znalazł.",
        "",
        "─── Pytania bez odpowiedzi ───",
    ]

    for pozycja in luki:
        # Krotność z przodu: to ona mówi, co uzupełnić najpierw.
        licznik = f"{pozycja['ile']}×" if pozycja["ile"] > 1 else "  "
        czesci.append(f"{licznik:>4}  {pozycja['pytanie']}")

    czesci += [
        "",
        "Dopisanie odpowiedzi do bazy wiedzy sprawi, że przy kolejnym takim",
        "pytaniu bot poradzi sobie sam.",
        "",
        f"Uzupełnij bazę wiedzy: {panel}",
        "",
        "Ten list wychodzi raz w tygodniu i tylko wtedy, gdy są jakieś luki.",
        "Możesz go wyłączyć w panelu, na pulpicie.",
    ]
    return "\n".join(czesci)


def wyslij_raport(tenant, teraz=None):
    """
    Raport dla jednej firmy. Zwraca True, jeśli list poszedł.

    Milczymy, gdy nie ma luk — i to jest decyzja, nie przeoczenie. List
    „w tym tygodniu nic" przychodzący co poniedziałek uczy odbiorcę omijać
    wzrokiem nadawcę, a wtedy przepadają też te listy, w których coś jest.
    """
    import logging

    from django.conf import settings
    from django.core.mail import send_mail

    logger = logging.getLogger(__name__)

    if not tenant.raport_tygodniowy or not tenant.owner_email:
        return False

    od, do = okno_tygodnia(teraz)
    luki = luki_w_wiedzy(tenant, od=od, do=do)
    if not luki:
        return False

    try:
        send_mail(
            subject=f"{len(luki)} pytań bez odpowiedzi w tym tygodniu — {tenant.name}",
            message=zbuduj_raport(tenant, luki, od, do),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[tenant.owner_email],
            fail_silently=False,
        )
    except Exception:
        # Raport jest wygodą, nie zobowiązaniem — ale jego cisza nie może być
        # niema. Bez tego wpisu nie da się odróżnić „nie było luk" od
        # „poczta nie działa od miesiąca".
        logger.exception("Raport tygodniowy nie poszedł do firmy %s", tenant.id)
        return False

    return True
