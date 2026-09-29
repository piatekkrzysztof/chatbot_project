"""
Bilety na pracę AI, przy których nie wiadomo, co się stało.

Każda wiadomość do bota zaczyna się od rezerwacji: krótka transakcja stwierdza
„ten klient ma jeszcze limit", zanim pójdzie zapytanie do OpenAI. Bilet kończy
się zwykle jednym z dwóch wyników - `charged` (praca wykonana, licznik klienta
w górę) albo `released` (nie wykonana, nic nie liczymy).

Jest jednak trzecie wyjście i ono jest tutaj tematem. Gdy worker zginie
w trakcie, `accounts/message_quota.py` celowo NIE zwalnia biletu po cichu, bo
martwy proces mógł zdążyć wywołać OpenAI: darowanie pracy, za którą
zapłaciliśmy, jest równie błędne co obciążenie za pracę niewykonaną. Bilet
dostaje stan `uncertain` i czeka na człowieka.

Na co czekał, skoro nikt nie patrzył
------------------------------------
Na nic. `check_message_reservations` umiała takie bilety wypisać od #44, ale
nie było jej w żadnym harmonogramie ani w żadnym alarmie - narzędzie gotowe,
którego nikt nie woła. To ta sama awaria, przez którą trzy inne zadania nie
działały tygodniami (2.14.1), tyle że o jeden stopień wcześniej: tamte były
w harmonogramie i nie dało się ich wykonać, to nie było w nim wcale.

Co kosztuje jeden nierozliczony bilet
-------------------------------------
Dopóki trwa cykl rozliczeniowy, w którym powstał, liczy się do limitu klienta
dokładnie tak samo jak wiadomość, którą klient dostał - `_reserve_locked`
sumuje `pending` i `uncertain` razem z licznikiem zużycia. Klient płaci więc
za wiadomość, której nie zobaczył. Szkoda jest ograniczona, bo przy nowym
cyklu `cycle_id` się zmienia i bilet przestaje być liczony, ale „ograniczona
do końca miesiąca" to nie to samo co „żadna".

Dlaczego nic tu nie rozlicza się samo
-------------------------------------
Bo to są pieniądze, a `uncertain` znaczy dokładnie tyle, że NIE WIEMY. Automat
musiałby zgadywać: obciążyć klienta za pracę, której mogło nie być, albo
darować pracę, za którą mogliśmy zapłacić OpenAI. Zgadywanie w jedną albo
drugą stronę jest gorsze od czekania, bo nikt się o nim nie dowie. Decyzja
zostaje przy człowieku i przy jawnej komendzie:

    python manage.py check_message_reservations --reservation UUID --outcome charged

Rola harmonogramu kończy się na powiedzeniu, że jest co rozliczać.

Dlaczego `pending` po terminie zostaje `pending`
------------------------------------------------
`reserve_message` przestawia przeterminowane bilety na `uncertain`, ale tylko
dla firmy, która właśnie pisze kolejną wiadomość. U klienta, który od tamtej
pory milczy - albo odszedł - bilet zostaje w `pending` na zawsze. Nie
przestawiamy go stąd, bo to rozróżnienie niesie informację: `uncertain` to
bilet, przy którym ruch trwał dalej, `pending` po terminie to bilet z firmy,
w której od tamtej chwili nie wydarzyło się nic. Raport pokazuje oba, bo oba
wymagają tej samej decyzji.
"""

import logging
from datetime import timedelta

from django.db.models import F, Q
from django.utils import timezone

from accounts.models import MessageReservation

logger = logging.getLogger(__name__)

#: Jak długo trzymamy bilety już rozliczone.
#:
#: Wartość z #44, przeniesiona tutaj bez zmiany. Rozliczony bilet nie niesie
#: treści rozmowy - zostaje firma, znacznik czasu i wynik - ale wiąże się
#: z konkretnym klientem, więc nie ma powodu trzymać go w nieskończoność.
#: Kwartał wystarcza na wyjaśnienie reklamacji „policzyliście mi wiadomość,
#: której nie było"; dłużej nikt do tego nie wraca.
OKRES_ROZLICZONYCH = timedelta(days=90)

#: Ile wierszy obejmuje jedno zapytanie DELETE.
PARTIA = 1000

#: Ile partii w jednym przebiegu. Nie po to, żeby ograniczyć sprzątanie -
#: przy naszym ruchu nigdy nie dojdziemy do tej granicy - tylko po to, żeby
#: pomyłka w warunku nie zamieniła nocnego zadania w pętlę bez końca.
NAJWIECEJ_PARTII = 50


def nierozliczone(teraz=None):
    """Bilety czekające na decyzję człowieka, najstarsze pierwsze."""
    teraz = teraz or timezone.now()
    return MessageReservation.objects.filter(
        Q(state="uncertain") | Q(state="pending", expires_at__lte=teraz)
    ).order_by("created_at")


def rozliczone_do_usuniecia(teraz=None):
    """
    Bilety z zamkniętym wynikiem, starsze niż okres przechowywania.

    Bilety z trwającego cyklu rozliczeniowego zostają niezależnie od wieku: to
    z nich liczy się zużycie, które klient widzi w panelu i na fakturze.
    Warunek jest wprawdzie teoretyczny, bo cykl krótszy niż kwartał nigdy do
    tego wieku nie dożyje, ale kosztuje jedno złączenie i zdejmuje całą klasę
    pomyłek przy zmianie okresu.
    """
    teraz = teraz or timezone.now()
    return MessageReservation.objects.filter(
        finished=True,
        state__in=["charged", "released"],
        created_at__lt=teraz - OKRES_ROZLICZONYCH,
    ).exclude(subscription__billing_cycle_id=F("cycle_id"))


def usun_rozliczone(teraz=None, *, partia=PARTIA, najwiecej_partii=NAJWIECEJ_PARTII):
    """Usuwa rozliczone bilety partiami i zwraca ich liczbę."""
    usuniete = 0
    for _ in range(najwiecej_partii):
        klucze = list(rozliczone_do_usuniecia(teraz).values_list("pk", flat=True)[:partia])
        if not klucze:
            break
        MessageReservation.objects.filter(pk__in=klucze).delete()
        usuniete += len(klucze)
    else:
        # Wyczerpany limit partii, a wiersze wciąż są. Przy naszym ruchu to nie
        # jest zaległość, tylko sygnał, że warunek usuwania łapie coś innego,
        # niż zakładamy.
        logger.warning(
            "Sprzątanie rezerwacji zatrzymane po %s partiach; zostały wiersze do usunięcia",
            najwiecej_partii,
        )
    return usuniete
