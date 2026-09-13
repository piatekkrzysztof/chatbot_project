"""Small sitemap discovery using the same network policy as page imports."""

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from documents.safe_http import (
    _CURRENT_BUDGET,
    FetchError,
    FetchLimitExceeded,
    ResponseTooLarge,
    decompress_gzip,
    fetch_page,
    same_site,
    validate_url,
)

MAX_SITEMAPS = 5
MAX_PAGES = 20

# Człony nazw plików map, po których platformy oznaczają strony stałe (oferta,
# cennik, kontakt) i strony pomocnicze (tagi, kategorie, autorzy). Nazwy
# pochodzą z konwencji WordPressa, Yoast, Rank Math, Shopify i Wix:
# page-sitemap.xml, wp-sitemap-posts-page-1.xml, sitemap_pages_1.xml,
# post_tag-sitemap.xml, wp-sitemap-users-1.xml.
#
# To podpowiedź z nazwy, nie pomiar treści. Dlatego mapa bez rozpoznanej nazwy
# nie jest spychana na koniec, tylko dzieli limit po równo z innymi. Limit
# dwudziestu podstron zostaje - zmienia się wyłącznie to, KTÓRE podstrony
# się w nim mieszczą.
CZLONY_STRON_STALYCH = {"page", "pages"}
CZLONY_STRON_POMOCNICZYCH = {
    "tag",
    "tags",
    "category",
    "categories",
    "taxonomy",
    "taxonomies",
    "author",
    "authors",
    "user",
    "users",
    "format",
}


def priorytet_mapy(url):
    """0 - strony stałe, 1 - bez podpowiedzi, 2 - strony pomocnicze."""
    nazwa = urlsplit(url).path.rsplit("/", 1)[-1].lower()
    czlony = set(re.split(r"[^a-z0-9]+", nazwa))
    if czlony & CZLONY_STRON_POMOCNICZYCH:
        return 2
    if czlony & CZLONY_STRON_STALYCH:
        return 0
    return 1


def wybierz_strony(grupy):
    """
    Łączy adresy z wielu map w listę najwyżej MAX_PAGES.

    Najpierw mapy o wyższym priorytecie; mapy o tym samym priorytecie oddają
    po jednym adresie na kolejkę. Wcześniej adresy brano w kolejności plików,
    więc pierwsza mapa z trzydziestoma wpisami blogowymi zabierała cały limit.
    """
    wybrane, znane = [], set()
    for priorytet in sorted({grupa[0] for grupa in grupy}):
        kolejki = [list(strony) for p, strony in grupy if p == priorytet]
        while kolejki and len(wybrane) < MAX_PAGES:
            for kolejka in kolejki:
                adres = kolejka.pop(0)
                if adres not in znane:
                    znane.add(adres)
                    wybrane.append(adres)
                    if len(wybrane) >= MAX_PAGES:
                        break
            kolejki = [kolejka for kolejka in kolejki if kolejka]
    return wybrane


def sitemap_search(base_url):
    base_url = validate_url(base_url)
    parsed = urlsplit(base_url)
    root_url = urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
    pending = [urljoin(root_url, "sitemap.xml")]
    scheduled = set(pending)
    grupy = []

    def schedule(value, relative_to):
        if len(scheduled) >= MAX_SITEMAPS:
            return
        try:
            value = validate_url(urljoin(relative_to, value))
        except FetchError:
            return
        if same_site(value, base_url) and value not in scheduled:
            scheduled.add(value)
            pending.append(value)

    try:
        robots = fetch_page(urljoin(root_url, "robots.txt"))
        for line in robots.text.splitlines()[:10000]:
            key, separator, value = line.partition(":")
            if separator and key.strip().lower() == "sitemap":
                schedule(value.strip(), robots.url)
    except ResponseTooLarge:
        pass  # robots.txt is optional, an oversized one included.
    except FetchLimitExceeded:
        raise
    except FetchError:
        pass  # robots.txt is optional.

    while pending:
        url = pending.pop(0)
        try:
            response = fetch_page(url)
            body = response.body
            if body.startswith(b"\x1f\x8b"):
                body = decompress_gzip(body)
                budget = _CURRENT_BUDGET.get()
                if budget:
                    budget.consume(max(0, len(body) - len(response.body)))
            tree = ElementTree.fromstring(body, forbid_dtd=True)
        except ResponseTooLarge:
            # Mapa sklepu z tysiącami produktów bywa większa niż limit jednej
            # odpowiedzi. Pomijamy ten plik; wcześniej przerywało to całe
            # pobieranie źródła, zamiast przejść do pozostałych map albo do
            # wyszukiwania podstron po linkach.
            continue
        except FetchLimitExceeded:
            raise
        except (FetchError, ElementTree.ParseError, DefusedXmlException):
            continue
        kind = tree.tag.rsplit("}", 1)[-1]
        if kind not in {"sitemapindex", "urlset"}:
            continue
        adresy = [
            node.text.strip()
            for entry in tree
            for node in entry
            if node.tag.rsplit("}", 1)[-1] == "loc" and node.text
        ]
        if kind == "sitemapindex":
            # Limit plików map obcina indeks. Mapy stron stałych planujemy
            # pierwsze, żeby to one się w nim zmieściły (sortowanie stabilne:
            # w obrębie priorytetu zostaje kolejność z indeksu).
            for adres in sorted(adresy, key=priorytet_mapy):
                schedule(adres, response.url)
            continue
        strony, znane = [], set()
        for adres in adresy:
            try:
                page = validate_url(urljoin(response.url, adres))
            except FetchError:
                continue
            if same_site(page, base_url) and page not in znane:
                znane.add(page)
                strony.append(page)
                if len(strony) >= MAX_PAGES:
                    break
        if strony:
            grupy.append((priorytet_mapy(response.url), strony))
    return wybierz_strony(grupy)
