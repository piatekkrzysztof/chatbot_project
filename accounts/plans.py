"""
Katalog planów — jedno źródło prawdy o cenach, limitach i uprawnieniach.

Dotąd limit wiadomości był luźnym polem na subskrypcji, a to, co klient kupił,
zapisywało się jako dowolny tekst ("pro", "Prymium"). Nic nie łączyło zakupu
z faktycznym limitem: webhook Stripe ustawiał plan na Tenant, a limity
egzekwował zupełnie inny model.

Ceny i limity pochodzą z badania rynku (sierpień 2026). Punkt odniesienia:
ChatBotXL Standard to 149 zł za 500 wiadomości, więc nasz START za tę samą
cenę daje czterokrotnie większy limit — to główny argument sprzedażowy.

Ceny podane w złotych netto. Rozliczenie prowadzi Stripe po stronie swoich
cenników; identyfikatory cen trzymamy w zmiennych środowiskowych, żeby zmiana
cennika nie wymagała wdrożenia kodu.
"""

from dataclasses import dataclass

START = "start"
GROW = "grow"
PRO = "pro"

# Poziomy brandingu. Trzy, nie dwa: badanie rozdziela "usuwalne Powered by"
# od pełnej białej etykiety, bo to dwa różne progi cenowe. Klient z GROW chce
# przede wszystkim, żeby widget nie reklamował cudzej firmy; własne logo
# i nazwa to potrzeba dopiero na PRO.
BRANDING_WYMAGANY = "wymagany"  # stopka Sm-art widoczna, bez zmian
BRANDING_USUWALNY = "usuwalny"  # można ukryć stopkę, ale marka zostaje nasza
BRANDING_WLASNY = "wlasny"  # pełna biała etykieta: logo, nazwa, kolory

# Kolejność od najsłabszego do najmocniejszego — pozwala porównywać poziomy
POZIOMY_BRANDINGU = (BRANDING_WYMAGANY, BRANDING_USUWALNY, BRANDING_WLASNY)


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    price_pln: int
    # Cena miesięczna przy płatności rocznej (-20%). Trzymamy obie, bo klient
    # porównuje je na stronie cennika, a rabat nie jest tu do wyliczenia
    # z zaokrągleń w drugą stronę.
    price_pln_yearly: int
    message_limit: int
    branding: str
    # Limity pojemnościowe z badania. Każdy z nich ma egzekwowanie w kodzie —
    # pole bez pilnującej go reguły to obietnica, o której nikt nie pamięta.
    #
    # Dlatego nie ma tu max_bots. Cennik obiecywał 1, 3 i 10 botów, a modelu
    # wielu botów nigdy nie zbudowano; limit szedł w odpowiedzi API i nikt go
    # nie sprawdzał, bo nie było czego. Wróci razem z funkcją, nie przed nią.
    knowledge_base_mb: int
    max_domains: int
    max_seats: int
    # Co ile dni odświeżamy treści pobrane ze stron klienta. None oznacza
    # wyłącznie ręczne odświeżanie — każdy przebieg to pobranie podstron
    # i przeliczenie embeddingów, więc na najniższym planie decyduje klient.
    recrawl_days: int | None
    # Limit żądań na minutę. To zabezpieczenie przed nadużyciem, nie element
    # cennika — komercyjnie plany różni miesięczny limit wiadomości. Wartości
    # są celowo hojne, żeby nigdy nie trafić w prawdziwego odwiedzającego:
    # nawet ruchliwa strona małej firmy nie generuje kilkudziesięciu pytań
    # w ciągu minuty.
    rate_per_minute: int


PLANS = {
    START: Plan(
        START,
        "Start",
        149,
        119,
        2_000,
        branding=BRANDING_WYMAGANY,
        knowledge_base_mb=5,
        max_domains=1,
        max_seats=1,
        recrawl_days=None,
        rate_per_minute=60,
    ),
    GROW: Plan(
        GROW,
        "Grow",
        349,
        279,
        8_000,
        branding=BRANDING_USUWALNY,
        knowledge_base_mb=25,
        max_domains=3,
        max_seats=3,
        recrawl_days=7,
        rate_per_minute=150,
    ),
    PRO: Plan(
        PRO,
        "Pro",
        899,
        719,
        25_000,
        branding=BRANDING_WLASNY,
        knowledge_base_mb=100,
        max_domains=10,
        max_seats=10,
        recrawl_days=1,
        rate_per_minute=500,
    ),
}

# Okres próbny. Rejestracja bez podania karty musi dać działającego bota —
# inaczej klient konfiguruje wszystko, wkleja kod na stronę i dostaje odmowę.
# Limity bierze z najniższego planu: ma poznać produkt, nie dostać go za darmo.
OKRES_PROBNY_DNI = 14
PLAN_PROBNY = START

# Pakiet doliczany po wyczerpaniu limitu. Kupowany świadomie, nie automatycznie:
# auto-doładowanie ma być domyślnie wyłączone, żeby klient nigdy nie zobaczył
# rachunku, na który się nie zgodził.
PAKIET_WIADOMOSCI = 1_000
PAKIET_CENA_PLN = 39

# Progi powiadomień o zużyciu limitu. Ostatni to nie ostrzeżenie, tylko
# informacja, że bot przestał odpowiadać — i musi dotrzeć natychmiast.
PROGI_ALERTOW = (80, 95, 100)

# Ile dni przed koncem subskrypcji uprzedzamy wlasciciela, i moment samego
# konca. Zero znaczy "dzis albo juz po" -- wtedy widget przestal odpowiadac
# i jest to informacja, nie ostrzezenie.
#
# Trzy dni, bo tyle wystarcza, zeby zdazyc cokolwiek zrobic, a jednoczesnie
# na tyle malo, ze wiadomosc nie ginie w skrzynce do czasu, gdy zaczyna byc
# istotna.
PROGI_KONCA_SUBSKRYPCJI = (3, 0)

# Nazwy planów sprzed zmiany cennika. Subskrypcje w bazie trzymają kod planu
# jako tekst, więc bez tej mapy klient kupiony na "basic" trafiłby po zmianie
# w gałąź "plan nierozpoznany" i dostał domyślne, zaniżone limity.
STARE_KODY = {
    "basic": START,
    "enterprise": PRO,
    # "pro" istniał wcześniej i istnieje nadal, ale oznacza teraz wyższy plan.
    # Klient dostanie hojniejszy limit niż kupił — świadomie, bo odwrotna
    # pomyłka odcięłaby działającego klienta od chatbota.
}

# Plan nierozpoznany: subskrypcja sprzed katalogu, brak subskrypcji albo
# literówka w nazwie. Wartość na tyle niska, żeby ograniczyć szkody, i na tyle
# wysoka, żeby nie zablokować prawdziwego klienta, zanim zdążymy poprawić wpis.
DOMYSLNY_LIMIT_NA_MINUTE = 30


def get_plan(code):
    """
    Plan o podanym kodzie albo None.

    Zwracamy None zamiast rzucać, bo w bazie są subskrypcje sprzed katalogu
    z dowolnym tekstem w plan_type. Awaria przy takim wpisie odcięłaby
    działającego klienta od jego chatbota.
    """
    if not code:
        return None
    znormalizowany = str(code).strip().lower()
    znormalizowany = STARE_KODY.get(znormalizowany, znormalizowany)
    return PLANS.get(znormalizowany)


def branding_level(plan_code):
    """
    Poziom brandingu przysługujący planowi.

    Plan spoza katalogu dostaje najwyższy poziom. Odwrotna decyzja odebrałaby
    białą etykietę klientom, którzy mają ją dziś ustawioną, tylko dlatego,
    że ich plan nazywa się inaczej niż w cenniku.
    """
    plan = get_plan(plan_code)
    if plan is None:
        return BRANDING_WLASNY
    return plan.branding


def allows_white_label(plan_code):
    """Czy plan pozwala ustawić własną markę widgetu (logo, nazwa, kolory)."""
    return branding_level(plan_code) == BRANDING_WLASNY


def allows_hiding_branding(plan_code):
    """
    Czy plan pozwala ukryć stopkę "Powered by Sm-art".

    Osobno od białej etykiety, bo to niższy próg: GROW kupuje się właśnie po to,
    żeby widget nie reklamował cudzej firmy, jeszcze bez własnego logo.
    """
    return branding_level(plan_code) in (BRANDING_USUWALNY, BRANDING_WLASNY)


def recrawl_days_for(plan_code):
    """
    Co ile dni odświeżać treści ze stron klienta. None = tylko ręcznie.

    Plan spoza katalogu traktujemy jak najniższy: automatyczne pobieranie
    kosztuje nas ruch i embeddingi przy każdym przebiegu, więc przy
    niepewności nie robimy tego z własnej inicjatywy.
    """
    plan = get_plan(plan_code)
    return plan.recrawl_days if plan else None


def message_limit_for(plan_code, default=2_000):
    plan = get_plan(plan_code)
    return plan.message_limit if plan else default


def rate_for(plan_code):
    """
    Limit żądań na minutę w formacie oczekiwanym przez throttling DRF.

    Wcześniej stawki mieszkały w osobnym słowniku w api/throttles.py, gdzie
    plany nazywały się free/pro/enterprise. Po wprowadzeniu cennika "basic"
    nie pasował do niczego i wpadał w domyślne 20/min — klient płacący
    99 zł był limitowany dokładnie tak jak darmowy. Stawki są teraz przy
    definicji planu, żeby nie dało się dodać planu i zapomnieć o limicie.
    """
    plan = get_plan(plan_code)
    limit = plan.rate_per_minute if plan else DOMYSLNY_LIMIT_NA_MINUTE
    return f"{limit}/min"
