"""
Skąd wiadomo, że bot odpowiedział - i czy w ogóle.

Cały mechanizm wisi na jednym ciągu znaków. Model, który nie potrafi
odpowiedzieć z podanej wiedzy, zaczyna odpowiedź od `[BRAK_ODPOWIEDZI]`.
Znacznik nigdy nie dociera do odwiedzającego - zdejmuje go `ObcinaczZnacznika`
przed wysłaniem - ale od niego zależy:

  • czy widget zaproponuje kontakt z firmą,
  • czy powstanie zapytanie i mail do właściciela,
  • raport luk w wiedzy (`chat/raport_luk.py`),
  • wykres pokrycia na pulpicie,
  • grupowanie w `zmierz_prog_rag`, czyli sposób dobierania progu odległości.

To jest protokół, którego dotrzymuje MODEL, nie kod. Inny model może stawiać
znacznik rzadziej i nic nie krzyknie - po prostu przestaną przychodzić
zapytania od klientów. Mierzy to `manage.py ocen_generowanie`; testy w tym
repozytorium sprawdzają jedynie, czy nasz kod obsługuje znacznik poprawnie.

Wydzielone z chat_engine.py 8 września 2026. Nie dlatego, że tamten plik był
długi, tylko dlatego, że to jest jedno pojęcie z trzema konsumentami, własnymi
testami i własnym sposobem psucia się - a takie rzeczy zasługują na nazwę.
"""

from django.conf import settings
from rapidfuzz import fuzz

from chat.models import ZRODLO_BRAK_WIEDZY, ZRODLO_DOKUMENT, ZRODLO_FAQ, ZRODLO_ROZMOWY

#: Ile wpisów FAQ trafia do promptu przy jednym pytaniu.
#:
#: Sufit kosztu, nie sufit wiedzy: każdy wpis to tokeny płacone przy KAŻDYM
#: pytaniu każdego odwiedzającego. Wybierane są najbardziej pasujące, więc
#: dwudziesty pierwszy wpis klienta nadal może trafić do modelu - o ile to
#: właśnie on odpowiada na zadane pytanie.
MAKS_FAQ_W_PROMPCIE = 20

#: Ile wpisów w ogóle bierzemy pod uwagę przy wybieraniu.
#:
#: Dopasowanie liczy się w Pythonie, więc czytamy wpisy do pamięci - i to jest
#: miejsce, w którym ten sposób się kończy. Do pięciuset wpisów jedno pytanie
#: kosztuje jedno zapytanie do bazy i kilka milisekund porównań; powyżej
#: trzeba przenieść wyszukiwanie do bazy (pg_trgm) albo policzyć FAQ wektorowo,
#: tak jak dokumenty.
#:
#: Powyżej tego pułapu wracamy do kolejności wstawiania, czyli do zachowania
#: sprzed tej poprawki - i to jest świadomy kompromis, nie przeoczenie.
#: Klient z pięciuset wpisami FAQ nie istnieje dzisiaj; gdy się pojawi,
#: `_faq_do_promptu` w chat_engine.py zapisze o tym ostrzeżenie w logu.
MAKS_FAQ_DO_PRZESZUKANIA = 500


def dopasowanie_faq(faq, message_text):
    """Jak bardzo wpis FAQ pasuje do pytania. Jeden scorer dla obu zastosowań."""
    return fuzz.token_set_ratio(message_text, faq.question)


def wybierz_faq(wszystkie, message_text, ile=MAKS_FAQ_W_PROMPCIE):
    """
    Wpisy FAQ, które naprawdę mogą odpowiedzieć na to pytanie.

    Wcześniej było tu `order_by("id")[:20]` i to jest cała treść tej poprawki.
    Klient z dwudziestoma pięcioma wpisami miał pięć, których model NIGDY nie
    widział - kolejność po id jest stała, więc nie chodziło o to, że czasem
    wypadały. Wypadały zawsze.

    Gorzej: ta sama lista rozstrzyga o pokryciu (`faq_matches_question`
    → `determine_source`). Pytanie odpowiadające dwudziestemu trzeciemu wpisowi
    szło więc jako brak wiedzy, lądowało w raporcie luk, a właściciel dostawał
    co tydzień list z poradą „uzupełnij bazę wiedzy" o rzecz, którą miał
    wpisaną. Miara i produkt myliły się tak samo, w tę samą stronę.

    Sortowanie jest stabilne i po ujemnym wyniku, więc przy remisie wygrywa
    wpis wcześniejszy - zachowanie przy zerze dopasowań jest identyczne jak
    dotąd.
    """
    posortowane = sorted(wszystkie, key=lambda faq: -dopasowanie_faq(faq, message_text))
    return posortowane[:ile]


def faq_matches_question(faqs, message_text):
    """
    Czy któryś wpis FAQ faktycznie dotyczy zadanego pytania.

    Samo istnienie wpisów FAQ nic nie mówi — bez tego sprawdzenia każda odpowiedź
    u klienta z jednym wpisem FAQ byłaby liczona jako pokryta, a raport
    "pytania bez pokrycia" zostawałby pusty na zawsze.

    Dostaje TĘ SAMĄ listę, którą zobaczył model. Gdyby liczyła z innego zbioru,
    bot mógłby odpowiedzieć z wpisu FAQ, a źródło i tak poszłoby jako brak
    wiedzy - albo odwrotnie.
    """
    threshold = settings.FAQ_MATCH_THRESHOLD
    return any(dopasowanie_faq(faq, message_text) >= threshold for faq in faqs)


# Model zaczyna od tego ciągu, gdy nie potrafi odpowiedzieć z podanej wiedzy.
# Nigdy nie dociera do odwiedzającego — zdejmujemy go przed wysłaniem.
ZNACZNIK_BRAKU = "[BRAK_ODPOWIEDZI]"


class ObcinaczZnacznika:
    """
    Zdejmuje znacznik z początku strumienia, zanim cokolwiek pójdzie do
    przeglądarki.

    Znacznik stoi na POCZĄTKU odpowiedzi, nie na końcu, właśnie przez
    streaming: koniec przychodzi wtedy, gdy reszta jest już u odwiedzającego.
    Na początku wystarczy wstrzymać kilkanaście pierwszych znaków.
    """

    def __init__(self):
        self._bufor = ""
        self._zdecydowano = False
        # Spacja po znaczniku bywa osobnym tokenem, więc nie zawsze da się ją
        # uciąć razem z nim. Bez tego odpowiedź zaczyna się od spacji.
        self._czekam_na_tresc = False
        self.brak_pokrycia = False

    def podaj(self, kawalek):
        """Fragment gotowy do wysłania — bywa pusty, dopóki trwa rozstrzyganie."""
        if self._zdecydowano:
            if self._czekam_na_tresc:
                kawalek = kawalek.lstrip()
                self._czekam_na_tresc = not kawalek
            return kawalek

        self._bufor += kawalek
        poczatek = self._bufor.lstrip()

        if len(poczatek) < len(ZNACZNIK_BRAKU):
            # Wciąż może się okazać znacznikiem — czekamy na kolejne tokeny
            if ZNACZNIK_BRAKU.startswith(poczatek):
                return ""
            return self._rozstrzygnij(self._bufor)

        if poczatek.startswith(ZNACZNIK_BRAKU):
            self.brak_pokrycia = True
            reszta = poczatek[len(ZNACZNIK_BRAKU) :].lstrip()
            self._czekam_na_tresc = not reszta
            return self._rozstrzygnij(reszta)
        return self._rozstrzygnij(self._bufor)

    def zakoncz(self):
        """Resztka bufora, gdy strumień skończył się w trakcie rozstrzygania.

        Bez tego odpowiedź krótsza niż znacznik ("Tak.") przepadałaby w całości.
        """
        if self._zdecydowano:
            return ""
        return self._rozstrzygnij(self._bufor)

    def _rozstrzygnij(self, tekst):
        self._zdecydowano = True
        self._bufor = ""
        return tekst


def determine_source(chunks, faqs, message_text, brak_pokrycia=False, wyszukiwanie_padlo=False):
    """
    Skąd realnie pochodzi pokrycie odpowiedzi — steruje raportem luk w wiedzy
    i tym, czy widget zaproponuje kontakt z firmą.

    `brak_pokrycia` bije wszystko, bo pochodzi od samego modelu. Wcześniej
    liczyła się wyłącznie niepustość `chunks`, czyli to, czy wyszukiwarka
    cokolwiek zwróciła — a ta zwraca najbliższe fragmenty, nie fragmenty
    trafne. Pytanie o chrzciny w firmie od wesel wyciągało cztery fragmenty
    o weselach: bot uczciwie odmawiał, źródło szło jako "document", widget
    nie proponował kontaktu i zapytanie nie powstawało. Retrieval mierzy
    podobieństwo, nie przydatność.
    """
    if brak_pokrycia:
        return ZRODLO_BRAK_WIEDZY
    # Awaria wyszukiwania to nie jest pogawedka. Pytanie moglo byc prawdziwe,
    # a bot odpowiadal bez bazy wiedzy - to nalezy do raportu luk, nawet gdy
    # model nie postawil znacznika.
    if wyszukiwanie_padlo:
        return ZRODLO_BRAK_WIEDZY
    if chunks:
        return ZRODLO_DOKUMENT
    if faq_matches_question(faqs, message_text):
        return ZRODLO_FAQ

    # Model nie postawil znacznika, a wyszukiwarka nic nie podala. Znaczy to,
    # ze obsluzyl wiadomosc rozmowa: powitanie, podziekowanie, "ok".
    #
    # Do 8 wrzesnia 2026 stalo tu "gpt" i bylo to jedyne dostepne wyjscie -
    # przed znacznikiem brak fragmentow byl JEDYNA przeslanka braku wiedzy.
    # Skutek widac bylo na produkcji: na "czesc, jest tam kto?" widget od razu
    # prosil odwiedzajacego o dane kontaktowe, w pierwszej wymianie zdan,
    # a wpis szedl do raportu luk jako brakujaca wiedza.
    #
    # Ta zmiana jest bezpieczna DOPIERO teraz. Wczoraj model czesto odpowiadal
    # na pytania spoza tematu bez znacznika ("Stolica Australii jest Canberra"),
    # wiec "brak znacznika" nie znaczyl "wszystko w porzadku". Po poprawce
    # promptu znaczy: zmierzone 100% trafnych odmow, `manage.py
    # ocen_generowanie`. Gdyby model to stracil, ten sam pomiar to pokaze.
    return ZRODLO_ROZMOWY
