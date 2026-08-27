"""
CORS dla publicznych endpointów widgetu.

Reszta API ma zamkniętą listę dozwolonych adresów, bo odpytuje ją wyłącznie
nasz panel. Widget jest odwrotnością tego założenia: siedzi na witrynach
klientów, których adresów z góry nie znamy i które zmieniają się bez naszego
udziału. Zamknięta lista oznaczała, że przeglądarka odwiedzającego blokowała
zapytanie `embed.js` o ustawienia — czyli wiadomość proaktywna nie pokazywała
się u nikogo poza środowiskiem deweloperskim, gdzie CORS przepuszcza wszystko.

Otwarcie tych ścieżek nie jest luką: uwierzytelnia je klucz API w nagłówku,
a nie pochodzenie żądania. Nagłówek Origin służy do czego innego — pozwala
policzyć i ograniczyć witryny, na których klient osadził widget (api.domains).
"""

from corsheaders.signals import check_request_enabled

# Ścieżki wołane z witryn klientów. Celowo wyliczone, a nie prefiks "/api/":
# przypadkowe otwarcie panelu na dowolne pochodzenie byłoby cichym błędem.
SCIEZKI_WIDGETU = (
    "/api/widget-settings/",
    "/api/widget/chat/",
    "/api/widget/chat/stream/",
    "/api/widget/feedback/",
    "/api/widget/contact/",
    "/api/widget/faq/",
    # Strona sprzedażowa może stać pod innym adresem niż panel
    "/api/billing/cennik/",
)


def zezwol_na_widget(sender, request, **kwargs):
    """Sygnał django-cors-headers: dowolne pochodzenie dla ścieżek widgetu."""
    return request.path in SCIEZKI_WIDGETU


def podepnij():
    check_request_enabled.connect(zezwol_na_widget)
