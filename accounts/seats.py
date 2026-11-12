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

Od 2.32.24 (przegląd 2026-11, R07) przy wystawianiu zaproszenia i przy
dodawaniu konta liczą się też zaproszenia, które czekają na przyjęcie. Wcześniej
właściciel planu Start mógł rozesłać dowolnie wiele zaproszeń naraz - limit
łapał dopiero przyjęcie, więc wszyscy poza pierwszym klikali w działający
link i dostawali błąd.
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import InvitationToken
from accounts.plans import PLANS, START, get_plan

#: Najdłuższy termin zaproszenia (InvitationToken.DURATION_DELTAS). Starszych
#: nie ma po co czytać z bazy - i tak wygasły.
NAJDLUZSZE_ZAPROSZENIE = timedelta(days=7)


def limit_miejsc(tenant):
    """
    Ile kont przysługuje firmie wedle jej planu. None oznacza brak limitu.

    Brak subskrypcji to limit najniższego planu. Do 2.32.23 był to brak limitu
    z uzasadnieniem, że firma w okresie próbnym nie ma subskrypcji - ale okres
    próbny to wiersz planu Start, więc bez limitu zostawała tylko firma, która
    okresu próbnego nie wzięła i niczego nie kupiła (R07).

    Plan spoza katalogu (subskrypcje sprzed cennika) zostaje bez limitu: panel
    obiecuje, że taki plan zachowuje swoje warunki, a dodatkowe konto nie
    kosztuje nas nic - jest wyłącznie elementem cennika.
    """
    subskrypcja = getattr(tenant, "subscription", None)
    if subskrypcja is None:
        return PLANS[START].max_seats
    plan = get_plan(subskrypcja.plan_type)
    return plan.max_seats if plan else None


def oczekujace_zaproszenia(tenant):
    """Zaproszenia, które jeszcze da się przyjąć - każde rezerwuje miejsce."""
    kandydaci = InvitationToken.objects.filter(
        tenant=tenant,
        users=0,
        max_users__gt=0,
        created_at__gt=timezone.now() - NAJDLUZSZE_ZAPROSZENIE,
    )
    # Termin zależy od `duration`, więc ważność liczy model, nie zapytanie.
    return sum(1 for zaproszenie in kandydaci if zaproszenie.is_valid())


def zajete_miejsca(tenant, z_zaproszeniami=False):
    """
    Liczba istniejących kont w firmie, opcjonalnie z oczekującymi zaproszeniami.

    Przyjęcie zaproszenia liczy same konta: to zaproszenie już zajmuje miejsce,
    o które pyta.
    """
    zajete = tenant.users.count()
    if z_zaproszeniami:
        zajete += oczekujace_zaproszenia(tenant)
    return zajete


def wolne_miejsca(tenant, z_zaproszeniami=False):
    """
    Ile kont można jeszcze dodać. None oznacza brak ograniczenia.

    Nigdy poniżej zera: firma może mieć więcej kont niż limit, jeśli zeszła
    na niższy plan. Nie odbieramy wtedy nikomu konta — blokujemy wyłącznie
    dodawanie nowych.
    """
    limit = limit_miejsc(tenant)
    if limit is None:
        return None
    return max(limit - zajete_miejsca(tenant, z_zaproszeniami), 0)


def sprawdz_limit_miejsc(tenant, z_zaproszeniami=False):
    """
    Rzuca ValidationError, gdy w firmie nie ma już wolnego miejsca.

    `z_zaproszeniami` przy wystawianiu zaproszenia i dodawaniu konta:
    oczekujące zaproszenia też rezerwują miejsca.
    """
    wolne = wolne_miejsca(tenant, z_zaproszeniami)
    if wolne is None or wolne > 0:
        return

    limit = limit_miejsc(tenant)
    if z_zaproszeniami and oczekujace_zaproszenia(tenant):
        raise ValidationError(
            f"Twój plan obejmuje {limit} {_konta(limit)}, a wszystkie są zajęte albo czekają "
            f"na przyjęcie zaproszenia. Cofnij nieaktualne zaproszenie, usuń nieużywane "
            f"konto albo przejdź na wyższy plan."
        )
    raise ValidationError(
        f"Twój plan obejmuje {limit} {_konta(limit)} i wszystkie są zajęte. "
        f"Usuń nieużywane konto albo przejdź na wyższy plan."
    )


def _konta(liczba):
    """1 konto, 3 konta, 10 kont - do 2.32.23 komunikat mówił „3 kont"."""
    if liczba == 1:
        return "konto"
    if liczba % 10 in (2, 3, 4) and liczba % 100 not in (12, 13, 14):
        return "konta"
    return "kont"
