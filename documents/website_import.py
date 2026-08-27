import requests
import trafilatura
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from documents.models import Document
from documents.validators import sprawdz_limit_bazy_wiedzy
from documents.utils.queue import enqueue
from documents.utils.tresc_strony import TrescStrony, wyciagnij_tresc
from documents import tasks


def fetch_text_from_url(url: str) -> TrescStrony:
    """
    Pobiera tekst ze strony wraz z miarą, ile z niej wzięliśmy.

    Zwraca parę, a nie sam tekst, bo bez mianownika nie da się odróżnić
    „strona jest krótka" od „wyciągnęliśmy z niej 3%". Ta druga sytuacja
    trwała u klienta tygodniami i nie było jej po czym poznać.
    """
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise ValueError(f"Nie udało się pobrać zawartości URL: {url}")

    wynik = wyciagnij_tresc(downloaded, url)

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
    istniejacy = Document.objects.filter(tenant=tenant, source="website", source_url=url).first()

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

    # Przeliczenie jest idempotentne — stare fragmenty znikają przed nowymi,
    # więc odświeżony dokument nie odpowiada dwiema wersjami naraz.
    enqueue(tasks.generate_embeddings_for_document, document.id)
    return document


def discover_links_recursively(base_url: str, max_depth: int = 2, max_pages: int = 20) -> set[str]:
    """
    Heurystyczny crawler: podąża za linkami wewnętrznymi w obrębie jednej domeny.
    """
    visited = set()
    to_visit = [(base_url, 0)]
    base_domain = urlparse(base_url).netloc

    while to_visit and len(visited) < max_pages:
        current_url, depth = to_visit.pop()
        if current_url in visited or depth > max_depth:
            continue

        visited.add(current_url)

        try:
            resp = requests.get(current_url, timeout=5)
            resp.raise_for_status()
        except Exception:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        for link_tag in soup.find_all("a", href=True):
            href = link_tag["href"]
            absolute_url = urljoin(current_url, href)
            parsed = urlparse(absolute_url)

            if parsed.netloc == base_domain and parsed.scheme.startswith("http"):
                to_visit.append((absolute_url, depth + 1))

    return visited
