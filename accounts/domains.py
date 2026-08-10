"""
Rejestr witryn, na których klient osadził widget.

Cennik obiecuje 1, 3 albo 10 domen, ale nic nie wiedziało, gdzie widgety
faktycznie działają. Rejestrujemy je same, przy pierwszym zapytaniu z danej
witryny: klient nie musi niczego konfigurować, a my zyskujemy policzalny limit
i ochronę klucza API. Klucz jest widoczny w kodzie strony klienta, więc bez tej
listy każdy mógł go skopiować i zużywać cudzy limit u siebie.

Adres bierzemy z nagłówka Origin, którego strona nie może podrobić — nie
z parametru w zapytaniu, bo ten byłby wyłącznie deklaracją.
"""
from urllib.parse import urlparse

from django.db import IntegrityError
from rest_framework.exceptions import PermissionDenied

from accounts.plans import get_plan

# Adresy deweloperskie nie zajmują miejsca w limicie. Klient stawiający stronę
# lokalnie zużyłby na testach jedyną domenę planu Start i zablokował sobie
# wdrożenie produkcyjne — a to najgorszy moment, żeby zobaczyć komunikat o limicie.
HOSTY_DEWELOPERSKIE = {"localhost", "127.0.0.1", "0.0.0.0", "[::1]"}


def normalizuj_host(origin):
    """
    Nazwa hosta z nagłówka Origin: bez schematu, portu, "www" i wielkości liter.

    Bez normalizacji sklep.pl i www.sklep.pl liczyłyby się jako dwie różne
    witryny i klient planu Start wyczerpałby limit na własnej stronie głównej.
    """
    if not origin:
        return ""

    tekst = origin.strip()
    if "//" not in tekst:
        tekst = f"//{tekst}"

    host = (urlparse(tekst).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def limit_domen(tenant):
    """Ile witryn przysługuje firmie. None oznacza brak ograniczenia."""
    subskrypcja = getattr(tenant, "subscription", None)
    plan = get_plan(getattr(subskrypcja, "plan_type", None))
    return plan.max_domains if plan else None


def zarejestruj_domene(tenant, origin):
    """
    Odnotowuje witrynę i pilnuje limitu planu.

    Zwraca nazwę hosta albo pusty napis, gdy nie było czego odnotować (brak
    nagłówka, adres deweloperski). Rzuca PermissionDenied, gdy limit planu
    nie pozwala dołożyć kolejnej witryny.

    Znane witryny przepuszczamy zawsze, także gdy klient zszedł na niższy plan
    i ma ich więcej, niż przewiduje cennik. Wyłączenie działającego widgetu
    na stronie, za którą klient zapłacił w poprzednim miesiącu, byłoby
    dotkliwsze niż odczekanie z egzekwowaniem do kolejnej nowej witryny.
    """
    from accounts.models import WidgetDomain

    host = normalizuj_host(origin)
    if not host or host in HOSTY_DEWELOPERSKIE:
        return ""

    istniejaca = WidgetDomain.objects.filter(tenant=tenant, host=host).first()
    if istniejaca:
        # Odświeżamy last_seen — po tym poznamy witryny, które przestały działać
        istniejaca.save(update_fields=["last_seen"])
        return host

    limit = limit_domen(tenant)
    if limit is not None and WidgetDomain.objects.filter(tenant=tenant).count() >= limit:
        raise PermissionDenied(
            f"Twój plan obejmuje {limit} "
            f"{'witrynę' if limit == 1 else 'witryn'}, a widget działa już na "
            f"tylu. Usuń nieużywaną witrynę w panelu albo przejdź na wyższy plan."
        )

    try:
        WidgetDomain.objects.create(tenant=tenant, host=host)
    except IntegrityError:
        # Dwa równoległe zapytania z tej samej, nowej witryny — druga przegrywa
        # wyścig, ale domena i tak jest już zapisana
        pass
    return host
