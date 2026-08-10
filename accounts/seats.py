"""
Limit kont w firmie (miejsca / seats).

Cennik obiecuje 1, 3 albo 10 miejsc zależnie od planu, ale nic tego nie
pilnowało: klient planu Start mógł zaprosić dowolną liczbę pracowników.
Ponieważ różnica między planami to nie tylko limit wiadomości, brak tej
kontroli sprawiał, że wyższy plan kupowało się wyłącznie po limit.

Sprawdzamy w dwóch miejscach i celowo w obu: przy wystawianiu zaproszenia,
żeby właściciel dowiedział się od razu, a nie po tym, jak pracownik kliknie
w link i zobaczy błąd; oraz przy jego przyjęciu, bo między jednym a drugim
mogą minąć dni i miejsca mogą się w tym czasie zapełnić.
"""
from rest_framework.exceptions import ValidationError

from accounts.plans import get_plan

def limit_miejsc(tenant):
    """
    Ile kont przysługuje firmie wedle jej planu. None oznacza brak limitu.

    Nieznany plan i brak subskrypcji zostawiamy bez ograniczenia, zamiast
    przyjmować najniższy. Firma w okresie próbnym nie ma jeszcze subskrypcji,
    a limit jednego miejsca zablokowałby jej zapraszanie pracowników zanim
    w ogóle zdecyduje o zakupie.

    Inaczej niż przy bazie wiedzy, gdzie nieznany plan dostaje limit najniższego:
    tam każdy megabajt kosztuje nas embeddingi i magazyn, więc hojność ma cenę.
    Dodatkowe konto nie kosztuje nas nic — jest wyłącznie elementem cennika.
    """
    subskrypcja = getattr(tenant, "subscription", None)
    plan = get_plan(getattr(subskrypcja, "plan_type", None))
    return plan.max_seats if plan else None


def zajete_miejsca(tenant):
    """Liczba istniejących kont w firmie."""
    return tenant.users.count()


def wolne_miejsca(tenant):
    """
    Ile kont można jeszcze dodać. None oznacza brak ograniczenia.

    Nigdy poniżej zera: firma może mieć więcej kont niż limit, jeśli zeszła
    na niższy plan. Nie odbieramy wtedy nikomu konta — blokujemy wyłącznie
    dodawanie nowych.
    """
    limit = limit_miejsc(tenant)
    if limit is None:
        return None
    return max(limit - zajete_miejsca(tenant), 0)


def sprawdz_limit_miejsc(tenant):
    """Rzuca ValidationError, gdy w firmie nie ma już wolnego miejsca."""
    wolne = wolne_miejsca(tenant)
    if wolne is None or wolne > 0:
        return

    limit = limit_miejsc(tenant)
    raise ValidationError(
        f"Twój plan obejmuje {limit} "
        f"{'konto' if limit == 1 else 'kont'} i wszystkie są zajęte. "
        f"Usuń nieużywane konto albo przejdź na wyższy plan."
    )
