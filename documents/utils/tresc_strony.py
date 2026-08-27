"""
Wyciąganie treści ze strony klienta.

Do niedawna robiła to wyłącznie `trafilatura`. To biblioteka do wyciągania
treści ARTYKUŁÓW: ocenia, co jest tekstem głównym, a co obudową wokół niego.
Na blogu czy w serwisie informacyjnym działa świetnie. Na stronie sprzedażowej
złożonej z kilkunastu krótkich sekcji marketingowych uznaje niemal wszystko
za obudowę.

Zmierzone na żywej witrynie klienta (znaki, % widocznego tekstu):

                   widoczny   trafilatura     bez obudowy
    /                 10037    257    3%      9506   95%
    /o-nas             3704    735   20%      3056   83%
    /cennik           13964  10155   73%     14508  104%
    /uslugi            3440   1889   55%      2829   82%
    /blog              3651    256    7%      3018   83%

Trzy podstrony z pięciu były w bazie wiedzy praktycznie puste, a w panelu
świeciły zielonym „gotowe". Przełączenie ustawień trafilatury (tabele,
favor_recall, formatowanie) nie zmieniało nic: 257 → 263 znaki. To nie były
ustawienia, tylko sam sposób działania biblioteki.

Bierzemy więc DŁUŻSZY z dwóch wyników. Nie „lepszy" — dłuższy, bo tego da się
dowieść, a „lepszy" wymagałby oceny, której nie umiemy zrobić automatycznie.
Wynik nie może być gorszy niż dotychczasowy, bo stary wariant nadal startuje.
"""

import logging
import re
from typing import NamedTuple

import trafilatura
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Znaczniki, które z definicji nie niosą treści strony.
ZNACZNIKI_OBUDOWY = ("script", "style", "noscript", "nav", "header", "footer", "aside", "form")

# Nazwy klas i identyfikatorów zdradzające obudowę na stronach bez znaczników
# semantycznych — a takich jest większość wśród małych firm, zwłaszcza na
# gotowych motywach WordPressa, gdzie menu to zwykły <div class="navbar">.
#
# Dopasowanie po CAŁYM członie klasy, nie po fragmencie. "header" wycina
# <div class="header">, ale zostawia <div class="header-title">, bo jego
# człony to "header-title" — jeden wyraz, nie pasujący do listy. Dopasowanie
# po fragmencie kasowałoby treść przy każdej klasie zawierającej te litery.
CZLONY_OBUDOWY = {
    "nav",
    "navbar",
    "navigation",
    "menu",
    "mainmenu",
    "main-menu",
    "topbar",
    "header",
    "site-header",
    "page-header",
    "masthead",
    "footer",
    "site-footer",
    "page-footer",
    "colophon",
    "breadcrumb",
    "breadcrumbs",
    "sidebar",
    "widget-area",
    "cookie",
    "cookies",
    "cookie-banner",
    "consent",
    "gdpr",
    "rodo",
    "skip-link",
    "screen-reader-text",
}

# Poniżej tylu znaków uznajemy, że ze strony nic sensownego nie wyszło.
# Ten sam próg co wcześniej — zmiana sposobu wyciągania nie jest okazją,
# żeby po cichu przestawić także to.
MINIMUM_ZNAKOW = 100


def _czy_obudowa(znacznik):
    """Czy element jest nawigacją, stopką albo baterią zgód."""
    if znacznik.name in ZNACZNIKI_OBUDOWY:
        return True
    nazwy = list(znacznik.get("class") or [])
    if znacznik.get("id"):
        nazwy.append(znacznik["id"])
    return any(nazwa.lower() in CZLONY_OBUDOWY for nazwa in nazwy)


def bez_obudowy(html):
    """
    Widoczny tekst strony po odjęciu tego, co powtarza się na każdej podstronie.

    Obudowa musi zniknąć, bo wciągnięta do bazy wiedzy tworzy kilkanaście
    niemal identycznych fragmentów pasujących „po trochu" do każdego pytania.
    Dokładnie ten problem miała sekcja „Kontakt / Porozmawiajmy": była
    najbliższym trafieniem dla pytań o pralki, pogodę i wymianę oleju.
    """
    zupa = BeautifulSoup(html, "html.parser")
    for znacznik in zupa.find_all(_czy_obudowa):
        znacznik.decompose()

    # Znak nowej linii między elementami, nie spacja: podział na fragmenty
    # opiera się na akapitach, więc struktura musi przetrwać ekstrakcję.
    tekst = zupa.get_text("\n")
    tekst = re.sub(r"[ \t]+", " ", tekst)
    tekst = re.sub(r" *\n *", "\n", tekst)
    return re.sub(r"\n{3,}", "\n\n", tekst).strip()


class TrescStrony(NamedTuple):
    """
    Wynik pobrania wraz z miarą, ile ze strony faktycznie wzięliśmy.

    `znakow_widocznych` zapisujemy przy dokumencie, żeby panel mógł powiedzieć
    „wyciągnęliśmy 3% tej strony" zamiast zielonego „gotowe". Przez tygodnie
    strona główna klienta miała w bazie 257 znaków z 10 037 i nic tego nie
    pokazywało — status mówił, że dokument jest przetworzony, bo formalnie był.
    """

    tekst: str
    znakow_widocznych: int


def tekst_widoczny(html):
    """
    Wszystko, co użytkownik zobaczyłby na stronie — bez skryptów i styli.

    Górna granica tego, co ekstrakcja mogłaby wyciągnąć. Zawiera nawigację
    i stopkę, więc nie jest celem samym w sobie; służy za mianownik przy
    ocenie, ile ze strony wzięliśmy.
    """
    zupa = BeautifulSoup(html, "html.parser")
    for znacznik in zupa(["script", "style", "noscript"]):
        znacznik.decompose()
    return re.sub(r"\s+", " ", zupa.get_text(" ")).strip()


def przez_trafilature(html):
    """Dotychczasowa droga. Wygrywa tam, gdzie strona jest artykułem."""
    return (
        trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            include_formatting=False,
        )
        or ""
    ).strip()


def wyciagnij_tresc(html, url=""):
    """
    Treść strony — dłuższy z dwóch wyników — wraz z miarą kompletności.

    Przy zbyt małej treści `tekst` jest pusty; decyzję, co z tym zrobić,
    zostawiamy wywołującemu.
    """
    kandydaci = {
        "bez obudowy": bez_obudowy(html),
        "trafilatura": przez_trafilature(html),
    }
    nazwa = max(kandydaci, key=lambda n: len(kandydaci[n]))
    wybrany = kandydaci[nazwa]

    if len(wybrany) < MINIMUM_ZNAKOW:
        return TrescStrony("", len(tekst_widoczny(html)))

    przegrany = min(kandydaci, key=lambda n: len(kandydaci[n]))
    if len(kandydaci[przegrany]) * 2 < len(wybrany):
        # Duża rozbieżność bywa sygnałem, że strona jest nietypowa. Log, nie
        # ostrzeżenie: to normalne na stronach sprzedażowych, ale przy skardze
        # klienta na braki w wiedzy dobrze mieć ślad, którą drogą poszliśmy.
        logger.info(
            "Pobieranie %s: wybrano '%s' (%d znaków) zamiast '%s' (%d znaków)",
            url or "?",
            nazwa,
            len(wybrany),
            przegrany,
            len(kandydaci[przegrany]),
        )
    return TrescStrony(wybrany, len(tekst_widoczny(html)))
