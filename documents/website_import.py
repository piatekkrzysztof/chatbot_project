import os
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from django.db import transaction

from documents.isolated_parser import parse_bytes
from documents.models import Document
from documents.safe_http import (
    FetchError,
    FetchLimitExceeded,
    ResponseTooLarge,
    fetch_page,
    same_site,
    validate_url,
)
from documents.utils.queue import enqueue
from documents.utils.tresc_strony import MINIMUM_ZNAKOW, TrescStrony, wyciagnij_tresc
from documents.validators import sprawdz_limit_bazy_wiedzy, zablokuj_baze_wiedzy

TYPY_HTML = {"text/html", "application/xhtml+xml"}

# Pliki podlinkowane na stronie klienta czytamy tym samym izolowanym parserem
# co upload w panelu. Wcześniej każda odpowiedź szła przez ekstrakcję HTML:
# PDF z cennikiem trafiał do wiedzy jako składnia "%PDF-1.3 ... obj", a zdjęcie
# jako dziesiątki tysięcy znaków zdekodowanych bajtów.
TYPY_PLIKOW = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/markdown": ".md",
    "text/x-markdown": ".md",
    "text/plain": ".txt",
}
TYPY_BEZ_INFORMACJI = {"", "application/octet-stream", "binary/octet-stream"}

# Linki, za którymi nie ma treści do nauki. Pomijamy je przed pobraniem:
# każdy zajmowałby jedno z dwudziestu miejsc na podstrony i jedno żądanie
# z budżetu źródła. Formaty biurowe spoza obsługiwanych (.doc, .xlsx) też tu
# są - parser ich nie przeczyta, więc pobieranie byłoby samym kosztem.
POMIJANE_ROZSZERZENIA = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".avif",
        ".svg",
        ".ico",
        ".bmp",
        ".tif",
        ".tiff",
        ".mp4",
        ".webm",
        ".mov",
        ".avi",
        ".mp3",
        ".wav",
        ".ogg",
        ".zip",
        ".rar",
        ".7z",
        ".gz",
        ".css",
        ".js",
        ".json",
        ".xml",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".doc",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".exe",
        ".dmg",
        ".apk",
    }
)


def _rozszerzenie(url):
    return os.path.splitext(urlsplit(url).path)[1].lower()


def rodzaj_tresci(strona):
    """
    "html", rozszerzenie pliku obsługiwanego przez parser albo None.

    Nagłówek Content-Type ma pierwszeństwo. Gdy go brak albo mówi tylko
    "octet-stream", rozpoznajemy PDF i DOCX po zawartości. Odpowiedź bez
    nagłówka i bez bajtów binarnych dalej traktujemy jak HTML - tak działały
    dotąd wszystkie importy i tak zachowują się stare serwery.
    """
    typ = strona.content_type.split(";", 1)[0].strip().lower()
    rozszerzenie = _rozszerzenie(strona.url)

    if typ in TYPY_HTML:
        return "html"
    if typ == "text/plain" and rozszerzenie == ".md":
        return ".md"
    if typ in TYPY_PLIKOW:
        return TYPY_PLIKOW[typ]
    if typ not in TYPY_BEZ_INFORMACJI:
        return None

    if strona.body.startswith(b"%PDF-"):
        return ".pdf"
    if strona.body.startswith(b"PK\x03\x04"):
        return ".docx" if rozszerzenie == ".docx" else None
    if b"\x00" in strona.body[:1024]:
        return None
    if rozszerzenie in {".txt", ".md"}:
        return rozszerzenie
    return "html" if not typ else None


def fetch_text_from_url(url: str) -> TrescStrony:
    """
    Pobiera tekst ze strony wraz z miarą, ile z niej wzięliśmy.

    Zwraca parę, a nie sam tekst, bo bez mianownika nie da się odróżnić
    „strona jest krótka" od „wyciągnęliśmy z niej 3%". Ta druga sytuacja
    trwała u klienta tygodniami i nie było jej po czym poznać.

    Dla pliku mianownikiem jest cały jego tekst: parser czyta plik w całości,
    nie ma obudowy do odcięcia.
    """
    strona = fetch_page(url)
    if not strona.body:
        raise ValueError(f"Nie udało się pobrać zawartości URL: {url}")

    rodzaj = rodzaj_tresci(strona)
    if rodzaj is None:
        typ = strona.content_type.split(";", 1)[0].strip()[:60] or "nieznany"
        raise ValueError(f"Nieobsługiwany typ treści ({typ}): {url}")

    if rodzaj == "html":
        wynik = wyciagnij_tresc(strona.body, url)
    else:
        tekst = parse_bytes(strona.body, "plik" + rodzaj)
        # Ten sam próg co dla stron: kilka słów z pliku to nie wiedza.
        wynik = TrescStrony(tekst if len(tekst) >= MINIMUM_ZNAKOW else "", len(tekst))

    if not wynik.tekst:
        raise ValueError(f"Zbyt mało treści do wykorzystania z: {url}")

    return wynik


def import_website_as_document(tenant, url: str, name: str = "Strona WWW klienta") -> Document:
    """
    Pobiera podstronę i zapisuje jako Document — zakładając nowy albo
    odświeżając istniejący.

    Wcześniej ta funkcja zawsze zakładała nowy dokument, a zadanie cykliczne
    pomijało adresy, które już były w bazie. Razem znaczyło to, że automatyczne
    odświeżanie z cennika (Grow co 7 dni, Pro codziennie) nie odświeżało
    niczego: bot odpowiadał z wersji pobranej przy pierwszym imporcie, także
    gdy klient dawno zmienił ceny na stronie.

    Rozpoznajemy podstronę po `source_url`, nie po nazwie: nazwę klient może
    zmienić w panelu, adres jest tym, co faktycznie pobieramy.
    """
    text, znakow_widocznych = fetch_text_from_url(url)

    # Pobranie strony trwa poza blokadą; odczyt istniejącej wersji, sprawdzenie
    # limitu i zapis - pod blokadą bazy wiedzy firmy, jak przy uploadzie.
    with transaction.atomic():
        zablokuj_baze_wiedzy(tenant)
        istniejacy = Document.objects.filter(
            tenant=tenant, source="website", source_url=url
        ).first()

        if istniejacy and istniejacy.content == text:
            # Treść bez zmian, ale miara mogła dojść dopiero teraz — zapisujemy ją
            # bez ruszania fragmentów.
            if istniejacy.znakow_na_stronie != znakow_widocznych:
                istniejacy.znakow_na_stronie = znakow_widocznych
                istniejacy.save(update_fields=["znakow_na_stronie"])
            # Strona bez zmian: nie ruszamy fragmentów. Przeliczanie ich co dobę
            # bez powodu kosztowałoby u klienta z planem Pro tyle samo, co realne
            # odświeżenie, a niczego by nie wnosiło.
            return istniejacy

        # Ten sam limit co przy uploadzie. Bez tego dałoby się go obejść, dodając
        # stronę zamiast dokumentu — a crawler potrafi zaciągnąć dziesiątki podstron.
        sprawdz_limit_bazy_wiedzy(
            tenant,
            text,
            zastepowany_tekst=istniejacy.content if istniejacy else "",
        )

        if istniejacy:
            istniejacy.content = text
            istniejacy.name = name
            istniejacy.znakow_na_stronie = znakow_widocznych
            istniejacy.save(update_fields=["content", "name", "znakow_na_stronie"])
            document = istniejacy
        else:
            document = Document.objects.create(
                tenant=tenant,
                name=name,
                content=text,
                source="website",
                # Strona jest publiczna, więc bot może podać do niej link jako źródło
                source_url=url,
                znakow_na_stronie=znakow_widocznych,
            )

    # Zlecenie po zatwierdzeniu zapisu - worker musi już widzieć nową treść.
    # Przeliczenie podmienia fragmenty w jednej transakcji (F17), więc
    # odświeżony dokument nie odpowiada dwiema wersjami naraz.
    # Import w srodku funkcji, zeby przerwac cykl: `documents.tasks` importuje
    # z tego modulu `discover_links_recursively` i `import_website_as_document`.
    #
    # Cykl istnial od dawna i dzialal wylacznie dzieki kolejnosci importow -
    # o ile cokolwiek zaladowalo `documents.tasks` PRZED tym modulem, wszystko
    # sie skladalo. Wyszlo dopiero, gdy posortowanie importow w pliku testu
    # zmienilo te kolejnosc i caly pakiet przestal sie zbierac.
    #
    # Odtworzenie starej kolejnosci naprawiloby objaw. To naprawia przyczyne:
    # w chwili wywolania oba moduly sa juz w calosci zaladowane.
    from documents import tasks

    enqueue(tasks.generate_embeddings_for_document, document.id)
    return document


def discover_links_recursively(base_url: str, max_depth: int = 2, max_pages: int = 20) -> set[str]:
    """
    Heurystyczny crawler: podąża za linkami wewnętrznymi w obrębie jednej domeny.
    """
    normalized_base = validate_url(base_url)
    max_pages = max(0, min(max_pages, 20))
    max_depth = max(0, min(max_depth, 2))
    visited = set()
    # Keep the original root spelling for updates of already imported documents.
    scheduled = {normalized_base}
    to_visit = [(base_url, 0)] if max_pages else []

    while to_visit and len(visited) < max_pages:
        current_url, depth = to_visit.pop()
        if current_url in visited or depth > max_depth:
            continue

        visited.add(current_url)

        try:
            resp = fetch_page(current_url)
        except ResponseTooLarge:
            # Za duża pojedyncza odpowiedź dotyczy tylko tego adresu. Wcześniej
            # był to ten sam błąd co wyczerpany budżet źródła, więc jeden
            # podlinkowany duży plik przerywał wyszukiwanie wszystkich podstron.
            # Adres zostaje na liście: import pokaże klientowi, czego nie pobrano.
            continue
        except FetchLimitExceeded:
            raise
        except FetchError:
            continue

        rodzaj = rodzaj_tresci(resp)
        if rodzaj is None:
            # Nie ma tu czego importować - zwalniamy miejsce na podstronę.
            visited.discard(current_url)
            continue
        if rodzaj != "html" or depth == max_depth:
            # Plik nie ma linków do dalszych podstron.
            continue
        soup = BeautifulSoup(resp.body, "html.parser")
        for link_tag in soup.find_all("a", href=True, limit=200):
            if len(scheduled) >= max_pages:
                break
            href = link_tag["href"]
            try:
                absolute_url = validate_url(urljoin(resp.url, href))
            except FetchError:
                continue
            if _rozszerzenie(absolute_url) in POMIJANE_ROZSZERZENIA:
                continue
            if same_site(absolute_url, base_url) and absolute_url not in scheduled:
                scheduled.add(absolute_url)
                to_visit.append((absolute_url, depth + 1))

    return visited
