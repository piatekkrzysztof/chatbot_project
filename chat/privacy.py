"""
Minimalizacja danych osobowych zbieranych przy rozmowach.

Adres IP odwiedzającego jest daną osobową w rozumieniu RODO, a do niczego w tej
aplikacji nie jest potrzebny w pełnej postaci — służy wyłącznie do odróżnienia
rozmówców. Skracamy go tak, jak robi to anonimizacja IP w narzędziach
analitycznych: ostatni oktet (IPv4) lub końcówka adresu (IPv6) idzie do zera.
"""
import ipaddress

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


def visitor_identifier(request):
    """Anonimowy identyfikator rozmówcy na podstawie żądania."""
    return anonymize_ip(request.META.get("REMOTE_ADDR"))
