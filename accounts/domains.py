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
import ipaddress
from urllib.parse import urlparse

from django.conf import settings
from django.db import IntegrityError
from rest_framework.exceptions import PermissionDenied

from accounts.plans import get_plan

# Adresy deweloperskie nie zajmują miejsca w limicie. Klient stawiający stronę
# lokalnie zużyłby na testach jedyną domenę planu Start i zablokował sobie
# wdrożenie produkcyjne — a to najgorszy moment, żeby zobaczyć komunikat o limicie.
#
# Bez nawiasów przy IPv6: urlparse zwraca hostname już rozpakowany, więc wpis
# "[::1]" nigdy się nie dopasowywał i praca po IPv6 na localhoście zjadała
# domenę z pakietu. Adresy prywatne i pętli zwrotnej łapiemy dodatkowo
# rachunkiem, w _adres_lokalny — sama lista nazw ich nie obejmie.
HOSTY_DEWELOPERSKIE = {"localhost", "0.0.0.0"}

# Końcówki zarezerwowane dla pracy lokalnej i sieci domowych (RFC 6761, mDNS).
KONCOWKI_DEWELOPERSKIE = (".localhost", ".local", ".test")

# Nie adresy, tylko wartości, które przeglądarka wysyła zamiast adresu.
# "null" trafia w nagłówku Origin ze stron w piaskownicy (iframe z atrybutem
# sandbox bez allow-same-origin), z plików otwartych z dysku i z części
# przekierowań. Zapisane w rejestrze wyglądało w panelu jak prawdziwa domena
# i nie odpowiadało na jedyne pytanie, do którego ten rejestr służy:
# gdzie faktycznie chodzi widget tego klienta.
NIE_ADRESY = {"null", "undefined", "none", "about", "blank"}


def _adres_lokalny(host):
    """Czy host jest adresem IP z zakresu prywatnego, pętli zwrotnej albo link-local."""
    try:
        adres = ipaddress.ip_address(host)
    except ValueError:
        return False
    return adres.is_private or adres.is_loopback or adres.is_link_local


def wyglada_na_adres_witryny(host):
    """
    Czy to w ogóle może być adres publicznej witryny.

    Nazwa bez kropki nie jest publiczną domeną — to albo host wewnętrzny,
    albo wartość, która adresem nie jest. W obu przypadkach nie ma czego
    odnotowywać, a wpisanie tego do rejestru zabiera klientowi miejsce
    w limicie planu za coś, czego nikt z zewnątrz nie odwiedzi.
    """
    if host in NIE_ADRESY:
        return False
    if host in HOSTY_DEWELOPERSKIE or host.endswith(KONCOWKI_DEWELOPERSKIE):
        return False
    if _adres_lokalny(host):
        return False
    return "." in host


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


def nasz_wlasny_host():
    """
    Host, spod ktorego serwujemy samo okno czatu.

    Widget dziala w ramce wskazujacej na nasz panel, wiec zapytania z jej
    wnetrza nios w naglowku Origin NASZ adres, nie adres klienta. Bez tego
    wykluczenia rejestr zapisywal go jako kolejna witryne klienta: na planie
    z jedna domena klient rejestrowal wlasna strone, a ramka widgetu probowala
    byc druga i dostawala odmowe. Widget tracil wtedy branding i wracal do
    ustawien domyslnych, a klient ogladal w panelu NASZA domene na liscie
    swoich witryn.

    Bierzemy adres z FRONTEND_URL, bo to ta sama wartosc, ktora sluzy za
    zrodlo ramki -- gdy panel przeprowadzi sie pod inny adres, wykluczenie
    przeprowadza sie razem z nim.
    """
    return normalizuj_host(getattr(settings, "FRONTEND_URL", ""))


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

    # Zapytanie z wnetrza ramki widgetu niesie nasz wlasny adres, nie adres
    # klienta. Nie ma tu czego odnotowywac -- to nie jest witryna klienta.
    if host and host == nasz_wlasny_host():
        return ""

    if not wyglada_na_adres_witryny(host):
        # Cicho, bo to nie jest błąd: widget ma działać także w piaskownicy
        # i na localhoście. Po prostu nie ma czego dopisać do rejestru.
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
