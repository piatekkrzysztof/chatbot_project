"""
Minimalizacja danych osobowych zbieranych przy rozmowach.

Adres IP odwiedzającego jest daną osobową w rozumieniu RODO, a do niczego w tej
aplikacji nie jest potrzebny w pełnej postaci — służy wyłącznie do odróżnienia
rozmówców. Skracamy go tak, jak robi to anonimizacja IP w narzędziach
analitycznych: ostatni oktet (IPv4) lub końcówka adresu (IPv6) idzie do zera.
"""

import ipaddress

from django.conf import settings

UNKNOWN = "unknown"


def anonymize_ip(raw):
    """
    Adres IP pozbawiony części identyfikującej konkretne urządzenie.

    Nierozpoznane wartości sprowadzamy do "unknown" zamiast zapisywać w oryginale —
    nagłówek od proxy potrafi zawierać listę adresów albo śmieci, a przechowywanie
    czegokolwiek niesprawdzonego w tym polu mija się z celem minimalizacji.
    """
    if not raw:
        return UNKNOWN

    try:
        address = ipaddress.ip_address(raw.strip())
    except ValueError:
        return UNKNOWN

    if address.version == 4:
        network = ipaddress.ip_network(f"{address}/24", strict=False)
    else:
        network = ipaddress.ip_network(f"{address}/64", strict=False)

    return str(network.network_address)


def client_ip(request):
    """
    Adres odwiedzającego, poprawnie odczytany zza serwerów pośredniczących.

    Na Renderze ruch idzie przez Cloudflare i load balancer, więc REMOTE_ADDR
    to adres proxy, a nie odwiedzającego — wszyscy wyglądaliby wtedy identycznie.
    Prawdziwy adres jest w X-Forwarded-For, ale nagłówka nie wolno czytać naiwnie:
    klient może go podrobić, a proxy tylko dopisuje kolejne wpisy na końcu listy.

    Wiarygodne są wyłącznie wpisy dopisane przez nasze własne proxy, czyli
    TRUSTED_PROXY_DEPTH ostatnich. Ten najbardziej zewnętrzny z nich zawiera
    faktyczny adres klienta — stąd indeks liczony od końca. Wszystko przed nim
    pochodzi od klienta i jest bezwartościowe.

    TRUSTED_PROXY_DEPTH=0 oznacza brak proxy (środowisko lokalne) i wtedy
    jedynym wiarygodnym źródłem jest REMOTE_ADDR.
    """
    remote_addr = request.META.get("REMOTE_ADDR")
    depth = getattr(settings, "TRUSTED_PROXY_DEPTH", 0)

    if depth <= 0:
        return remote_addr

    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if not forwarded:
        # Nagłówka brak mimo skonfigurowanego proxy — na przykład wywołanie
        # wprost do usługi z pominięciem load balancera
        return remote_addr

    adresy = [wpis.strip() for wpis in forwarded.split(",") if wpis.strip()]
    if not adresy:
        return remote_addr

    return adresy[-min(depth, len(adresy))]


def visitor_identifier(request):
    """Anonimowy identyfikator rozmówcy na podstawie żądania."""
    return anonymize_ip(client_ip(request))
