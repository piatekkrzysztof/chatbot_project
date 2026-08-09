"""
Katalog planów — jedno źródło prawdy o cenach, limitach i uprawnieniach.

Dotąd limit wiadomości był luźnym polem na subskrypcji, a to, co klient kupił,
zapisywało się jako dowolny tekst ("pro", "Prymium"). Nic nie łączyło zakupu
z faktycznym limitem: webhook Stripe ustawiał plan na Tenant, a limity
egzekwował zupełnie inny model.

Ceny podane brutto w złotych, dla czytelności — rozliczenie i tak prowadzi
Stripe po stronie swoich cenników. Identyfikatory cen trzymamy w zmiennych
środowiskowych, żeby zmiana cennika nie wymagała wdrożenia kodu.
"""
from dataclasses import dataclass

BASIC = "basic"
PRO = "pro"
ENTERPRISE = "enterprise"


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    price_pln: int
    message_limit: int
    # Biała etykieta to główny wyróżnik płatnych planów: w Basic widget
    # występuje wyłącznie w brandingu Sm-art.
    white_label: bool
    # Limit żądań na minutę. To zabezpieczenie przed nadużyciem, nie element
    # cennika — komercyjnie plany różni miesięczny limit wiadomości. Wartości
    # są celowo hojne, żeby nigdy nie trafić w prawdziwego odwiedzającego:
    # nawet ruchliwa strona małej firmy nie generuje kilkudziesięciu pytań
    # w ciągu minuty.
    rate_per_minute: int


PLANS = {
    BASIC: Plan(BASIC, "Basic", 99, 1_000, white_label=False, rate_per_minute=60),
    PRO: Plan(PRO, "Pro", 199, 5_000, white_label=True, rate_per_minute=150),
    ENTERPRISE: Plan(ENTERPRISE, "Enterprise", 399, 20_000, white_label=True, rate_per_minute=500),
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
    return PLANS.get(str(code).strip().lower())


def allows_white_label(plan_code):
    """
    Czy plan pozwala na własny branding widgetu.

    Plan spoza katalogu traktujemy jako uprawniony. Odwrotna decyzja
    odebrałaby białą etykietę klientom, którzy mają ją dziś ustawioną,
    tylko dlatego, że ich plan nazywa się inaczej niż w cenniku.
    """
    plan = get_plan(plan_code)
    if plan is None:
        return True
    return plan.white_label


def message_limit_for(plan_code, default=1_000):
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
